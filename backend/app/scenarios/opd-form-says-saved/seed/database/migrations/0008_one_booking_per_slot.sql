-- 0008: one Booked appointment per doctor, date and time.
-- Two patients could be booked into the same slot because nothing in the database forbade it, and it happened several times this week.
-- 1. keep the earliest booking of every double-booked slot, cancel the later ones (no row is deleted) and record why in appointments.cancel_reason;
-- 2. from now on the database refuses a second Booked row for a slot (a Cancelled or Completed row may share it, so the index is partial).
ALTER TABLE appointments ADD COLUMN cancel_reason TEXT;

UPDATE appointments
SET status = 'Cancelled',
    cancel_reason = 'Duplicate booking: appointment ' || (
        SELECT first.id FROM appointments AS first
        WHERE first.status = 'Booked' AND first.doctor_id = appointments.doctor_id AND first.date = appointments.date AND first.slot_at = appointments.slot_at
        ORDER BY first.created_at, first.id LIMIT 1) || ' booked this slot first'
WHERE status = 'Booked'
  AND id <> (
        SELECT first.id FROM appointments AS first
        WHERE first.status = 'Booked' AND first.doctor_id = appointments.doctor_id AND first.date = appointments.date AND first.slot_at = appointments.slot_at
        ORDER BY first.created_at, first.id LIMIT 1);

CREATE UNIQUE INDEX idx_appointments_one_booking_per_slot ON appointments (doctor_id, date, slot_at) WHERE status = 'Booked';
