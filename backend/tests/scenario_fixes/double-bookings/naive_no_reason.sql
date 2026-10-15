-- Cleans up and adds the partial index, but never records why a booking was cancelled: only test_a_cancelled_duplicate_records_why fails.
UPDATE appointments SET status = 'Cancelled'
WHERE status = 'Booked' AND id NOT IN (SELECT MIN(id) FROM appointments WHERE status = 'Booked' GROUP BY doctor_id, date, slot_at);
CREATE UNIQUE INDEX idx_one_booking ON appointments (doctor_id, date, slot_at) WHERE status = 'Booked';
