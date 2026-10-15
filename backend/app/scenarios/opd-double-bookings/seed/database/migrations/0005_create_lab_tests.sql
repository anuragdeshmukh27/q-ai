-- 0005: lab tests ordered by a doctor: Ordered, then Collected, then Reported
CREATE TABLE lab_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id INTEGER NOT NULL,
    patient_name TEXT NOT NULL,
    test_name TEXT NOT NULL,
    cost REAL NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TRIGGER lab_tests_status_flow BEFORE UPDATE OF status ON lab_tests
WHEN NEW.status != OLD.status AND NOT ((OLD.status = 'Ordered' AND NEW.status IN ('Collected')) OR (OLD.status = 'Collected' AND NEW.status IN ('Reported')) OR (OLD.status = 'Reported' AND NEW.status IN ('')))
BEGIN
    SELECT RAISE(ABORT, 'That status change is not allowed');
END;
