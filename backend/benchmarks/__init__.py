"""Benchmark suite: small tasks per role with an automatic pass/fail, run per model; results feed the leaderboard and the router.

    backend\.venv\Scripts\python.exe scripts\benchmark.py [--models qwen25-coder-7b,qwen3-4b] [--roles backend,qa] [--export]

Roles are employee ids: architect, planner, backend, frontend, database, reviewer, qa. See `tasks.py` for what each task checks.
"""
