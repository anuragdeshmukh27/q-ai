-- The first idea: delete the later duplicates, then add the index. No row may be deleted, so test_duplicate_bookings_are_cancelled_not_deleted fails.
DELETE FROM appointments WHERE status = 'Booked' AND id NOT IN (SELECT MIN(id) FROM appointments WHERE status = 'Booked' GROUP BY doctor_id, date, slot_at);
CREATE UNIQUE INDEX idx_one_booking ON appointments (doctor_id, date, slot_at) WHERE status = 'Booked';
