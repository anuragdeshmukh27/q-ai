"""Static checks on a generated page's script, shared by Q's own tests and by the generated project's UI test.

The generated project cannot import from Q, so `contract_tests.py` copies this file's text into `tests/ui/test_script.py`.
Keep it dependency-free (only `re`) and compatible with plain `import re` at the top of the copied file.
"""
import re


def balanced(js, start, open_ch, close_ch):
    """Index just after the bracket that closes the one opened just before js[start]."""
    depth, i = 1, start
    while i < len(js) and depth:
        depth += 1 if js[i] == open_ch else -1 if js[i] == close_ch else 0
        i += 1
    return i


def action_spans(js):
    """(start, end) of every `actions: [ ... ]` array: the buttons of a list row."""
    return [(m.end(), balanced(js, m.end(), "[", "]")) for m in re.finditer(r"actions\s*:\s*\[", js)]


_NAMED = re.compile(r"function\s+(\w+)\s*\(|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:function\s*\w*\s*)?(?:\([^)]*\)|\w+)\s*(?:=>)?\s*(?=\{)")


def named_functions(js):
    """name -> (start, end) of the body of every named function, or arrow function assigned to a name."""
    out = {}
    for m in _NAMED.finditer(js):
        brace = js.find("{", m.end())
        if brace != -1:
            out.setdefault(m.group(1) or m.group(2), (brace + 1, balanced(js, brace + 1, "{", "}")))
    return out


def reachable_bodies(js):
    """Bodies of the functions a list button can reach: named in an action, or called by a function that is reachable."""
    funcs = named_functions(js)
    names = {n for a, b in action_spans(js) for n in re.findall(r"(\w+)\s*\(", js[a:b])}
    seen = set()
    while names - seen:
        name = (names - seen).pop()
        seen.add(name)
        if name in funcs:
            a, b = funcs[name]
            names |= set(re.findall(r"(\w+)\s*\(", js[a:b]))
    return [funcs[n] for n in seen if n in funcs]


def called_from_a_button(js, method, base, suffix=""):
    """True when a fetch of `method` to `base`/... sits inside an action or inside a function that an action reaches."""
    spans = action_spans(js) + reachable_bodies(js)
    for m in re.finditer(r"fetch\(", js):
        window = js[m.end():balanced(js, m.end(), "(", ")")]  # the arguments of this one fetch call
        if base in window and re.search(r"method\s*:\s*['\"`]" + method, window, re.I) and (not suffix or suffix in window):
            if any(a <= m.start() < b for a, b in spans):
                return True
    return False
