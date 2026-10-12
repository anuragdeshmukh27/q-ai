"""Data access functions (stubs generated from the database schema). Fill in the bodies."""
import json

from database.connection import connect

SCHEMA = ""  # the schema is in database/migrations/ (applied by database.connection.connect)
def add_doctor(name: str, department: str, phone: str, email: str, consultation_fee: float, room: str, availability: str) -> dict:
    """Inserts a row with these values and returns the new row as a dict (SELECT * FROM the table WHERE id = lastrowid: always SELECT *, so created_at and the counters come back too). Counters and created_at come from their column defaults."""
    with connect(SCHEMA) as conn:
        cur = conn.execute("INSERT INTO doctors (name, department, phone, email, consultation_fee, room, availability) VALUES (?, ?, ?, ?, ?, ?, ?)", (name, department, phone, email, consultation_fee, room, availability,))
        row = conn.execute("SELECT * FROM doctors WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)


def get_doctor(doctor_id: int) -> dict | None:
    """Returns the row as a dict (SELECT *), or None if the id does not exist."""
    with connect(SCHEMA) as conn:
        row = conn.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
        return dict(row) if row else None


def list_doctors() -> list[dict]:
    """Returns every row, as a list of dicts, ordered newest first (ORDER BY id DESC, never ORDER BY created_at: rows added in the same second have the same timestamp)."""
    with connect(SCHEMA) as conn:
        order = "id DESC"
        rows = conn.execute("SELECT * FROM doctors ORDER BY " + order, ()).fetchall()
        return [dict(r) for r in rows]


def update_doctor(doctor_id: int, name: str, department: str, phone: str, email: str, consultation_fee: float, room: str, availability: str) -> dict | None:
    """Updates the user-entered columns of the row (never counters or created_at) and returns the updated row, or None if the id does not exist."""
    with connect(SCHEMA) as conn:
        conn.execute("UPDATE doctors SET name = ?, department = ?, phone = ?, email = ?, consultation_fee = ?, room = ?, availability = ? WHERE id = ?", (name, department, phone, email, consultation_fee, room, availability, doctor_id))
        row = conn.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
        return dict(row) if row else None


def delete_doctor(doctor_id: int) -> bool:
    """First deletes every row of its children (DELETE FROM appointments WHERE doctor_id = ?, DELETE FROM prescriptions WHERE doctor_id = ?, DELETE FROM lab_tests WHERE doctor_id = ?; every module's SCHEMA creates all tables), then deletes the row. Returns True if the row existed, else False."""
    with connect(SCHEMA) as conn:
        conn.execute("DELETE FROM appointments WHERE doctor_id = ?", (doctor_id,))
        conn.execute("DELETE FROM prescriptions WHERE doctor_id = ?", (doctor_id,))
        conn.execute("DELETE FROM lab_tests WHERE doctor_id = ?", (doctor_id,))
        cur = conn.execute("DELETE FROM doctors WHERE id = ?", (doctor_id,))
        return cur.rowcount > 0
