"""What a finished build is made of, in numbers a judge can read on its demo card: tables, endpoints, pages, functions, lines, and how much the agents wrote.

Read from the project itself (`.q/design.json`, the `.q/authorship.json` that every build writes), so nothing is estimated.
"""
from __future__ import annotations

import json
from pathlib import Path


def project_stats(root: Path | str) -> dict:
    root = Path(root)
    try:
        design = json.loads((root / ".q" / "design.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    modules = len(design.get("resources") or []) or 1
    stats = {"modules": modules, "tables": len(design.get("tables", [])), "endpoints": len(design.get("endpoints", [])), "pages": 2 + 2 * modules}  # dashboard, About, a list and a detail page per module
    try:
        app = json.loads((root / ".q" / "authorship.json").read_text(encoding="utf-8")).get("app", {})
    except (OSError, ValueError):
        app = {}
    if app:
        stats.update(functions=app.get("functions", 0), lines=app.get("lines", 0), agent_share_functions=app.get("agent_share_functions", 0.0), agent_share_lines=app.get("agent_share_lines", 0.0),
                     functions_repair=app.get("functions_repair", 0))
    return stats


def stats_line(stats: dict) -> str:
    """'4 modules, 4 tables, 41 endpoints, 10 pages, 62 functions (71% written by agents), 1,240 lines'."""
    if not stats:
        return ""
    parts = [f"{stats['modules']} modules" if stats.get("modules", 1) > 1 else "1 module", f"{stats['tables']} tables", f"{stats['endpoints']} endpoints", f"{stats['pages']} pages"]
    if "functions" in stats:
        repaired = f", {stats['functions_repair']} repaired from the contract" if stats.get("functions_repair") else ""
        parts.append(f"{stats['functions']} functions ({round(100 * stats['agent_share_functions'])}% written by agents{repaired})")
        parts.append(f"{stats['lines']:,} lines")
    return ", ".join(parts)
