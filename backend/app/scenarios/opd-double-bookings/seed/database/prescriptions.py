"""Data access functions (stubs generated from the database schema). Fill in the bodies."""
import json

from database.connection import connect

SCHEMA = ""  # the schema is in database/migrations/ (applied by database.connection.connect)
def add_prescription(doctor_id: int, patient_name: str, medicine: str, dosage: str, days: int, instructions: str) -> dict:
    """Inserts a row with these values and returns the new row as a dict (SELECT * FROM the table WHERE id = lastrowid: always SELECT *, so created_at and the counters come back too). Counters and created_at come from their column defaults."""
    with connect(SCHEMA) as conn:
        cur = conn.execute("INSERT INTO prescriptions (doctor_id, patient_name, medicine, dosage, days, instructions) VALUES (?, ?, ?, ?, ?, ?)", (doctor_id, patient_name, medicine, dosage, days, instructions,))
        row = conn.execute("SELECT * FROM prescriptions WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)


def get_prescription(prescription_id: int) -> dict | None:
    """Returns the row as a dict (SELECT *), or None if the id does not exist."""
    with connect(SCHEMA) as conn:
        row = conn.execute("SELECT * FROM prescriptions WHERE id = ?", (prescription_id,)).fetchone()
        return dict(row) if row else None


def list_prescriptions(doctor_id: int) -> list[dict]:
    """Returns the rows whose doctor_id equals the argument (WHERE doctor_id = ?), as a list of dicts, ordered newest first (ORDER BY id DESC, never ORDER BY created_at: rows added in the same second have the same timestamp)."""
    with connect(SCHEMA) as conn:
        order = "id DESC"
        rows = conn.execute("SELECT * FROM prescriptions WHERE doctor_id = ? ORDER BY " + order, (doctor_id,)).fetchall()
        return [dict(r) for r in rows]


def update_prescription(prescription_id: int, patient_name: str, medicine: str, dosage: str, days: int, instructions: str) -> dict | None:
    """Updates the user-entered columns of the row (never counters or created_at) and returns the updated row, or None if the id does not exist."""
    with connect(SCHEMA) as conn:
        conn.execute("UPDATE prescriptions SET patient_name = ?, medicine = ?, dosage = ?, days = ?, instructions = ? WHERE id = ?", (patient_name, medicine, dosage, days, instructions, prescription_id))
        row = conn.execute("SELECT * FROM prescriptions WHERE id = ?", (prescription_id,)).fetchone()
        return dict(row) if row else None


def delete_prescription(prescription_id: int) -> bool:
    """Deletes the row. Returns True if the row existed, else False."""
    with connect(SCHEMA) as conn:
        cur = conn.execute("DELETE FROM prescriptions WHERE id = ?", (prescription_id,))
        return cur.rowcount > 0
