"""Data access functions (stubs generated from the database schema). Fill in the bodies."""
import json

from database.connection import connect

SCHEMA = ""  # the schema is in database/migrations/ (applied by database.connection.connect)
def add_lab_test(doctor_id: int, patient_name: str, test_name: str, cost: float, status: str) -> dict:
    """Inserts a row with these values and returns the new row as a dict (SELECT * FROM the table WHERE id = lastrowid: always SELECT *, so created_at and the counters come back too). Counters and created_at come from their column defaults."""
    with connect(SCHEMA) as conn:
        cur = conn.execute("INSERT INTO lab_tests (doctor_id, patient_name, test_name, cost, status) VALUES (?, ?, ?, ?, ?)", (doctor_id, patient_name, test_name, cost, status,))
        row = conn.execute("SELECT * FROM lab_tests WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)


def get_lab_test(lab_test_id: int) -> dict | None:
    """Returns the row as a dict (SELECT *), or None if the id does not exist."""
    with connect(SCHEMA) as conn:
        row = conn.execute("SELECT * FROM lab_tests WHERE id = ?", (lab_test_id,)).fetchone()
        return dict(row) if row else None


def list_lab_tests(doctor_id: int) -> list[dict]:
    """Returns the rows whose doctor_id equals the argument (WHERE doctor_id = ?), as a list of dicts, ordered newest first (ORDER BY id DESC, never ORDER BY created_at: rows added in the same second have the same timestamp)."""
    with connect(SCHEMA) as conn:
        order = "id DESC"
        rows = conn.execute("SELECT * FROM lab_tests WHERE doctor_id = ? ORDER BY " + order, (doctor_id,)).fetchall()
        return [dict(r) for r in rows]


def update_lab_test(lab_test_id: int, patient_name: str, test_name: str, cost: float, status: str) -> dict | None:
    """Updates the user-entered columns of the row (never counters or created_at) and returns the updated row, or None if the id does not exist."""
    with connect(SCHEMA) as conn:
        conn.execute("UPDATE lab_tests SET patient_name = ?, test_name = ?, cost = ?, status = ? WHERE id = ?", (patient_name, test_name, cost, status, lab_test_id))
        row = conn.execute("SELECT * FROM lab_tests WHERE id = ?", (lab_test_id,)).fetchone()
        return dict(row) if row else None


def delete_lab_test(lab_test_id: int) -> bool:
    """Deletes the row. Returns True if the row existed, else False."""
    with connect(SCHEMA) as conn:
        cur = conn.execute("DELETE FROM lab_tests WHERE id = ?", (lab_test_id,))
        return cur.rowcount > 0


def collect_lab_test(lab_test_id: int) -> dict | None:
    """Runs UPDATE lab_tests SET status = 'Collected' WHERE id = ? and returns the updated row as a dict, or None if the id does not exist."""
    with connect(SCHEMA) as conn:
        conn.execute("UPDATE lab_tests SET status = ? WHERE id = ?", ('Collected', lab_test_id))
        row = conn.execute("SELECT * FROM lab_tests WHERE id = ?", (lab_test_id,)).fetchone()
        return dict(row) if row else None


def report_lab_test(lab_test_id: int) -> dict | None:
    """Runs UPDATE lab_tests SET status = 'Reported' WHERE id = ? and returns the updated row as a dict, or None if the id does not exist."""
    with connect(SCHEMA) as conn:
        conn.execute("UPDATE lab_tests SET status = ? WHERE id = ?", ('Reported', lab_test_id))
        row = conn.execute("SELECT * FROM lab_tests WHERE id = ?", (lab_test_id,)).fetchone()
        return dict(row) if row else None
