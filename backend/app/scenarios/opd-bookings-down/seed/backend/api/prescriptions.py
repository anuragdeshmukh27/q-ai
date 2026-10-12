"""Route stubs generated from the API contract. Fill in the bodies; keep paths, models and status codes."""
import json
import operator
import re
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.validation import Email, Phone, Positive, PositiveInt, Required, between
from database import prescriptions as db
from database import doctors as doctors_db

router = APIRouter()

class GetDoctorsPrescriptionsByDoctor_idResponse(BaseModel):
    items: list

@router.get("/api/doctors/{doctor_id}/prescriptions", response_model=GetDoctorsPrescriptionsByDoctor_idResponse)
def handle_get_doctors_prescriptions_by_doctor_id(doctor_id: int):
    # List the prescriptions of one doctor
    # error: raise HTTPException(status_code=404, detail="Doctor not found")
    # body: if doctors_db.get_doctor(doctor_id) is None: raise HTTPException(status_code=404, detail="Doctor not found")
    # body: return {"items": db.list_prescriptions(doctor_id=doctor_id)}
    if doctors_db.get_doctor(doctor_id) is None: raise HTTPException(status_code=404, detail="Doctor not found")
    return {"items": db.list_prescriptions(doctor_id=doctor_id)}

class PostDoctorsPrescriptionsByDoctor_idRequest(BaseModel):
    patient_name: Required
    medicine: Required
    dosage: Required
    days: between(1, 90, True)
    instructions: Required

class PostDoctorsPrescriptionsByDoctor_idResponse(BaseModel):
    id: int
    doctor_id: int
    patient_name: str
    medicine: str
    dosage: str
    days: int
    instructions: str
    created_at: str

@router.post("/api/doctors/{doctor_id}/prescriptions", status_code=201, response_model=PostDoctorsPrescriptionsByDoctor_idResponse)
def handle_post_doctors_prescriptions_by_doctor_id(doctor_id: int, req: PostDoctorsPrescriptionsByDoctor_idRequest):
    # Add a prescription to a doctor
    # error: raise HTTPException(status_code=404, detail="Doctor not found")
    # body: if doctors_db.get_doctor(doctor_id) is None: raise HTTPException(status_code=404, detail="Doctor not found")
    # body: return db.add_prescription(doctor_id=doctor_id, patient_name=req.patient_name, medicine=req.medicine, dosage=req.dosage, days=req.days, instructions=req.instructions)
    if doctors_db.get_doctor(doctor_id) is None: raise HTTPException(status_code=404, detail="Doctor not found")
    return db.add_prescription(doctor_id=doctor_id, patient_name=req.patient_name, medicine=req.medicine, dosage=req.dosage, days=req.days, instructions=req.instructions)

class PutPrescriptionsByIdRequest(BaseModel):
    patient_name: Required
    medicine: Required
    dosage: Required
    days: between(1, 90, True)
    instructions: Required

class PutPrescriptionsByIdResponse(BaseModel):
    id: int
    doctor_id: int
    patient_name: str
    medicine: str
    dosage: str
    days: int
    instructions: str
    created_at: str

@router.put("/api/prescriptions/{id}", response_model=PutPrescriptionsByIdResponse)
def handle_put_prescriptions_by_id(id: int, req: PutPrescriptionsByIdRequest):
    # Edit one prescription
    # error: raise HTTPException(status_code=404, detail="Prescription not found")
    # body: row = db.update_prescription(prescription_id=id, patient_name=req.patient_name, medicine=req.medicine, dosage=req.dosage, days=req.days, instructions=req.instructions)
    # body: if row is None: raise HTTPException(status_code=404, detail="Prescription not found")
    # body: return row
    row = db.update_prescription(prescription_id=id, patient_name=req.patient_name, medicine=req.medicine, dosage=req.dosage, days=req.days, instructions=req.instructions)
    if row is None: raise HTTPException(status_code=404, detail="Prescription not found")
    return row

class DeletePrescriptionsByIdResponse(BaseModel):
    deleted: bool

@router.delete("/api/prescriptions/{id}", response_model=DeletePrescriptionsByIdResponse)
def handle_delete_prescriptions_by_id(id: int):
    # Delete one prescription
    # error: raise HTTPException(status_code=404, detail="Prescription not found")
    # body: if not db.delete_prescription(prescription_id=id): raise HTTPException(status_code=404, detail="Prescription not found")
    # body: return {"deleted": True}
    if not db.delete_prescription(prescription_id=id): raise HTTPException(status_code=404, detail="Prescription not found")
    return {"deleted": True}
