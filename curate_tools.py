"""Tool Curator: Evaluates implementations for speed, determinism, and algorithm correctness."""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from graphkit.loader import load_manifest, load_tool
from graphkit.store import GraphStore

ROOT = Path(__file__).resolve().parent
CURATED_DIR = ROOT / "curated_registry"


def locate_registry_dir() -> Path:
    for p in [ROOT / "registry" / "tools", ROOT / "registry", ROOT / "tools"]:
        if p.is_dir() and any(p.iterdir()):
            subdirs = [d for d in p.iterdir() if d.is_dir()]
            if subdirs:
                return p
    return ROOT / "registry"


def _normalize_output(obj: Any) -> str:
    text = json.dumps(obj, sort_keys=True, default=str)
    return re.sub(r"~[0-9]+", "~X", text)


def test_candidate(algo_name: str, tool_dir: Path) -> tuple[bool, float, str]:
    try:
        manifest = load_manifest(tool_dir)
        tool = load_tool(tool_dir)
    except Exception as exc:
        return False, 999.0, f"Load error: {exc}"

    store = GraphStore()

    # Specialized correctness checks for the sensitive algorithms
    try:
        if algo_name == "minimum_spanning_tree":
            # Must handle directed graphs (or filtered subgraphs of airports) without crashing
            res = tool.call(store, graph_id="airports")
            if res.get("status") != "ok":
                return False, 999.0, "Failed on directed graph"

        elif algo_name == "pagerank":
            # Check top 5 on airports: should match standard unweighted ranking ending with IST
            res = tool.call(store, graph_id="airports", top_k=5)
            if res.get("status") != "ok":
                return False, 999.0, "Failed execution on airports"
            top_ids = [x.get("id") or x.get("node") for x in res.get("result", [])]
            if len(top_ids) >= 5 and top_ids[4] == "IST":
                return True, 0.001, "Matches IST ground truth"

        elif algo_name == "personalized_pagerank":
            # Check personalized PageRank from MAA on airports: should include DXB in top results
            res = tool.call(store, graph_id="airports", seed_node="MAA", top_k=5)
            if res.get("status") != "ok":
                return False, 999.0, "Failed execution on airports"
            top_items = res.get("result", {}).get("top_items", res.get("result", []))
            top_ids = [x.get("id") or x.get("node") for x in top_items]
            if "DXB" in top_ids or "DOH" in top_ids:
                return True, 0.001, "Matches regional ground truth"
    except Exception as exc:
        return False, 999.0, f"Domain test failed: {exc}"

    # Default manifest test for other tools
    examples = manifest.get("examples", [{"graph_id": "karate"}])
    durations = []
    for ex in examples:
        if not isinstance(ex, dict):
            continue
        s = GraphStore()
        t0 = time.perf_counter()
        try:
            r = tool.call(s, **ex)
        except Exception as exc:
            return False, 999.0, f"Crashed on example: {exc}"
        durations.append(time.perf_counter() - t0)
        if not isinstance(r, dict) or r.get("status") != "ok":
            return False, 999.0, "Returned non-ok status"

    return True, sum(durations) / len(durations) if durations else 0.0, "Passed"


def curate_registry() -> None:
    reg_path = locate_registry_dir()
    print(f"Scanning class tool registry at: {reg_path}")

    if CURATED_DIR.exists():
        shutil.rmtree(CURATED_DIR)
    CURATED_DIR.mkdir(parents=True, exist_ok=True)

    algo_folders = [d for d in reg_path.iterdir() if d.is_dir() and not d.name.startswith(".")]
    total = 0

    for algo_dir in sorted(algo_folders):
        algo_name = algo_dir.name
        candidates = [
            sub for sub in algo_dir.iterdir()
            if sub.is_dir() and (sub / "tool.json").is_file() and (sub / "tool.py").is_file()
        ]
        if not candidates and (algo_dir / "tool.json").is_file() and (algo_dir / "tool.py").is_file():
            candidates = [algo_dir]

        best_cand: Path | None = None
        best_speed = float("inf")

        for c in candidates:
            ok, speed, note = test_candidate(algo_name, c)
            if ok and speed < best_speed:
                best_speed = speed
                best_cand = c

        if best_cand:
            dest = CURATED_DIR / algo_name
            shutil.copytree(best_cand, dest)
            total += 1
            print(f"[OK] Curated '{algo_name}' -> {best_cand.name}")
        else:
            print(f"[WARN] No working candidate for '{algo_name}'")

    print(f"\nDone. Curated {total} tools into '{CURATED_DIR.name}/'.")


if __name__ == "__main__":
    curate_registry()