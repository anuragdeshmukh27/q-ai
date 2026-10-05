# MORNING SUMMARY (written 2026-10-06 about 03:20 IST, the work was finished long before the 07:00 stop)

main was never edited, committed to, merged into or run. The only things done from `q` are `git worktree add ..\q-demo -b demo-v2 main`, **one mistake I made and repaired (read "What went wrong" first)**, and temporary detached worktrees of main (667c8d9) that I created and deleted to replay the recordings with main's code.
Branches pushed: `demo-v2` (this one) and `task-c`. Nothing merged into main.

## Ready and verified with main's code (three recordings)

| name | where it is now | verified |
|---|---|---|
| `hackathon-platform` | `C:\CODING\Hackathon\q-demo\recordings\hackathon-platform` (branch demo-v2) | yes |
| `hospital-opd` | `C:\CODING\Hackathon\q-demo\recordings\hospital-opd` (branch demo-v2) | yes |
| `mixed-model-team` | `C:\CODING\Hackathon\q-c\recordings\mixed-model-team` (branch task-c only) | yes |

"Verified" means (`scripts\verify_on_main.py`, a temporary detached worktree of main 667c8d9, a random port, network and Ollama blocked at socket level): main's own API lists the recording, the replay runs to `project_done` ok with every event matching the recording type for type, the restored app answers `/health` and `/`, and the restored project's own tests pass (94, 97 and 54 passed). I also opened main's real React UI (the main code, Vite on port 5373, backend on 8200, both stopped afterwards), saw the three new cards with their numbers, and replayed `mixed-model-team` at 4x to "Complete 100 %" with the Open app button; `hackathon-platform` and `hospital-opd` were replayed in the UI the same way; those two screenshots were taken at 90 % of the replay (40 s in), and their full replays to `project_done` were checked by the API-level verification above. Screenshots are in `q-demo\workspace\_shots\ui-*.png` (not committed).

## Copy them into main (Windows, PowerShell)

```powershell
$dst = "C:\CODING\Hackathon\q\recordings"
Copy-Item -Recurse -Force "C:\CODING\Hackathon\q-demo\recordings\hackathon-platform" $dst
Copy-Item -Recurse -Force "C:\CODING\Hackathon\q-demo\recordings\hospital-opd"      $dst
Copy-Item -Recurse -Force "C:\CODING\Hackathon\q-c\recordings\mixed-model-team"      $dst
Get-ChildItem $dst\hackathon-platform, $dst\hospital-opd, $dst\mixed-model-team | Select-Object Directory, Name, Length
```
Each folder must show `events.jsonl`, `llm.jsonl`, `meta.json` and `snapshot.bundle`. Copy only these three: the rest of the two branches changes the engine, and main should stay as it is.
(`git status` in `q` will then show three untracked folders; commit them on main yourself if you want them tracked.)

Check that each one appears and replays, with Wi-Fi off:
1. Run `start.bat` (a restart is not needed if it is already running, just reload the page). Turn Wi-Fi off. Ollama can stay off.
2. Demo mode switch ON. In "Choose a recorded build" there are three new cards: **Hackathon management platform: 4 modules** (2 min 41 s), **Hospital OPD manager: 4 modules** (2 min 46 s), **Q&A forum, a mixed team** (3 min 23 s). The older recordings are still there.
3. Pick a card, choose 4x, press **Play demo**. It takes about 40 to 50 seconds, ends with the bar at 100 % and "Done in ...", the employees celebrate, and **Open app** opens the real generated app (it needs ports 9100-9199 free). On the mixed-model card the top bar shows the loaded model changing between qwen2.5-coder:14b, qwen3:4b and qwen2.5-coder:7b.
4. Optional automatic check of every recording in `q\recordings` (the offline replay test, a few minutes in total): `cd C:\CODING\Hackathon\q ; backend\.venv\Scripts\python.exe -m pytest backend\tests\test_replay_offline.py -q`

## Table 1: the 7b flagships against the college fest (all `qwen2.5-coder:7b`, same machine)

