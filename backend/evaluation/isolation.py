"""Executable truth/runtime package boundary check."""

import ast
import inspect
from pathlib import Path


def assert_isolated(root: Path) -> None:
    from friendly_filter.runlog import run_scenario

    runtime = root / "backend/friendly_filter"
    for path in runtime.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "TRUTH_PATH" in source:
            raise AssertionError(f"truth path in runtime: {path}")
        tree = ast.parse(source)
        names = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        names += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        if any(name and (name == "evaluation" or name.startswith("evaluation.")) for name in names):
            raise AssertionError(f"evaluator import in runtime: {path}")
    if any("truth" in name.lower() for name in inspect.signature(run_scenario).parameters):
        raise AssertionError("runtime accepts a truth input")
