"""What a scenario's debrief measures on the merged project after the submit, besides the suite re-run (see debrief.py).

A rubric lists the measures it needs (`"measures": ["double_bookings"]`). A measure looks at the merged project and answers with named results: each has a `text`, which becomes an
entry of the log the report scores (`debrief_check`, quoted by the point that depends on it), and the facts a rule needs. A measure never raises into the debrief: when it cannot run it
returns nothing and the rules say that the result could not be measured.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Callable

PRODUCTION_HAS = "0007"  # the last migration the production database has run; the snapshot was taken from it
MIGRATION_GLOB = "[0-9][0-9][0-9][0-9]_*.sql"
SLOT = ("doctor_id", "date", "slot_at")


def _migrations(folder: Path) -> list[Path]:
    return sorted((Path(folder) / "database" / "migrations").glob(MIGRATION_GLOB))


def _rows(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute("SELECT * FROM appointments ORDER BY id")]


def _double_booked(rows: list[dict]) -> dict[tuple, list[dict]]:
    slots: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r["status"] == "Booked":
            slots[(r["doctor_id"], r["date"], r["slot_at"])].append(r)
    return {k: sorted(v, key=lambda r: (r["created_at"], r["id"])) for k, v in slots.items() if len(v) > 1}


def _why(conn: sqlite3.Connection, appointment_id: int, columns_before: set[str], tables_before: set[str]) -> str:
    """The reason recorded for an appointment: a value in a column the upgrade added to `appointments`, or a row of a table it added that names the appointment."""
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
    for column in {r["name"] for r in conn.execute("PRAGMA table_info(appointments)")} - columns_before:
        if row is not None and str(row[column] or "").strip():
            return str(row[column])
    for table in {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} - tables_before - {"sqlite_sequence"}:
        for logged in conn.execute(f'SELECT * FROM "{table}"'):
            values = list(logged)
            if str(appointment_id) in [str(v) for v in values]:
                text = [str(v) for v in values if isinstance(v, str) and len(v.strip()) > 3]
                if text:
                    return text[0]
    return ""


def _index_shape(conn: sqlite3.Connection) -> dict:
    """Is there a unique index over exactly doctor_id, date, slot_at, and is it limited to the Booked rows?"""
    conn.row_factory = sqlite3.Row
    found = {"unique": False, "partial": False, "name": ""}
    for idx in conn.execute("PRAGMA index_list(appointments)").fetchall():
        if not idx["unique"]:
            continue
        cols = [r["name"] for r in conn.execute(f'PRAGMA index_info("{idx["name"]}")')]
        if sorted(cols) == sorted(SLOT):
            sql = (conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (idx["name"],)).fetchone() or {"sql": ""})["sql"] or ""
            partial = bool(idx["partial"]) and "booked" in sql.lower()
            if not found["unique"] or partial:
                found = {"unique": True, "partial": partial, "name": idx["name"]}
    return found


def _enforcement(conn: sqlite3.Connection) -> dict:
    """Try it on a free slot, inside a transaction that is rolled back: a second Booked row must be refused, a Cancelled one allowed."""
    insert = "INSERT INTO appointments (doctor_id, patient_name, patient_phone, date, slot_at, reason, status) VALUES (1, 'P', '9876500000', '2031-01-04', '07:07', 'r', ?)"
    out = {"refuses_second_booked": False, "allows_cancelled": False}
    conn.execute("SAVEPOINT probe")
    try:
        conn.execute(insert, ("Booked",))
        try:
            conn.execute(insert, ("Booked",))
        except sqlite3.IntegrityError:
            out["refuses_second_booked"] = True
        try:
            conn.execute(insert, ("Cancelled",))
            out["allows_cancelled"] = True
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.execute("ROLLBACK TO probe")
        conn.execute("RELEASE probe")
    return out


def double_bookings(root: Path, seed_dir: Path, params: dict) -> dict[str, dict]:
    """Run the learner's migrations (every migration after 0007 of the merged project) on the production snapshot, built from the seed's own 0001 to 0007 and snapshot so that
    nothing the learner can edit changes the data, and report: was any row lost, were the double-booked slots resolved the way the incident asks, and does the unique index exist and work."""
    seed = Path(seed_dir)
    with tempfile.TemporaryDirectory(prefix="q-double-") as tmp:
        conn = sqlite3.connect(Path(tmp) / "prod.db", isolation_level=None)
        try:
            for sql in _migrations(seed):
                if sql.name.split("_", 1)[0] <= PRODUCTION_HAS:
                    conn.executescript(sql.read_text(encoding="utf-8"))
            conn.executescript((seed / "fixtures" / "prod_snapshot.sql").read_text(encoding="utf-8"))
            before = _rows(conn)
            conn.row_factory = sqlite3.Row
            columns_before = {r["name"] for r in conn.execute("PRAGMA table_info(appointments)")}
            tables_before = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            groups = _double_booked(before)
            error = ""
            try:
                for sql in _migrations(Path(root)):
                    if sql.name.split("_", 1)[0] > PRODUCTION_HAS:
                        conn.executescript(sql.read_text(encoding="utf-8"))
            except sqlite3.Error as e:
                error = f"{type(e).__name__}: {e}"
            after = {r["id"]: r for r in _rows(conn)}
            lost = sorted({r["id"] for r in before} - set(after))
            earliest_kept = all(after.get(rows[0]["id"], {}).get("status") == "Booked" for rows in groups.values())
            later = [r for rows in groups.values() for r in rows[1:]]
            cancelled = [r for r in later if after.get(r["id"], {}).get("status") == "Cancelled"]
            reasons = [r for r in cancelled if _why(conn, r["id"], columns_before, tables_before)]
            others_kept = all(after.get(r["id"], {}).get("status") == r["status"] for r in before if r["id"] not in {x["id"] for x in later})
            still_double = bool(_double_booked(list(after.values())))
            resolved = not error and earliest_kept and len(cancelled) == len(later) and len(reasons) == len(later) and others_kept and not still_double
            shape = _index_shape(conn) if not error else {"unique": False, "partial": False, "name": ""}
            tried = _enforcement(conn) if not error else {"refuses_second_booked": False, "allows_cancelled": False}
        finally:
            conn.close()
    n = len(before)
    if error:
        rows_text = f"Debrief upgrade of the production snapshot: your migration failed ({error[:120]})"
        dup_text = f"Debrief check of the {len(groups)} double-booked slots: not resolved, the migration failed"
        idx_text = "Debrief check of the index: not created, the migration failed"
    else:
        rows_text = f"Debrief upgrade of the production snapshot: {len(after)} of {n} appointments are still there" + (f" (deleted: {', '.join(map(str, lost))})" if lost else "")
        dup_text = (f"Debrief check of the {len(groups)} double-booked slots: {sum(1 for rows in groups.values() if after.get(rows[0]['id'], {}).get('status') == 'Booked')} keep their earliest booking, "
                    f"{len(cancelled)} of {len(later)} later bookings are cancelled, {len(reasons)} of {len(later)} say why" + ("" if not still_double else "; a slot still holds two Booked appointments"))
        if not shape["unique"]:
            idx_text = "Debrief check of the index: there is no unique index over doctor_id, date and slot_at"
        elif not shape["partial"]:
            idx_text = "Debrief check of the index: the unique index over doctor_id, date and slot_at covers every status, not only Booked"
        elif not tried["refuses_second_booked"]:
            idx_text = "Debrief check of the index: it exists but a second Booked row for a slot was accepted"
        elif not tried["allows_cancelled"]:
            idx_text = "Debrief check of the index: a Cancelled row at a Booked slot was refused"
        else:
            idx_text = "Debrief check of the index: unique over doctor_id, date and slot_at for Booked rows only; a second Booked row is refused, a Cancelled one is allowed"
    return {
        "rows_kept": {"text": rows_text, "ok": not error and not lost, "error": error, "lost": lost},
        "duplicates": {"text": dup_text, "ok": resolved, "error": error, "slots": len(groups), "cancelled": len(cancelled), "later": len(later), "reasons": len(reasons),
                       "earliest_kept": earliest_kept, "still_double": still_double},
        "unique_index": {"text": idx_text, "ok": not error and shape["unique"] and shape["partial"] and tried["refuses_second_booked"] and tried["allows_cancelled"], "error": error, **shape, **tried},
    }


# the ways a page sends a write request, with the real answer of the API for each refusal (the seed's tests/ui/answers.json) and where a person sees the outcome
REFUSALS = (("create_taken", "a taken slot in the booking form", "form"), ("create_bad_phone", "a bad phone in the booking form", "form"), ("edit_taken", "an edit onto a taken slot", "form"),
            ("action_refused", "a refused Complete or Cancel", "toast"), ("delete_missing", "a refused delete", "toast"), ("board_refused", "a refused board move", "toast"),
            ("create_doctor_email_taken", "a taken email in the doctor form", "form"), ("create_prescription_bad_days", "a bad number of days in the prescription form", "form"))


def refusals(root: Path, seed: Path, params: dict) -> dict[str, dict]:
    """Runs the pages of the merged project (its static/) in Node against the seed's own probe and the real answers of the API: does every way of sending a request show a refusal
    as an error, with the server's own words? The probe, the fake browser and the answers are the seed's, so nothing you can edit changes them."""
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is not installed")
    answers = json.loads((Path(seed) / "tests" / "ui" / "answers.json").read_text(encoding="utf-8"))
    shown: list[str] = []
    said: list[str] = []
    error = ""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        shutil.copytree(Path(root) / "static", work / "static", ignore=shutil.ignore_patterns("fonts"))
        (work / "tests" / "ui").mkdir(parents=True)
        for name in ("fakedom.mjs", "refusals.mjs"):
            shutil.copy(Path(seed) / "tests" / "ui" / name, work / "tests" / "ui" / name)
        for name, label, where in REFUSALS:
            case = answers[name]
            detail = case["body"]["detail"]
            r = subprocess.run([node, str(work / "tests" / "ui" / "refusals.mjs"), json.dumps(case)], cwd=work, capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                error = (r.stderr or r.stdout).strip().splitlines()[-1][:160] if (r.stderr or r.stdout).strip() else "the page did not run"
                break
            out = json.loads(r.stdout.strip().splitlines()[-1])
            success = [t["text"] for t in out["toasts"] if t["kind"] == "success"]
            errors = [t["text"] for t in out["toasts"] if t["kind"] == "error"]
            refused = not success and (out["formOpen"] if where == "form" else bool(errors))
            if refused:
                shown.append(label)
            if refused and (out["formError"] == detail if where == "form" else any(detail in t for t in errors)):
                said.append(label)
    labels = [label for _, label, _ in REFUSALS]
    if error:
        text = f"Debrief check of the pages: they could not be run on your change ({error})"
        return {"refusal_paths": {"text": text, "ok": False, "error": error, "passed": 0, "of": len(labels), "failed": labels},
                "refusal_message": {"text": "Debrief check of the messages: the pages could not be run on your change", "ok": False, "error": error, "passed": 0, "of": len(labels), "failed": labels}}
    bad = [x for x in labels if x not in shown]
    unsaid = [x for x in labels if x not in said]
    return {
        "refusal_paths": {"text": ("Debrief check of the pages: all {} refused requests (the booking form, an edit, Complete or Cancel, a delete, a board move, and the doctor and prescription forms) show an error and none says it saved".format(len(labels)) if not bad
                                   else f"Debrief check of the pages: {len(shown)} of {len(labels)} refused requests show an error; still reported as saved: {', '.join(bad)}"),
                          "ok": not bad, "passed": len(shown), "of": len(labels), "failed": bad},
        "refusal_message": {"text": (f"Debrief check of the messages: in all {len(labels)} cases the server's own message is what the person reads" if not unsaid
                                     else f"Debrief check of the messages: the server's own message reaches the person in {len(said)} of {len(labels)} cases; missing for {', '.join(unsaid)}"),
                            "ok": not unsaid, "passed": len(said), "of": len(labels), "failed": unsaid},
    }


MEASURES: dict[str, Callable[[Path, Path, dict], dict[str, dict]]] = {"double_bookings": double_bookings, "refusals": refusals}