| | College tech fest (main) | Hackathon platform | Hospital OPD |
|---|---|---|---|
| time of the recorded build | 269 s | 161 s | 166 s |
| tests passed | 96 | 94 | 97 |
| endpoints / tables / pages | 19 / 4 / 10 | 20 / 4 / 10 | 20 / 4 / 10 |
| functions in the app | 42 | 44 | 44 |
| written by the agents | 16 (38 %) | 44 (100 %) | 44 (100 %) |
| written by contract repair | 26 | 0 | 0 |
| escalations / error events in the recording | 5 / 11 | 0 / 0 | 0 / 0 |
| dashboard, theme | purple "campus" | amber "transit", 5 KPIs, 4 charts | teal "clinic", 5 KPIs, 4 charts |

How repeatable is it? 16 more unrecorded builds of the two goals (4 + 4 before the last reviewer filter, 4 + 4 after): **all 16 passed every test**, 11 of 16 with every function written by the agents, the other five with 84 to 89 % (5 to 7 functions of one router or data module finished by contract repair), 151 to 211 s. The recordings are the clean ones: `record_demos.py` keeps a recording only if no one had to step in. The real build is about 3 minutes, so a 4x replay is about 45 seconds.
Before the fixes the same goal took 661 s with 16 % of the functions written by the agents (see "What was wrong" below), so the improvement is from the engine, not from picking an easy goal.

## Table 2: bigger models (qwen2.5-coder 7b, 14b, 32b)

Backend benchmark only, 2 runs per task, 2 tasks, same code (demo-v2 merged):

| model | pass rate | seconds per run | note |
|---|---|---|---|
| 7b | 2 of 4 (5 of 11 over every run) | 39 | api-todo 0 of 2 in this protocol (404 for an unknown id), calculator 2 of 2 |
| 14b | 4 of 4 | 54 | |
| 32b | 4 of 4 | 277 | 5 times the 14b for the same score |

The router (margin 0.1) now sends **backend to the 14b** ("100 % (4/4) vs 7b 46 % (5/11)"), everything else stays on the 7b, and the Task C `finish` role is pinned back to the 7b. Two runs per task is thin; one 14b failure would have moved it 25 points.

One live build, the hackathon goal, every employee on the 14b, against the 7b recording:

| | 7b (hackathon-platform) | 14b, all roles |
|---|---|---|
| time | 161 s | 799 s |
| tests passed | 94 | 94 |
| functions by agents / contract repair | 44 / 0 | 38 / 6 |
| escalations | 0 | 1 (the teams router: the same syntax error 8 times) |

On this engine a bigger model is slower and not better for a whole build; the 14b earns its place on single roles (backend). The 32b was not run live, as agreed.

Mixed-model team (`mixed-model-team`, Q&A forum with upvotes, task-c branch): 203 s, 54 tests, 2 modules, 10 endpoints, 22 of 22 functions by the agents, 9 model loads between the 14b (Aarav's spec, Vikram's 4 reviews), the 4b (Karan, 22 calls) and the 7b (Rohan, 14 calls). Priya and Meera do no model work on a goal like this (rules), so no model is shown for them.

## What went wrong, what failed or was skipped (honestly)

- **My mistake, repaired: I emptied `q\frontend\node_modules`.** `q-c\frontend\node_modules` is a junction to `q`'s. I made a temporary worktree of main for the UI check, put a junction to q-c's `node_modules` inside it, and `git worktree remove --force` followed the links and deleted the contents of q's `node_modules` (03:04 IST). It is untracked and was rebuilt at once: `npm ci` in `q-demo\frontend` (its `package-lock.json` has the same content as q's), checked with `vite --version`, then copied into `q\frontend\node_modules` with robocopy (63 entries, same as the fresh install; `git status` in `q` is clean; `dist` and every tracked file were not touched). If `start.bat` complains about the frontend in the morning, run `npm ci` in `q\frontend`. I did not touch anything else in `q`. Saved as a note so it does not happen again.
- `PROGRESS.md` did not exist on main, and the repository's shared `.git/info/exclude` hides that name, so the first commits on demo-v2 did not contain it; I force-added it.
- Part 1, one test build (run 2) failed: I edited engine files while it ran, it hit the oversize prompt (below) and one router failed even after contract repair. It is not counted in the table.
- The 7b is not perfect: 5 of 16 repeat builds needed contract repair for one router or data module, and the 7b backend benchmark on `api-todo` is a coin toss (3 of 9).
- The first launch of the 14b backend benchmark exited after 11 s without output (cause not found); the identical rerun worked and the 14b and 32b numbers come from that rerun.
- Part 5: for a goal that lists its things and fields (the restaurant manager I tried first) the Architect's work is done by rules, so Aarav's 14b would never be used; I switched to the Q&A forum, where the spec step is a model call. Meera (frontend) and Priya (planner) still make no model call on any goal where the page and the plan are generated by rules, so the 4b is used by Karan only.
- "Wi-Fi off" was tested as blocked sockets (everything except loopback, and the Ollama port), not by switching the adapter off.
- The college fest recording in main (`flagship`) was not re-recorded; its numbers are from the old engine.
- Not done: nothing in the brief was skipped. The 32b live build was excluded by the brief.
- Full backend suite on demo-v2 at the end (after every change, 03:15 IST): **805 passed**, 1 warning.

