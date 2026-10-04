"""Task E regressions: category options and the shell smoke test with a request in the top slot."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parents[2]


def test_the_spec_options_win_when_the_architect_lists_a_category_differently():
    """Regression (inventory chip, 2 of 3 recordings): 'field category must list the same options everywhere' was sent back to the 7B until it gave up."""
    from app.schemas import normalize_design
    from test_enrich import SPEC, design

    d = design()
    spec = SPEC.model_copy(deep=True)
    spec.resources[0].fields[1].options = ["Low", "Medium", "High"]
    spec.resources[0].fields[1].type = "string"
    name = spec.resources[0].fields[1].name
    for i, e in enumerate(d.endpoints):
        for f in [*e.request_fields, *e.response_fields]:
            if f.name == name:
                f.type, f.options = "string", ["Low", "High"] if i % 2 else ["Low", "Medium", "High", "Urgent"]
    normalize_design(d, spec)
    lists = {tuple(f.options) for e in d.endpoints for f in [*e.request_fields, *e.response_fields] if f.name == name and f.options}
    assert lists == {("Low", "Medium", "High")}


def test_an_error_example_may_send_a_value_that_is_not_an_option():
    from app.schemas import ExampleSpec, ErrorSpec, check_architecture
    from test_enrich import design

    d = design()
    e = next(x for x in d.endpoints if x.method == "POST" and any(f.options for f in x.request_fields))
    field = next(f for f in e.request_fields if f.options)
    e.errors.append(ErrorSpec(status=400, detail="Invalid " + field.name))
    e.examples.append(ExampleSpec(description="Rejects an invalid value", request={field.name: "Not-an-option"}, status=400, response={"detail": "Invalid " + field.name}))
    assert not [p for p in check_architecture(d, ["fastapi-vanilla"], None) if "Rejects an invalid value" in p and "not one of its options" in p]


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_a_request_that_adds_an_element_to_the_top_slot_and_calls_the_kit_passes_the_shell_smoke(tmp_path):
    """Regression (ask-employee recording): the fake browser had no #progress and no UI kit, so Meera's correct progress bar failed test_every_route_renders."""
    out = tmp_path / "app"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "shell_try.py"), "Build Instagram", "--keep", str(out)], capture_output=True, text=True, cwd=ROOT)
    assert "shell smoke ok" in r.stdout, r.stdout + r.stderr
    page, js = out / "static" / "index.html", out / "static" / "app.js"
    page.write_text(page.read_text(encoding="utf-8").replace("<!-- request-hook:top -->", '<!-- request-hook:top -->\n<div id="progress"></div>'), encoding="utf-8")
    js.write_text(js.read_text(encoding="utf-8").replace("// request-hook:loaded", "// request-hook:loaded\n    UI.progress(document.getElementById('progress'), data.items.filter((i) => i.done).length, data.items.length);"), encoding="utf-8")
    r = subprocess.run(["node", str(out / "tests" / "ui" / "shell_smoke.mjs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
