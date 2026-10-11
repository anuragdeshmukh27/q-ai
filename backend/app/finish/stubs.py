"""Rules put the missing routes into the project as placeholder functions in the project's own style, so the engineer only has to fill bodies
(`implement`), the one edit a 7B model does reliably; it never has to invent a decorator, a router or an import."""
from __future__ import annotations

import re

from .analyze import Analysis, Gap, Route


def _local(full: str, prefix: str) -> str:
    return full[len(prefix):] or "/" if prefix and full.startswith(prefix) else full


def _is_id(name: str) -> bool:
    return name == "id" or name.endswith("_id")


def function_name(method: str, local: str, taken: set[str]) -> str:
    words = [w for w in re.split(r"[^a-zA-Z0-9]+", re.sub(r"\{[^}]*\}", "", local)) if w]
    base = "_".join([method.lower(), *words]) or method.lower()
    name, n = base, 1
    while name in taken:
        n += 1
        name = f"{base}_{n}"
    taken.add(name)
    return name


def stub_source(a: Analysis, g: Gap, var: str, prefix: str, taken: set[str]) -> tuple[str, str]:
    """(the placeholder function's source, its name)"""
    local = _local(g.path, prefix)
    params = re.findall(r"\{([^}]+)\}", local)
    name = function_name(g.method, local, taken)
    if a.framework == "fastapi":
        args = [f"{p}: {'int' if _is_id(p) else 'str'}" for p in params] + (["body: dict"] if g.method in ("POST", "PUT", "PATCH") else [])
        deco = f'@{var}.{g.method.lower()}("{local}")'
    else:
        args = list(params)
        flask_path = re.sub(r"\{([^}]+)\}", lambda m: f"<int:{m.group(1)}>" if _is_id(m.group(1)) else f"<{m.group(1)}>", local)
        deco = f'@{var}.route("{flask_path}", methods=["{g.method}"])'
    return f"{deco}\ndef {name}({', '.join(args)}):\n    # missing endpoint: {g.title}\n    raise NotImplementedError\n", name


def insert(source: str, stubs: list[str]) -> str:
    """The stubs go before an `if __name__ == "__main__":` block, else at the end."""
    block = "\n\n\n".join(s.rstrip("\n") for s in stubs) + "\n"
    m = re.search(r"^if __name__ ?== ?[\"']__main__[\"']\s*:", source, re.M)
    if m:
        return source[:m.start()].rstrip("\n") + "\n\n\n" + block + "\n\n" + source[m.start():]
    return source.rstrip("\n") + "\n\n\n" + block


def router_of(routes: list[Route], file: str) -> tuple[str, str]:
    """(variable, prefix) the existing routes of a file hang on; ('router', '') guess when there are none."""
    r = next((x for x in routes if x.file == file and x.var), None)
    return (r.var, r.prefix) if r else ("app", "")