## What was wrong with the engine (the reason the new demos are so much cleaner; details further down)
The router tasks of a four-module app were 32 000 characters, more than the 8192-token window, so Ollama dropped the START of the prompt (the system prompt and the task) and the 7b answered about another module. Windows pytest output has CR LF endings, which silently broke the failure digest the engineers are told to read first. A retry at the same temperature repeated the same invalid reply. The 7b reviewer's invented defects (a syntax error in a file that compiles, a "65-line file over the limit") sent engineers on chases; they are now checked against the file and dropped when false. All of this is in `backend/app` with tests in `backend/tests/test_overnight.py`; no event type and no frontend file changed.

## Pitches

**Hackathon management platform** (4 lines)
1. One paragraph in, a working hackathon platform out: teams, members, mentor sessions and judge scores, built by eight AI employees on a laptop GPU in under three minutes.
2. Four linked modules, 20 endpoints, 94 passing tests and a dashboard with the amber "terminal" look.
3. Shortlist or eliminate a team, complete or cancel a mentor session, score a demo from 1 to 10; the app itself refuses an 11 and an illegal status change.
4. All 44 functions were written by the agents, with no template filling them in, and the whole build replays offline.

**Hospital OPD manager** (4 lines)
1. Doctors, appointments, prescriptions and lab tests in one OPD manager, built from a single paragraph in under three minutes.
2. An appointment goes Booked, then Completed or Cancelled; a lab test goes Ordered, Collected, Reported and cannot skip a step.
3. Teal clinic theme, a dashboard with lab revenue and the average consultation fee, 20 endpoints, 97 passing tests.
4. 44 of 44 functions written by the agents; the recording replays offline and "Open app" starts the real app.

**Mixed-model team** (3 lines)
1. One build, three models: Aarav and Vikram on a 14B, Karan on a 4B, Rohan on the 7B, moved on and off one 8 GB GPU by the scheduler (nine model loads, watch the coffee breaks).
2. The app is a Q&A forum with answers and upvotes: 54 passing tests, 22 of 22 functions written by the agents.
3. It is not faster, which is the honest point: Q assigns roles to models, and one weak model does not have to do everything.

---

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

## Reliability of the two demos, and two last fixes (02:08 to 02:55 IST)

Eight unrecorded builds (4 hackathon, 4 hospital), full review mode, same code as the recordings: **8 of 8 passed all tests**, 5 of 8 with every function written by the agents; the other three had 84 to 89 % (one router or one data module finished by contract repair, 5 to 7 functions), 151 to 211 s.
Both repaired cases were the 7b reviewer's opinions sending a database engineer after problems that were not there ("a large number of lines and a single function doing several jobs", "lacks tests for X" while the generated tests exist), and a loop where an engineer re-sent an unchanged function three times after it had already fixed the others.
Fixes: `drop_unfounded` also drops size opinions and "lacks tests" claims when a test file for the module exists (a branch with no tests at all is still a static finding), and the "no change" message tells the engineer to call run_tests when everything the failure points to is already changed (`tools.py`). Eight more builds with these fixes: **8 of 8 passed all tests, 6 of 8 with every function written by the agents** (the two others 84 % and 86 %), 152 to 174 s.
So the hackathon and hospital goals pass their tests on every run so far (16 of 16) and need contract repair in about one run in three; the recorded runs are the clean ones.
Raw logs of every test build are in `workspace/_logs/` (not committed).
