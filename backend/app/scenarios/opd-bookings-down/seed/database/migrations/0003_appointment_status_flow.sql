-- 0003: an appointment is Booked, then Completed or Cancelled, and never moves again
CREATE TRIGGER appointments_status_flow BEFORE UPDATE OF status ON appointments
WHEN NEW.status != OLD.status AND NOT ((OLD.status = 'Booked' AND NEW.status IN ('Completed', 'Cancelled')) OR (OLD.status = 'Completed' AND NEW.status IN ('')) OR (OLD.status = 'Cancelled' AND NEW.status IN ('')))
BEGIN
    SELECT RAISE(ABORT, 'That status change is not allowed');
END;
