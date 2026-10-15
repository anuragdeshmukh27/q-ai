-- The index without cleaning up: it cannot be built over the rows that already collide, so the upgrade fails on the production data.
CREATE UNIQUE INDEX idx_one_booking ON appointments (doctor_id, date, slot_at) WHERE status = 'Booked';
