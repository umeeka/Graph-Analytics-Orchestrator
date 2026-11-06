"""CLI runner script for the Graph Analytics Orchestrator.

Fulfills Rule 7:
    python run_queries.py --queries <file> --out answers.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from orchestrator.agent import GraphOrchestrator

DEFAULT_TOOLS_DIR = ROOT / "curated_registry"
DEFAULT_INFRA_DIR = ROOT / "infra_tools"
DEFAULT_TRACES_DIR = ROOT / "traces"


def load_input_queries(file_path: Path) -> list[tuple[str, str]]:
    """Loads query pairs (query_id, question_text) from JSON or line-based text files."""
    if not file_path.is_file():
        raise FileNotFoundError(f"Queries file not found at: {file_path}")

    raw_content = file_path.read_text(encoding="utf-8").strip()
    extracted: list[tuple[str, str]] = []

    # 1. Parse JSON formatted query list
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

    # 2. Line-by-line fallback (for .txt or .jsonl)
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
        help="Path to input query file (e.g. public_queries.json)",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Path to output answers file (e.g. answers_public.json)",
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
        help="Directory to record .jsonl trace files",
    )
    args = parser.parse_args()

    # Verify that an LLM API key is accessible in the environment
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print(
            "ERROR: Missing API key. Set the 'LLM_API_KEY' or 'GEMINI_API_KEY' "
            "environment variable before running.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Ensure traces and destination directories exist
    args.traces.mkdir(parents=True, exist_ok=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    queries = load_input_queries(args.queries)
    print(f"Loaded {len(queries)} queries from '{args.queries}'.")
    print(f"Discovering tools from: {args.tools}")

    orchestrator = GraphOrchestrator(tools_dir=args.tools, infra_dir=args.infra)
    all_answers: list[dict[str, Any]] = []

    for idx, (qid, query_text) in enumerate(queries, 1):
        print(f"\n[{idx}/{len(queries)}] Processing {qid}: \"{query_text}\"")
        trace_file = args.traces / f"{qid}.jsonl"

        try:
            result = orchestrator.run_query(
                query_id=qid,
                question=query_text,
                trace_path=trace_file,
            )
        except Exception as exc:
            print(f"  -> Execution Error on {qid}: {exc}")
            result = {
                "query_id": qid,
                "status": "error",
                "answer_text": f"Execution error: {exc}",
                "answer": {"type": "text", "value": ""},
                "tools_used": [],
                "trace_file": str(trace_file),
            }

        print(f"  -> Status: {result['status']} | Type: {result['answer']['type']} | Tools: {result['tools_used']}")
        all_answers.append(result)

    # Persist all responses formatted with 2-space indentation
    args.out.write_text(json.dumps(all_answers, indent=2), encoding="utf-8")
    print(f"\nExecution complete. Saved {len(all_answers)} results to '{args.out}'.")


if __name__ == "__main__":
    main()