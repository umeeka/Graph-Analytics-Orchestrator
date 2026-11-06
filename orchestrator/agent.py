"""Agent execution engine: manages tool calling, auto-structuring, and trace logging."""
from __future__ import annotations

import json
from pathlib import Path
import re
import time
from typing import Any

from graphkit.loader import discover
from graphkit.llm import make_client, model_name, tool_schema
from graphkit.store import GraphStore
from graphkit.trace import Trace

from orchestrator.parser import parse_orchestrator_output
from orchestrator.prompts import build_system_prompt

MAX_CALL_BUDGET = 6


def _compress_schema(manifest: dict[str, Any]) -> dict[str, Any]:
    """Compresses a tool schema to save tokens and makes optional parameters nullable."""
    raw = tool_schema(manifest)
    fn = raw.get("function", {})

    desc = fn.get("description", "").split(". ")[0].strip()
    if not desc.endswith("."):
        desc += "."
    fn["description"] = desc

    params = fn.get("parameters", {})
    props = params.get("properties", {})
    required = set(params.get("required", []))

    for prop_name, spec in props.items():
        if isinstance(spec, dict):
            if "description" in spec:
                spec["description"] = spec["description"].split(". ")[0].strip()

            # Allow null for optional fields so Groq doesn't reject `field: null`
            if prop_name not in required and "type" in spec:
                t = spec["type"]
                if isinstance(t, str) and t != "null":
                    spec["type"] = [t, "null"]

    return raw

def _call_llm_with_retry(client: Any, **kwargs: Any) -> Any:
    """Wraps completions call with exponential backoff on HTTP 429 rate limits."""
    for attempt in range(5):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as exc:
            err_msg = str(exc)
            if "429" in err_msg or "rate limit" in err_msg.lower():
                wait_sec = 2.5 * (attempt + 1)
                print(f"  [Rate limit 429 reached on Groq. Cooling down for {wait_sec:.1f}s...]")
                time.sleep(wait_sec)
            else:
                raise exc
    return client.chat.completions.create(**kwargs)


def _ensure_structured_json(client: Any, model: str, question: str, raw_text: str) -> str:
    """If the LLM replied in conversational prose, converts it into the exact required JSON schema."""
    if "```json" in raw_text or ('"status"' in raw_text and '"answer"' in raw_text):
        return raw_text

    structuring_messages = [
        {
            "role": "system",
            "content": (
                "You are a strict data formatter. Take the natural language answer to the graph question "
                "and convert it into the EXACT required JSON format.\n"
                "Output ONLY a ```json ... ``` block. No conversational text.\n\n"
                "SCHEMA:\n"
                "```json\n"
                "{\n"
                '  "status": "answered" | "clarification_needed" | "unsupported",\n'
                '  "answer_text": "<concise explanation>",\n'
                '  "answer": {\n'
                '    "type": "number" | "boolean" | "node" | "node_list" | "path" | "text",\n'
                '    "value": <extracted_value>,\n'
                '    "ordered": true | false\n'
                "  }\n"
                "}\n"
                "```\n"
                "RULES:\n"
                "- 'number': numeric scalar (e.g. 20058, 2, 0.4324)\n"
                "- 'node': single node ID string (e.g. 'FRA', 'MUC', 'm2')\n"
                "- 'node_list': array of node ID strings (e.g. ['FRA', 'CDG']). Set 'ordered': true if ranked.\n"
                "- 'path': ordered array of node ID strings along the route (e.g. ['MAA', 'DEL', 'JFK'])\n"
                "- 'boolean': true or false\n"
                "- 'text': empty string \"\" for 'clarification_needed' and 'unsupported'"
            ),
        },
        {
            "role": "user",
            "content": f"Question: {question}\nRaw Answer: {raw_text}",
        },
    ]

    try:
        res = _call_llm_with_retry(
            client,
            model=model,
            messages=structuring_messages,
            temperature=0.0,
        )
        return res.choices[0].message.content or raw_text
    except Exception:
        return raw_text


class GraphOrchestrator:
    def __init__(self, tools_dir: Path, infra_dir: Path):
        self.store = GraphStore()
        discovered = discover(infra_dir, tools_dir)
        self.tools = {t.name: t for t in discovered}
        self.client = make_client()
        self.model = model_name()
        self.schemas = [_compress_schema(t.manifest) for t in self.tools.values()]

    def run_query(self, query_id: str, question: str, trace_path: Path) -> dict[str, Any]:
        trace = Trace(trace_path)
        trace.question(question)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(self.store)},
            {"role": "user", "content": question},
        ]

        tools_invoked: list[str] = []
        active_subgraph_id: str | None = None

        for _ in range(MAX_CALL_BUDGET):
            response = _call_llm_with_retry(
                self.client,
                model=self.model,
                messages=messages,
                tools=self.schemas if self.schemas else None,
                tool_choice="auto" if self.schemas else None,
                temperature=0.0,
            )

            msg = response.choices[0].message
            trace.llm_call(self.model, msg)
            messages.append(msg)

            # If no tools called, synthesize final output
            if not msg.tool_calls:
                raw_text = msg.content or ""
                structured_text = _ensure_structured_json(self.client, self.model, question, raw_text)
                trace.final_answer(structured_text)

                return parse_orchestrator_output(
                    query_id=query_id,
                    raw_text=structured_text,
                    tools_used=tools_invoked,
                    trace_path=str(trace_path),
                )

            # Execute tool calls
            for call in msg.tool_calls:
                raw_name = call.function.name
                fn_name = re.sub(r"<\|.*?\|>.*", "", raw_name).strip()
                if fn_name.endswith("commentary"):
                    fn_name = fn_name.replace("commentary", "").strip()

                try:
                    fn_args = json.loads(call.function.arguments) if call.function.arguments else {}
                except Exception as exc:
                    fn_args = {}
                    tool_output = {"status": "error", "error": f"Invalid arguments: {exc}"}
                else:
                    if fn_name in self.tools:
                        tool_ref = self.tools[fn_name]

                        # Safely resolve parameters across both Tool and BoundTool classes
                        manifest = getattr(tool_ref, "manifest", {})
                        params_meta = getattr(tool_ref, "parameters", None) or manifest.get("parameters", {})
                        tool_props = params_meta.get("properties", {}) if isinstance(params_meta, dict) else {}

                        # Only inject graph_id if the tool actually takes graph_id
                        if "graph_id" in tool_props and "graph_id" not in fn_args and active_subgraph_id:
                            fn_args["graph_id"] = active_subgraph_id

                        tools_invoked.append(tool_ref.implementation_id)
                        tool_output = tool_ref.call(self.store, **fn_args)

                        if isinstance(tool_output, dict) and tool_output.get("result_graph_id"):
                            active_subgraph_id = tool_output["result_graph_id"]
                    else:
                        tool_output = {"status": "error", "error": f"Tool '{fn_name}' not available."}

                trace.tool_call(fn_name, fn_args, tool_output)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": fn_name,
                    "content": json.dumps(tool_output, default=str),
                })

        fallback_msg = "Step budget exhausted."
        trace.error(fallback_msg)
        return parse_orchestrator_output(
            query_id=query_id,
            raw_text=fallback_msg,
            tools_used=tools_invoked,
            trace_path=str(trace_path),
        )