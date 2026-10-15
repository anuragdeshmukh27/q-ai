"""Data access functions (stubs generated from the database schema). Fill in the bodies."""
import json

from database.connection import connect

SCHEMA = ""  # the schema is in database/migrations/ (applied by database.connection.connect)


def _row(row) -> dict:
    """The row as a dict. Since migration 0007 the column is `slot_at`; the API contract still calls the field `time`, so the row carries it under that name too."""
    d = dict(row)
    d["time"] = d["slot_at"]
    return d


def booked_slots(doctor_id: int, date: str) -> list[dict]:
    """The Booked appointments of one doctor on one date, earliest first (ORDER BY slot_at), as a list of dicts (every column, `slot_at` included)."""
    with connect(SCHEMA) as conn:
        rows = conn.execute("SELECT * FROM appointments WHERE doctor_id = ? AND date = ? AND status = 'Booked' ORDER BY slot_at, id", (doctor_id, date)).fetchall()
        return [_row(r) for r in rows]


def add_appointment(doctor_id: int, patient_name: str, patient_phone: str, date: str, slot_at: str, reason: str, status: str) -> dict:
    """Inserts a row with these values and returns the new row as a dict (SELECT * FROM the table WHERE id = lastrowid: always SELECT *, so created_at and the counters come back too). Counters and created_at come from their column defaults."""
    with connect(SCHEMA) as conn:
        cur = conn.execute("INSERT INTO appointments (doctor_id, patient_name, patient_phone, date, slot_at, reason, status) VALUES (?, ?, ?, ?, ?, ?, ?)", (doctor_id, patient_name, patient_phone, date, slot_at, reason, status,))
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row(row)


def get_appointment(appointment_id: int) -> dict | None:
    """Returns the row as a dict (SELECT *), or None if the id does not exist."""
    with connect(SCHEMA) as conn:
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
        return _row(row) if row else None


def list_appointments(doctor_id: int) -> list[dict]:
    """Returns the rows whose doctor_id equals the argument (WHERE doctor_id = ?), as a list of dicts, ordered newest first (ORDER BY id DESC, never ORDER BY created_at: rows added in the same second have the same timestamp)."""
    with connect(SCHEMA) as conn:
        order = "id DESC"
        rows = conn.execute("SELECT * FROM appointments WHERE doctor_id = ? ORDER BY " + order, (doctor_id,)).fetchall()
        return [_row(r) for r in rows]


def update_appointment(appointment_id: int, patient_name: str, patient_phone: str, date: str, slot_at: str, reason: str, status: str) -> dict | None:
    """Updates the user-entered columns of the row (never counters or created_at) and returns the updated row, or None if the id does not exist."""
    with connect(SCHEMA) as conn:
        conn.execute("UPDATE appointments SET patient_name = ?, patient_phone = ?, date = ?, slot_at = ?, reason = ?, status = ? WHERE id = ?", (patient_name, patient_phone, date, slot_at, reason, status, appointment_id))
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
        return _row(row) if row else None


def delete_appointment(appointment_id: int) -> bool:
    """Deletes the row. Returns True if the row existed, else False."""
    with connect(SCHEMA) as conn:
        cur = conn.execute("DELETE FROM appointments WHERE id = ?", (appointment_id,))
        return cur.rowcount > 0


def complete_appointment(appointment_id: int) -> dict | None:
    """Runs UPDATE appointments SET status = 'Completed' WHERE id = ? and returns the updated row as a dict, or None if the id does not exist."""
    with connect(SCHEMA) as conn:
        conn.execute("UPDATE appointments SET status = ? WHERE id = ?", ('Completed', appointment_id))
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
        return _row(row) if row else None


def cancel_appointment(appointment_id: int) -> dict | None:
    """Runs UPDATE appointments SET status = 'Cancelled' WHERE id = ? and returns the updated row as a dict, or None if the id does not exist."""
    with connect(SCHEMA) as conn:
        conn.execute("UPDATE appointments SET status = ? WHERE id = ?", ('Cancelled', appointment_id))
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
        return _row(row) if row else None
