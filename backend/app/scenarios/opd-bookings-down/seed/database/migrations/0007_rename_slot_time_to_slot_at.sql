-- 0007: naming rule for time columns is <thing>_at (created_at, slot_at).
-- Rename appointments.slot_time to appointments.slot_at. The index from 0006 follows the column.
-- Every caller of the database layer has to say slot_at from now on (the database/ functions already do).
ALTER TABLE appointments RENAME COLUMN slot_time TO slot_at;
