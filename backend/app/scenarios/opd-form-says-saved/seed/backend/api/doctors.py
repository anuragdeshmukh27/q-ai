"""Route stubs generated from the API contract. Fill in the bodies; keep paths, models and status codes."""
import json
import operator
import re
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.validation import Email, Phone, Positive, PositiveInt, Required, between
from database import appointments as appointments_db
from database import doctors as db

router = APIRouter()

class GetDoctorsResponse(BaseModel):
    items: list

@router.get("/api/doctors", response_model=GetDoctorsResponse)
def handle_get_doctors():
    # List all doctors
    # body: return {"items": db.list_doctors()}
    return {"items": db.list_doctors()}

class PostDoctorsRequest(BaseModel):
    name: Required
    department: Literal['General Medicine', 'Cardiology', 'Dermatology', 'Pediatrics', 'Orthopedics', 'ENT']
    phone: Phone
    email: Email
    consultation_fee: Positive
    room: Required
    availability: Literal['Available', 'On leave']

class PostDoctorsResponse(BaseModel):
    id: int
    name: str
    department: Literal['General Medicine', 'Cardiology', 'Dermatology', 'Pediatrics', 'Orthopedics', 'ENT']
    phone: str
    email: str
    consultation_fee: float
    room: str
    availability: Literal['Available', 'On leave']
    created_at: str

@router.post("/api/doctors", status_code=201, response_model=PostDoctorsResponse)
def handle_post_doctors(req: PostDoctorsRequest):
    # Add a doctor Answers 409 when: Email already exists (the database refuses it by itself and the app turns that into the 409: never check it in the route function).
    # body: return db.add_doctor(name=req.name, department=req.department, phone=req.phone, email=req.email, consultation_fee=req.consultation_fee, room=req.room, availability=req.availability)
    return db.add_doctor(name=req.name, department=req.department, phone=req.phone, email=req.email, consultation_fee=req.consultation_fee, room=req.room, availability=req.availability)

class PutDoctorsByIdRequest(BaseModel):
    name: Required
    department: Literal['General Medicine', 'Cardiology', 'Dermatology', 'Pediatrics', 'Orthopedics', 'ENT']
    phone: Phone
    email: Email
    consultation_fee: Positive
    room: Required
    availability: Literal['Available', 'On leave']

class PutDoctorsByIdResponse(BaseModel):
    id: int
    name: str
    department: Literal['General Medicine', 'Cardiology', 'Dermatology', 'Pediatrics', 'Orthopedics', 'ENT']
    phone: str
    email: str
    consultation_fee: float
    room: str
    availability: Literal['Available', 'On leave']
    created_at: str

@router.put("/api/doctors/{id}", response_model=PutDoctorsByIdResponse)
def handle_put_doctors_by_id(id: int, req: PutDoctorsByIdRequest):
    # Edit one doctor Answers 409 when: Email already exists (the database refuses it by itself and the app turns that into the 409: never check it in the route function).
    # error: raise HTTPException(status_code=404, detail="Doctor not found")
    # body: row = db.update_doctor(doctor_id=id, name=req.name, department=req.department, phone=req.phone, email=req.email, consultation_fee=req.consultation_fee, room=req.room, availability=req.availability)
    # body: if row is None: raise HTTPException(status_code=404, detail="Doctor not found")
    # body: return row
    row = db.update_doctor(doctor_id=id, name=req.name, department=req.department, phone=req.phone, email=req.email, consultation_fee=req.consultation_fee, room=req.room, availability=req.availability)
    if row is None: raise HTTPException(status_code=404, detail="Doctor not found")
    return row

class DeleteDoctorsByIdResponse(BaseModel):
    deleted: bool

@router.delete("/api/doctors/{id}", response_model=DeleteDoctorsByIdResponse)
def handle_delete_doctors_by_id(id: int):
    # Delete one doctor and its appointments, prescriptions, lab_tests
    # error: raise HTTPException(status_code=404, detail="Doctor not found")
    # body: if not db.delete_doctor(doctor_id=id): raise HTTPException(status_code=404, detail="Doctor not found")
    # body: return {"deleted": True}
    if not db.delete_doctor(doctor_id=id): raise HTTPException(status_code=404, detail="Doctor not found")
    return {"deleted": True}


def booked_times(doctor_id: int, date: str) -> list[str]:
    """The times of day already taken on `date`, earliest first (what the front desk's slot picker greys out)."""
    return [row["slot_at"] for row in appointments_db.booked_slots(doctor_id, date)]


class GetDoctorsSlotsByIdResponse(BaseModel):
    date: str
    booked: list[str]


@router.get("/api/doctors/{id}/slots", response_model=GetDoctorsSlotsByIdResponse)
def handle_get_doctors_slots_by_id(id: int, date: str):
    # The booked times of one doctor on one date
    # error: raise HTTPException(status_code=404, detail="Doctor not found")
    if db.get_doctor(id) is None: raise HTTPException(status_code=404, detail="Doctor not found")
    return {"date": date, "booked": booked_times(id, date)}
