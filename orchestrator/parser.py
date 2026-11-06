"""Output parser and schema normalizer for orchestrator results."""
from __future__ import annotations

import json
import re
from typing import Any

VALID_STATUSES = {"answered", "clarification_needed", "unsupported", "error"}
VALID_TYPES = {"number", "boolean", "node", "node_list", "path", "text"}


def _extract_node_id(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("id") or item.get("node") or "")
    return str(item).strip()


def _clean_value_for_type(val: Any, val_type: str) -> Any:
    if val_type == "number":
        if isinstance(val, (int, float)):
            return val
        text = str(val).strip().replace(",", "")
        # Find first number in text if string contains words
        match = re.search(r"[-+]?\d*\.?\d+", text)
        if match:
            num_str = match.group(0)
            return float(num_str) if "." in num_str else int(num_str)
        return 0

    if val_type == "boolean":
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("true", "yes", "1")

    if val_type == "node":
        return _extract_node_id(val)

    if val_type in ("node_list", "path"):
        if isinstance(val, list):
            return [_extract_node_id(x) for x in val if x is not None]
        if isinstance(val, (str, dict)):
            nid = _extract_node_id(val)
            return [nid] if nid else []
        return []

    if val_type == "text":
        return str(val) if val is not None else ""

    return val


def parse_orchestrator_output(
    query_id: str,
    raw_text: str,
    tools_used: list[str],
    trace_path: str,
) -> dict[str, Any]:
    cleaned_tools = list(dict.fromkeys(tools_used))
    json_payload: dict[str, Any] | None = None

    # 1. Match fenced JSON block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if match:
        try:
            json_payload = json.loads(match.group(1))
        except Exception:
            pass

    # 2. Try raw JSON
    if json_payload is None:
        try:
            json_payload = json.loads(raw_text.strip())
        except Exception:
            pass

    # 3. Handle parsed JSON object
    if isinstance(json_payload, dict):
        status = str(json_payload.get("status", "answered")).lower()
        if status not in VALID_STATUSES:
            status = "answered"

        ans_obj = json_payload.get("answer", {})
        if not isinstance(ans_obj, dict):
            ans_obj = {"type": "text", "value": str(ans_obj)}

        ans_type = str(ans_obj.get("type", "text")).lower()
        if ans_type not in VALID_TYPES:
            ans_type = "text"

        raw_val = ans_obj.get("value")
        clean_val = _clean_value_for_type(raw_val, ans_type)

        if status in ("clarification_needed", "unsupported"):
            ans_type = "text"
            clean_val = ""

        formatted_answer: dict[str, Any] = {
            "type": ans_type,
            "value": clean_val,
        }

        if "ordered" in ans_obj:
            formatted_answer["ordered"] = bool(ans_obj["ordered"])
        elif ans_type == "node_list" and (
            "ordered" in json_payload or "top" in raw_text.lower() or "rank" in raw_text.lower()
        ):
            formatted_answer["ordered"] = True

        return {
            "query_id": query_id,
            "status": status,
            "answer_text": str(json_payload.get("answer_text", raw_text)).strip(),
            "answer": formatted_answer,
            "tools_used": cleaned_tools,
            "trace_file": trace_path,
        }

    # 4. Fallback heuristics if parsing failed completely
    lower = raw_text.lower()
    if any(k in lower for k in ("clarification", "ambiguous", "specify", "unclear")):
        status = "clarification_needed"
        ans_type = "text"
        val: Any = ""
    elif any(k in lower for k in ("unsupported", "cannot answer", "not supported", "no tool", "not present")):
        status = "unsupported"
        ans_type = "text"
        val = ""
    else:
        status = "answered"
        # Extract number if raw text contains digits
        num_match = re.search(r"\b\d[\d,]*\b", raw_text)
        if num_match:
            ans_type = "number"
            val = int(num_match.group(0).replace(",", ""))
        else:
            ans_type = "text"
            val = raw_text.strip()

    return {
        "query_id": query_id,
        "status": status,
        "answer_text": raw_text.strip(),
        "answer": {"type": ans_type, "value": val},
        "tools_used": cleaned_tools,
        "trace_file": trace_path,
    }