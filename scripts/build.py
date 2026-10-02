"""P2 check: the full team builds an app from a goal (Architect -> Planner -> engineers -> verification).

    backend\.venv\Scripts\python.exe scripts\build.py "Build a calculator with history" [--serve]

Everything runs on local models unless --allow-cloud is given.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from solo import cli_approver, printer as solo_printer  # noqa: E402

from app.config import load_env  # noqa: E402
from app.events import EventBus  # noqa: E402
from app.llm import LLMClient  # noqa: E402
from app.orchestrator import Orchestrator  # noqa: E402
from app.registry import ModelRegistry  # noqa: E402


def printer(e: dict) -> None:
    t = e["type"]
    if t == "project_created":
        print(f"\n== project {e['slug']} ({e['preset']})")
    elif t == "architecture_ready":
        print(f"== architecture ready: {e['endpoints']} endpoints, {e['tables']} tables")
    elif t == "contract_updated":
        print(f"== contract v{e['version']}: {', '.join(e['endpoints'])}")
    elif t == "plan_created":
        print("== plan" + (" (re-planned)" if e.get("replan") else ""))
        for x in e["tasks"]:
            print(f"   {x['id']} [{x['owner']}] {x['title']}  <- {','.join(x['depends_on']) or '-'}")
    elif t == "task_assigned":
        print(f"\n>> {e['task']} {e['title']} -> {e['agent']} ({e['model']})")
    elif t == "project_progress":
        print(f"   progress {e['percent']}% ({e['done']}/{e['total']})")
    elif t == "message_sent":
        print(f"    message {e['from']} -> {e['to']}: {e['text'][:100]}")
    elif t == "consultant_called":
        print(f"** SENIOR CONSULTANT ** {e['message']}")
    elif t == "consultant_result":
        print(f"** consultant {'solved' if e['ok'] else 'did not solve'} {e['task']} ({e['iterations']} iterations)")
    elif t == "app_running":
        print(f"== app running at {e['url']}")
    elif t == "agent_state" and e["state"] in ("thinking",) and e["agent"] in ("architect", "planner"):
        print(f"[{e['agent']}] thinking...")
    else:
        solo_printer(e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("goal")
    ap.add_argument("--mode", default="autonomous", choices=["assisted", "supervised", "autonomous"])
    ap.add_argument("--preset")
    ap.add_argument("--allow-cloud", action="store_true", help="permit cloud models (default: local only)")
    ap.add_argument("--consultant", action="store_true", help="after two local escalations, retry the task once on a cloud model (needs GEMINI_API_KEY); logged as a senior-consultant event")
    ap.add_argument("--serve", action="store_true", help="keep the built app running until Ctrl-C")
    args = ap.parse_args()

    load_env()
    registry = ModelRegistry.load(env=None if (args.allow_cloud or args.consultant) else {})  # empty env: cloud models are unavailable
    bus = EventBus()
    bus.subscribe(printer)
    started = time.time()
    orch = Orchestrator(args.goal, registry, LLMClient(registry), bus, mode=args.mode, approver=cli_approver,
                        preset=args.preset, local_only=not args.allow_cloud, consultant=args.consultant)
    res = orch.run()

    print(f"\n== {'BUILD OK' if res.ok else 'BUILD FAILED'} in {time.time() - started:.0f}s | tests: {res.test_summary}")
    for name, s in res.agent_stats.items():
        print(f"   {name:10s} {s['model']:20s} {s['iterations']:3d} iterations, {s['completion_tokens']} tokens generated")
    for p in res.problems:
        print(f"   problem: {p}")
    if res.root:
        print(f"== project: {res.root}")
    if res.app_url:
        print(f"== OPEN: {res.app_url}")
        if args.serve:
            print("   serving; press Ctrl-C to stop")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
    orch.ports and orch.ports.stop_all()
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
