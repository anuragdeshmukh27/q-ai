-- Cleans up the data and records why, but nothing stops it from happening again: the index tests and the 409 tests fail.
ALTER TABLE appointments ADD COLUMN cancel_reason TEXT;
UPDATE appointments SET status = 'Cancelled', cancel_reason = 'Duplicate booking'
WHERE status = 'Booked' AND id NOT IN (SELECT MIN(id) FROM appointments WHERE status = 'Booked' GROUP BY doctor_id, date, slot_at);
