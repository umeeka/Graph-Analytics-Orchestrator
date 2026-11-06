"""loader.py: Registry tool discovery, manifest parsing, and GraphStore execution binding."""
from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from graphkit.store import GraphStore


@dataclass
class BoundTool:
    """A tool whose execution is bound to a GraphStore instance."""

    name: str
    implementation_id: str
    description: str
    parameters: dict[str, Any]
    manifest: dict[str, Any]
    run_fn: Callable[..., dict]
    path: Path

    def call(self, store: GraphStore, **params: Any) -> dict[str, Any]:
        """Safely invokes the tool with store as the first positional parameter."""
        try:
            return self.run_fn(store, **params)
        except Exception as exc:
            return {
                "status": "error",
                "result": None,
                "summary": f"Tool '{self.name}' crashed: {type(exc).__name__}: {exc}",
                "result_graph_id": None,
                "error": f"Tool '{self.name}' crashed: {type(exc).__name__}: {exc}",
            }


def load_tool_from_directory(tool_dir: Path | str) -> BoundTool | None:
    """Loads a single tool from its directory containing tool.json and tool.py."""
    tool_dir = Path(tool_dir).resolve()
    json_path = tool_dir / "tool.json"
    py_path = tool_dir / "tool.py"

    if not json_path.is_file() or not py_path.is_file():
        return None

    try:
        manifest = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    module_name = f"tool_{manifest.get('name', 'unknown')}_{abs(hash(str(tool_dir)))}"
    spec = importlib.util.spec_from_file_location(module_name, py_path)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None

    run_fn = getattr(module, "run", None)
    if not callable(run_fn):
        return None

    return BoundTool(
        name=manifest.get("name", tool_dir.name),
        implementation_id=manifest.get("implementation_id", manifest.get("name", tool_dir.name)),
        description=manifest.get("description", ""),
        parameters=manifest.get("parameters", {}),
        manifest=manifest,
        run_fn=run_fn,
        path=tool_dir,
    )


def discover_tools(*roots: Path | str) -> dict[str, BoundTool]:
    """Discovers all tools across specified directory roots, indexed by tool name."""
    tools: dict[str, BoundTool] = {}
    for root in roots:
        root_path = Path(root).resolve()
        if not root_path.is_dir():
            continue
        for json_path in sorted(root_path.rglob("tool.json")):
            tool_folder = json_path.parent
            if "template" in tool_folder.parts:
                continue
            tool = load_tool_from_directory(tool_folder)
            if tool:
                tools[tool.name] = tool
    return tools