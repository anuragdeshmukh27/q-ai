-- 0006: the front desk looks up a doctor's day by date and time
CREATE INDEX idx_appointments_doctor_day ON appointments (doctor_id, date, slot_time);
