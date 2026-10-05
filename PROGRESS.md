# Overnight progress (branch demo-v2)

main is the frozen presentation build; nothing here is merged into it. All work for Parts 1-2 is in `q-demo` (branch `demo-v2`).
Started 2026-10-05 23:30 IST, hard stop 07:00 IST.

## Part 1: flagship demo #2

### Choice (23:35)

**Hackathon management platform**: teams (parent) with members, mentor sessions and judge scores.
Why this one and not the hospital OPD or the placement cell:
- it uses all four module slots the engine allows (one parent, three children) and has the most distinct field types: labelled categories (track, stage, role), 1-10 integer scores with bounds rules, dates and times, e-mail and phone rules;
- two status actions on two different resources (shortlist / eliminate a team, complete / cancel a mentor session) and a status flow rule on both;
- a dashboard that means something (teams by track and stage, members per team, mentor sessions done, average innovation score);
- no skill pack covered it, so it gets a new one (`config/skills/hackathon.yaml`, amber "transit" skin: sharp corners, terminal feel, clearly different from the purple tech fest);
- a judge audience knows what a hackathon needs, so the story explains itself.
The hospital OPD (existing `clinic` pack, teal skin) is used for demo #3.

### Engine fixes found while preparing (no event schema, no frontend change)
- `goal_actions` (backend/app/schemas.py) matched a resource name written with an underscore (`mentor_sessions`) against goal text that says `mentor sessions`, so "actions: complete and cancel" of a child with a two-word name were attached to the parent. Now matched loosely and the nearest mentioned resource wins.

### What was wrong (read from the actual prompts, `Q_DUMP_PROMPTS` writes every model call to a folder)

The first test build (try 1, 661 s) passed 94 tests but contract repair wrote 37 of 44 functions (agents 16 %), worse than the college fest (26 of 42). Reading the prompts the model really received showed why:

