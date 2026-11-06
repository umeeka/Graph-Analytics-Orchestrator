"""CLI runner script for the Graph Analytics Orchestrator.

Supports full evaluation as well as selective query reruns:
    python run_queries.py --queries public_queries.json --out answers_public.json
    python run_queries.py --queries public_queries.json --out answers_public.json --only q04 q18 q20
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from orchestrator.agent import GraphOrchestrator

DEFAULT_TOOLS_DIR = ROOT / "curated_registry"
DEFAULT_INFRA_DIR = ROOT / "infra_tools"
DEFAULT_TRACES_DIR = ROOT / "traces"

from dotenv import load_dotenv
load_dotenv()
def load_input_queries(file_path: Path) -> list[tuple[str, str]]:
    if not file_path.is_file():
        raise FileNotFoundError(f"Queries file not found at: {file_path}")

    raw_content = file_path.read_text(encoding="utf-8").strip()
    extracted: list[tuple[str, str]] = []

    if file_path.suffix == ".json" or raw_content.startswith("[") or raw_content.startswith("{"):
        try:
            parsed = json.loads(raw_content)
            if isinstance(parsed, list):
                for idx, entry in enumerate(parsed, 1):
                    if isinstance(entry, dict):
                        qid = str(entry.get("query_id") or f"q{idx:02d}")
                        qtext = str(entry.get("query") or entry.get("question") or "")
                        extracted.append((qid, qtext))
                    else:
                        extracted.append((f"q{idx:02d}", str(entry)))
            elif isinstance(parsed, dict):
                for qid, qtext in parsed.items():
                    extracted.append((str(qid), str(qtext)))
            return extracted
        except json.JSONDecodeError:
            pass

    for idx, line in enumerate(raw_content.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("{"):
            try:
                row = json.loads(line)
                qid = str(row.get("query_id") or f"q{idx:02d}")
                qtext = str(row.get("query") or row.get("question") or "")
                extracted.append((qid, qtext))
                continue
            except json.JSONDecodeError:
                pass

        extracted.append((f"q{idx:02d}", line))

    return extracted


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Graph Analytics Orchestrator Runner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--queries",
        required=True,
        type=Path,
        help="Path to input query file",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Path to output answers file",
    )
    parser.add_argument(
        "--tools",
        default=DEFAULT_TOOLS_DIR,
        type=Path,
        help="Path to curated tools directory",
    )
    parser.add_argument(
        "--infra",
        default=DEFAULT_INFRA_DIR,
        type=Path,
        help="Path to infra tools directory",
    )
    parser.add_argument(
        "--traces",
        default=DEFAULT_TRACES_DIR,
        type=Path,
        help="Directory to store .jsonl trace files",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        help="Space-separated list of specific query IDs to run (e.g. --only q04 q18)",
    )
    args = parser.parse_args()

    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: Missing API key environment variable.", file=sys.stderr)
        sys.exit(1)

    args.traces.mkdir(parents=True, exist_ok=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    all_queries = load_input_queries(args.queries)

    # Filter by --only if specified
    if args.only:
        targets = set(args.only)
        queries_to_run = [item for item in all_queries if item[0] in targets]
        print(f"Running selective rerun for {len(queries_to_run)} queries: {sorted(targets)}")
    else:
        queries_to_run = all_queries
        print(f"Loaded {len(queries_to_run)} queries from '{args.queries}'.")

    # Load existing answers to merge into if output file already exists
    existing_map: dict[str, dict[str, Any]] = {}
    if args.out.is_file():
        try:
            prev_data = json.loads(args.out.read_text(encoding="utf-8"))
            if isinstance(prev_data, list):
                for item in prev_data:
                    if isinstance(item, dict) and "query_id" in item:
                        existing_map[item["query_id"]] = item
        except Exception:
            pass

    orchestrator = GraphOrchestrator(tools_dir=args.tools, infra_dir=args.infra)

    for idx, (qid, query_text) in enumerate(queries_to_run, 1):
        print(f"\n[{idx}/{len(queries_to_run)}] Processing {qid}: \"{query_text}\"")
        trace_file = args.traces / f"{qid}.jsonl"
        relative_trace = f"traces/{qid}.jsonl"

        try:
            result = orchestrator.run_query(
                query_id=qid,
                question=query_text,
                trace_path=trace_file,
            )
            result["trace_file"] = relative_trace
        except Exception as exc:
            print(f"  -> Execution Error on {qid}: {exc}")
            result = {
                "query_id": qid,
                "status": "error",
                "answer_text": f"Execution error: {exc}",
                "answer": {"type": "text", "value": ""},
                "tools_used": [],
                "trace_file": relative_trace,
            }

        print(f"  -> Status: {result['status']} | Type: {result['answer']['type']} | Tools: {result['tools_used']}")
        existing_map[qid] = result

        # Small pause to avoid hitting Groq's 8,000 TPM limit
        time.sleep(1.5)

    # Sort final records by query_id and write back
    sorted_answers = [existing_map[k] for k in sorted(existing_map.keys())]
    args.out.write_text(json.dumps(sorted_answers, indent=2), encoding="utf-8")
    print(f"\nSaved updated results ({len(sorted_answers)} total) to '{args.out}'.")


if __name__ == "__main__":
    main()