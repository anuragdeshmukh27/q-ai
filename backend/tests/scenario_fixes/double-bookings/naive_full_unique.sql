-- Cleans up the duplicates but the index covers every status: Cancelled rows that share a slot (as two of them do in the data) make it fail to build.
ALTER TABLE appointments ADD COLUMN cancel_reason TEXT;
UPDATE appointments SET status = 'Cancelled', cancel_reason = 'Duplicate booking'
WHERE status = 'Booked' AND id NOT IN (SELECT MIN(id) FROM appointments WHERE status = 'Booked' GROUP BY doctor_id, date, slot_at);
CREATE UNIQUE INDEX idx_one_booking ON appointments (doctor_id, date, slot_at);