1. **The router tasks were 32 000 characters long** (system prompt 7 000 + task and stub 7 400 + the whole 20-endpoint contract 17 000), more than `num_ctx` 8192 tokens. Ollama silently drops the START of a prompt that does not fit, so the backend engineer never saw its system prompt or its task. It answered about another module ("the judge_scores data access functions..."), asked for files that were not there and ended in contract repair. Fix: a router task gets only its own router's endpoints in the contract section (`memory.contract_brief(only_paths)`, `Orchestrator._context(owner, task)`), and `run_agent` shortens the project context, never the task, when the prompt would not fit.
2. **Pytest output on Windows ends its lines with CR LF**, so every `$` regex in `tools.py` failed: the "What failed (read this first)" digest has never appeared on this machine. A request that fails inside the app also puts 25 FastAPI / Starlette / anyio frames between the engineer's line and the error. New `compact_pytest_output`: normalises line endings and drops library frames, so the digest and the real `E ...` line are visible.
3. **A retry at the same temperature repeats itself**: a 7B sent the same invalid reply (`implement` with `pattern` and `to: frontend`) 6 times in a row. The in-call retry is now 0.4 warmer, and an invalid reply raises the temperature of the next loop iteration.
4. **The task text said "replacing its `raise NotImplementedError`"**, and the model answered with `implement` plus `pattern`. The task now shows the exact first reply for this file and its first function, with the code in `content`.
5. **The reviewer (7B, full review mode = up to 3 rounds)** asked for changes that the file disproves ("syntax error" in a file that compiles, "65 lines, over the 150-line limit", "SCHEMA not used" while every function opens `connect(SCHEMA)`, style opinions). The engineer then spent its iterations chasing them. `drop_unfounded` checks those claims against the file and drops the ones that do not hold; every other item stays, and static findings are never touched.
6. **The 409 comment in the route stub** ("Answers 409 when: Email already exists") made the engineers write duplicate checks and call `db.get_member_by_email`, which does not exist (the app turns the database's refusal into the 409 by itself). The comment and `backend.md` now say so, and `backend.md` tells the engineer to copy the stub's `# body:` lines.
7. After the tests passed, a harmless pytest warning made one engineer call `ask_human`. The "all tests passed" observation now says to call finish.

Review mode is full (`Q_FAST_LIVE=0`: up to 3 review rounds per task), agent iterations stay at 8 (the loop counts review revisions separately; they were not the limit).

### Test builds on qwen2.5-coder:7b (the hackathon goal, not recorded), full review mode

| run | what changed | seconds | tests | endpoints | tables | pages | functions by agents / contract repair |
|---|---|---|---|---|---|---|---|
| 1 | nothing (baseline) | 661 | 94 passed | 20 | 4 | 10 | 7 / 37 (16 %) |
| 3 | temperature, task shape, router context, reviewer claims | 335 | 94 passed | 20 | 4 | 10 | 27 / 17 (61 %) |
| 4 | same | 246 | 94 passed | 20 | 4 | 10 | 27 / 17 (61 %) |
| 5 | + short test output | 372 | 94 passed | 20 | 4 | 10 | 27 / 17 (61 %) |
| 6 | + CR LF digest, 409 comment, backend rules | 156 | 94 passed | 20 | 4 | 10 | 44 / 0 (100 %) |
| 7 | same code, repeat | 159 | 94 passed | 20 | 4 | 10 | 44 / 0 (100 %) |

(Run 2 failed: it ran while the code was being edited and hit the oversize prompt: task t7 failed after contract repair. It is not counted.)

### Result: `hackathon-platform` recorded (00:32 IST), verified with main's code

`recordings/hackathon-platform`: 161 s, 72 model calls, 672 events, 4 modules, 4 tables, 20 endpoints, 10 pages, 595 lines, **94 tests passed, 44 of 44 functions written by agents, 0 contract repairs, 0 escalations, 0 errors**. Skill pack `hackathon`, amber `transit` skin.
Checked with `scripts/verify_on_main.py` against a temporary detached worktree of main (667c8d9; deleted afterwards): the recording is listed by main's API, replays headless and offline (network and Ollama blocked, random port) to `project_done` ok with all 672 events matching type for type, the restored app answers `/health` and `/`, and the restored project's own tests pass (94 passed).

## Part 2: flagship demo #3

### Choice (00:36)

**Hospital OPD manager**: doctors (parent) with appointments, prescriptions and lab tests. A different domain from the hackathon (healthcare, rupees, a lab workflow), teal `clinic` skin, new pack `hospital` (department / test / status labels, 1-90 day bound, appointment flow Booked to Completed or Cancelled, lab flow Ordered to Collected to Reported, lab revenue and average fee on the dashboard).
Actions: complete / cancel an appointment, collect / report a lab test. The placement cell was not picked because it needs the same four-module shape with less vocabulary the 7B can reuse; the hospital is the one every judge understands.

| run | seconds | tests | endpoints | tables | pages | functions by agents / contract repair |
|---|---|---|---|---|---|---|
| test 1 | 161 | 97 passed | 20 | 4 | 10 | 38 / 6 (86 %): an engineer called `ask_human` about a harmless warning, contract repair finished that router |
| (fix) | the "all tests passed" observation says to call finish | | | | | |
| test 2 | 159 | 97 passed | 20 | 4 | 10 | 44 / 0 (100 %) |
| **recorded `hospital-opd`** | 166 | 97 passed | 20 | 4 | 10 | 44 / 0 (100 %), 0 escalations, 0 errors |

`recordings/hospital-opd` was verified with main's code in the same way (97 passed in the restored app, 652 of 652 events).

### Engine and test changes in demo-v2 (for the record)
- `backend/app/schemas.py`: `goal_actions` loose match of two-word resource names.
- `backend/app/agent/loop.py`, `llm.py`, `tools.py`, `memory.py`, `orchestrator.py`, `relations.py`, `agent/review.py`, `prompts/backend.md`: the fixes above. No event type, no event field and nothing in `frontend/` changed, so every recording replays in main's code.
- `config/skills/hackathon.*`, `config/skills/hospital.*`; `scripts/goals.py`, `scripts/record_demos.py` (the two demos, with a stricter keep rule), `scripts/rec_report.py`, `scripts/verify_on_main.py`, `scripts/overnight_try.sh`.
- `backend/tests/test_overnight.py` (7 new tests), `test_p10.py` (12 packs, two new match checks). Full backend suite after the last edit: 804 passed (includes the offline replay of every shipped recording, both new ones too).
