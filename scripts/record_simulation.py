"""Record an autoplay run of a scenario ("Production incident: Bookings are down", the default, or "Double bookings") as a Demo-mode recording, with real Ollama.

    backend\\.venv\\Scripts\\python.exe scripts\\record_simulation.py [--scenario opd-bookings-down|opd-double-bookings] [--tries 3] [--variant strong] [--require-model]

Ollama must be running with the models installed (the teammates' replies, the Reviewer of the Submit and the debrief's judges' lines use `qwen25-coder-7b`); this is one GPU job, run it alone.
The scripted learner plays the scenario through the same calls a person makes (about 3 minutes), then the debrief runs; the whole event stream and the project's git history are saved as
recordings/simulation-<scenario>-<variant>/ (simulation-bookings-down-strong, simulation-double-bookings-strong; "Simulation: Double bookings (strong)" in the Demo picker). A take is kept only if the
report is 100/100 for a strong run (a weak run: 30 for each scenario), the debrief finished, no error was emitted and no Reviewer send-back cost a point; otherwise it is deleted and the run is repeated (`--tries`). `--require-model` also insists that
the judges' lines and the coach paragraph are the 7b's (not the template's) in the kept take. Replaying it needs neither Ollama nor a GPU:
    backend\\.venv\\Scripts\\python.exe -m pytest backend\\tests\\test_replay_scenario.py -q
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.session import Settings, SessionManager  # noqa: E402

# per scenario: the recording's name (recordings/<name>-<variant>), its title, the score a take must get and the line on its card
SCENARIOS = {
    "opd-bookings-down": {"name": "simulation-bookings-down", "title": "Simulation: Bookings are down", "expected": {"strong": 100, "weak": 30},
                          "card": {"strong": "Strong run: tests first, both fixes, a regression test, 100/100", "weak": "Weak run: edits first, nudged, a red submit, 30/100"}},
    "opd-double-bookings": {"name": "simulation-double-bookings", "title": "Simulation: Double bookings", "expected": {"strong": 100, "weak": 30},
                            "card": {"strong": "Strong run: the data first, one safe migration, a regression test, 100/100", "weak": "Weak run: a migration that deletes rows, nudged, a red submit, 30/100"}},
}


def wait(fn, timeout: float, what: str):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.5)
    raise TimeoutError(f"timed out waiting for {what}")


def take(settings: Settings, scenario: str, variant: str, name: str, require_model: bool) -> tuple[bool, list[str]]:
    info = SCENARIOS[scenario]
    mgr = SessionManager(settings)
    try:
        s = mgr.start_autoplay(scenario, variant, 1, record_as=name, record_info={"title": f"{info['title']} ({variant})", "app": "Hospital OPD", "feature": info["card"][variant]})
        ev = lambda t: [e for e in list(s.bus.history) if e["type"] == t]  # noqa: E731
        wait(lambda: ev("autoplay_ended"), 1200, "the run to end")
        wait(lambda: (settings.recordings / name / "meta.json").is_file(), 120, "the recording to be written")
        report = (s.orch.debrief.report if s.orch and s.orch.debrief else None) or {}
        bad = []
        if ev("autoplay_ended")[0]["reason"] != "done":
            bad.append(f"the run ended as {ev('autoplay_ended')[0]['reason']}: {ev('autoplay_ended')[0].get('error', '')}")
        if report.get("total") != info["expected"][variant]:
            bad.append(f"the report scored {report.get('total')}, expected {info['expected'][variant]} (a Reviewer send-back or a late update costs points)")
        if ev("debrief_failed") or ev("error"):
            bad.append("an error was emitted: " + "; ".join(str(e.get("message") or e.get("reason")) for e in ev("debrief_failed") + ev("error"))[:300])
        voices = (report.get("fairness") or {}).get("voices") or {}
        print(f"  report {report.get('total')}/100; voices: judges {voices.get('judges')}, coach {voices.get('coach')}" + (f" ({voices['reason']})" if voices.get("reason") else ""))
        if require_model and (voices.get("judges") != "model" or voices.get("coach") != "model"):
            bad.append(f"the 7b did not write every line (judges {voices.get('judges')}, coach {voices.get('coach')}, {voices.get('reason') or 'verifier'}): see fairness.ai_rejected")
        return not bad, bad
    finally:
        mgr.shutdown()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default="opd-bookings-down", choices=sorted(SCENARIOS), help="which scenario to record (default: the first one, so the old command is unchanged)")
    ap.add_argument("--variant", default="strong", choices=["strong", "weak"])
    ap.add_argument("--tries", type=int, default=3)
    ap.add_argument("--require-model", action="store_true", help="keep a take only when the judges' lines and the coach paragraph were written by the 7b")
    args = ap.parse_args()
    settings = Settings.from_env()
    info = SCENARIOS[args.scenario]
    final = f"{info['name']}-{args.variant}"
    for n in range(1, args.tries + 1):
        tmp = f"{final}-take{n}"
        print(f"take {n} of {args.tries}: {args.scenario}, {args.variant} run, real Ollama (about 3 minutes of play, then the debrief)")
        try:
            ok, bad = take(settings, args.scenario, args.variant, tmp, args.require_model)
        except Exception as e:  # noqa: BLE001
            ok, bad = False, [f"{type(e).__name__}: {e}"]
        folder = settings.recordings / tmp
        if ok and (folder / "meta.json").is_file():
            meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
            meta.update(name=final, title=f"{info['title']} ({args.variant})")
            (folder / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            shutil.rmtree(settings.recordings / final, ignore_errors=True)
            folder.rename(settings.recordings / final)
            print(f"KEPT recordings/{final} ({meta['events']} events, {meta['seconds']} s). Check it with: backend\\.venv\\Scripts\\python.exe -m pytest backend\\tests\\test_replay_scenario.py -q")
            return 0
        print("  not kept: " + "; ".join(bad))
        shutil.rmtree(folder, ignore_errors=True)
    print(f"no good take in {args.tries} tries")
    return 1


if __name__ == "__main__":
    sys.exit(main())
