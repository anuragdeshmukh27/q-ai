"""Route stubs generated from the API contract. Fill in the bodies; keep paths, models and status codes."""
import json
import operator
import re
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.validation import Email, Phone, Positive, PositiveInt, Required, between
from database import appointments as db
from database import doctors as doctors_db

router = APIRouter()

class GetDoctorsAppointmentsByDoctor_idResponse(BaseModel):
    items: list

@router.get("/api/doctors/{doctor_id}/appointments", response_model=GetDoctorsAppointmentsByDoctor_idResponse)
def handle_get_doctors_appointments_by_doctor_id(doctor_id: int):
    # List the appointments of one doctor
    # error: raise HTTPException(status_code=404, detail="Doctor not found")
    # body: if doctors_db.get_doctor(doctor_id) is None: raise HTTPException(status_code=404, detail="Doctor not found")
    # body: return {"items": db.list_appointments(doctor_id=doctor_id)}
    if doctors_db.get_doctor(doctor_id) is None: raise HTTPException(status_code=404, detail="Doctor not found")
    return {"items": db.list_appointments(doctor_id=doctor_id)}

class PostDoctorsAppointmentsByDoctor_idRequest(BaseModel):
    patient_name: Required
    patient_phone: Phone
    date: str
    time: Required
    reason: str
    status: Literal['Booked', 'Completed', 'Cancelled']

class PostDoctorsAppointmentsByDoctor_idResponse(BaseModel):
    id: int
    doctor_id: int
    patient_name: str
    patient_phone: str
    date: str
    time: str
    reason: str
    status: Literal['Booked', 'Completed', 'Cancelled']
    created_at: str

@router.post("/api/doctors/{doctor_id}/appointments", status_code=201, response_model=PostDoctorsAppointmentsByDoctor_idResponse)
def handle_post_doctors_appointments_by_doctor_id(doctor_id: int, req: PostDoctorsAppointmentsByDoctor_idRequest):
    # Add a appointment to a doctor
    # error: raise HTTPException(status_code=404, detail="Doctor not found")
    # body: if doctors_db.get_doctor(doctor_id) is None: raise HTTPException(status_code=404, detail="Doctor not found")
    # body: return db.add_appointment(doctor_id=doctor_id, patient_name=req.patient_name, patient_phone=req.patient_phone, date=req.date, slot_time=req.time, reason=req.reason, status=req.status)
    if doctors_db.get_doctor(doctor_id) is None: raise HTTPException(status_code=404, detail="Doctor not found")
    return db.add_appointment(doctor_id=doctor_id, patient_name=req.patient_name, patient_phone=req.patient_phone, date=req.date, slot_time=req.time, reason=req.reason, status=req.status)

class PutAppointmentsByIdRequest(BaseModel):
    patient_name: Required
    patient_phone: Phone
    date: str
    time: Required
    reason: str
    status: Literal['Booked', 'Completed', 'Cancelled']

class PutAppointmentsByIdResponse(BaseModel):
    id: int
    doctor_id: int
    patient_name: str
    patient_phone: str
    date: str
    time: str
    reason: str
    status: Literal['Booked', 'Completed', 'Cancelled']
    created_at: str

@router.put("/api/appointments/{id}", response_model=PutAppointmentsByIdResponse)
def handle_put_appointments_by_id(id: int, req: PutAppointmentsByIdRequest):
    # Edit one appointment Answers 409 when: That status change is not allowed (the database refuses it by itself and the app turns that into the 409: never check it in the route function).
    # error: raise HTTPException(status_code=404, detail="Appointment not found")
    # body: row = db.update_appointment(appointment_id=id, patient_name=req.patient_name, patient_phone=req.patient_phone, date=req.date, slot_time=req.time, reason=req.reason, status=req.status)
    # body: if row is None: raise HTTPException(status_code=404, detail="Appointment not found")
    # body: return row
    row = db.update_appointment(appointment_id=id, patient_name=req.patient_name, patient_phone=req.patient_phone, date=req.date, slot_time=req.time, reason=req.reason, status=req.status)
    if row is None: raise HTTPException(status_code=404, detail="Appointment not found")
    return row

class DeleteAppointmentsByIdResponse(BaseModel):
    deleted: bool

@router.delete("/api/appointments/{id}", response_model=DeleteAppointmentsByIdResponse)
def handle_delete_appointments_by_id(id: int):
    # Delete one appointment
    # error: raise HTTPException(status_code=404, detail="Appointment not found")
    # body: if not db.delete_appointment(appointment_id=id): raise HTTPException(status_code=404, detail="Appointment not found")
    # body: return {"deleted": True}
    if not db.delete_appointment(appointment_id=id): raise HTTPException(status_code=404, detail="Appointment not found")
    return {"deleted": True}

class PostAppointmentsCompleteByIdResponse(BaseModel):
    id: int
    doctor_id: int
    patient_name: str
    patient_phone: str
    date: str
    time: str
    reason: str
    status: Literal['Booked', 'Completed', 'Cancelled']
    created_at: str

@router.post("/api/appointments/{id}/complete", response_model=PostAppointmentsCompleteByIdResponse)
def handle_post_appointments_complete_by_id(id: int):
    # Complete one appointment: sets status to Completed and return the updated appointment Answers 409 when: That status change is not allowed (the database refuses it by itself and the app turns that into the 409: never check it in the route function).
    # error: raise HTTPException(status_code=404, detail="Appointment not found")
    # body: row = db.complete_appointment(id)
    # body: if row is None: raise HTTPException(status_code=404, detail="Appointment not found")
    # body: return row
    row = db.complete_appointment(id)
    if row is None: raise HTTPException(status_code=404, detail="Appointment not found")
    return row

class PostAppointmentsCancelByIdResponse(BaseModel):
    id: int
    doctor_id: int
    patient_name: str
    patient_phone: str
    date: str
    time: str
    reason: str
    status: Literal['Booked', 'Completed', 'Cancelled']
    created_at: str

@router.post("/api/appointments/{id}/cancel", response_model=PostAppointmentsCancelByIdResponse)
def handle_post_appointments_cancel_by_id(id: int):
    # Cancel one appointment: sets status to Cancelled and return the updated appointment Answers 409 when: That status change is not allowed (the database refuses it by itself and the app turns that into the 409: never check it in the route function).
    # error: raise HTTPException(status_code=404, detail="Appointment not found")
    # body: row = db.cancel_appointment(id)
    # body: if row is None: raise HTTPException(status_code=404, detail="Appointment not found")
    # body: return row
    row = db.cancel_appointment(id)
    if row is None: raise HTTPException(status_code=404, detail="Appointment not found")
    return row
