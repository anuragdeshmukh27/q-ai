"""Route stubs generated from the API contract. Fill in the bodies; keep paths, models and status codes."""
import json
import operator
import re
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.validation import Email, Phone, Positive, PositiveInt, Required, between
from database import lab_tests as db
from database import doctors as doctors_db

router = APIRouter()

class GetDoctorsLabTestsByDoctor_idResponse(BaseModel):
    items: list

@router.get("/api/doctors/{doctor_id}/lab_tests", response_model=GetDoctorsLabTestsByDoctor_idResponse)
def handle_get_doctors_lab_tests_by_doctor_id(doctor_id: int):
    # List the lab_tests of one doctor
    # error: raise HTTPException(status_code=404, detail="Doctor not found")
    # body: if doctors_db.get_doctor(doctor_id) is None: raise HTTPException(status_code=404, detail="Doctor not found")
    # body: return {"items": db.list_lab_tests(doctor_id=doctor_id)}
    if doctors_db.get_doctor(doctor_id) is None: raise HTTPException(status_code=404, detail="Doctor not found")
    return {"items": db.list_lab_tests(doctor_id=doctor_id)}

class PostDoctorsLabTestsByDoctor_idRequest(BaseModel):
    patient_name: Required
    test_name: Literal['Blood test', 'X-ray', 'MRI', 'ECG', 'Urine test']
    cost: Positive
    status: Literal['Ordered', 'Collected', 'Reported']

class PostDoctorsLabTestsByDoctor_idResponse(BaseModel):
    id: int
    doctor_id: int
    patient_name: str
    test_name: Literal['Blood test', 'X-ray', 'MRI', 'ECG', 'Urine test']
    cost: float
    status: Literal['Ordered', 'Collected', 'Reported']
    created_at: str

@router.post("/api/doctors/{doctor_id}/lab_tests", status_code=201, response_model=PostDoctorsLabTestsByDoctor_idResponse)
def handle_post_doctors_lab_tests_by_doctor_id(doctor_id: int, req: PostDoctorsLabTestsByDoctor_idRequest):
    # Add a lab_test to a doctor
    # error: raise HTTPException(status_code=404, detail="Doctor not found")
    # body: if doctors_db.get_doctor(doctor_id) is None: raise HTTPException(status_code=404, detail="Doctor not found")
    # body: return db.add_lab_test(doctor_id=doctor_id, patient_name=req.patient_name, test_name=req.test_name, cost=req.cost, status=req.status)
    if doctors_db.get_doctor(doctor_id) is None: raise HTTPException(status_code=404, detail="Doctor not found")
    return db.add_lab_test(doctor_id=doctor_id, patient_name=req.patient_name, test_name=req.test_name, cost=req.cost, status=req.status)

class PutLabTestsByIdRequest(BaseModel):
    patient_name: Required
    test_name: Literal['Blood test', 'X-ray', 'MRI', 'ECG', 'Urine test']
    cost: Positive
    status: Literal['Ordered', 'Collected', 'Reported']

class PutLabTestsByIdResponse(BaseModel):
    id: int
    doctor_id: int
    patient_name: str
    test_name: Literal['Blood test', 'X-ray', 'MRI', 'ECG', 'Urine test']
    cost: float
    status: Literal['Ordered', 'Collected', 'Reported']
    created_at: str

@router.put("/api/lab_tests/{id}", response_model=PutLabTestsByIdResponse)
def handle_put_lab_tests_by_id(id: int, req: PutLabTestsByIdRequest):
    # Edit one lab_test Answers 409 when: That status change is not allowed (the database refuses it by itself and the app turns that into the 409: never check it in the route function).
    # error: raise HTTPException(status_code=404, detail="Lab test not found")
    # body: row = db.update_lab_test(lab_test_id=id, patient_name=req.patient_name, test_name=req.test_name, cost=req.cost, status=req.status)
    # body: if row is None: raise HTTPException(status_code=404, detail="Lab test not found")
    # body: return row
    row = db.update_lab_test(lab_test_id=id, patient_name=req.patient_name, test_name=req.test_name, cost=req.cost, status=req.status)
    if row is None: raise HTTPException(status_code=404, detail="Lab test not found")
    return row

class DeleteLabTestsByIdResponse(BaseModel):
    deleted: bool

@router.delete("/api/lab_tests/{id}", response_model=DeleteLabTestsByIdResponse)
def handle_delete_lab_tests_by_id(id: int):
    # Delete one lab_test
    # error: raise HTTPException(status_code=404, detail="Lab test not found")
    # body: if not db.delete_lab_test(lab_test_id=id): raise HTTPException(status_code=404, detail="Lab test not found")
    # body: return {"deleted": True}
    if not db.delete_lab_test(lab_test_id=id): raise HTTPException(status_code=404, detail="Lab test not found")
    return {"deleted": True}

class PostLabTestsCollectByIdResponse(BaseModel):
    id: int
    doctor_id: int
    patient_name: str
    test_name: Literal['Blood test', 'X-ray', 'MRI', 'ECG', 'Urine test']
    cost: float
    status: Literal['Ordered', 'Collected', 'Reported']
    created_at: str

@router.post("/api/lab_tests/{id}/collect", response_model=PostLabTestsCollectByIdResponse)
def handle_post_lab_tests_collect_by_id(id: int):
    # Collect one lab_test: sets status to Collected and return the updated lab_test Answers 409 when: That status change is not allowed (the database refuses it by itself and the app turns that into the 409: never check it in the route function).
    # error: raise HTTPException(status_code=404, detail="Lab test not found")
    # body: row = db.collect_lab_test(id)
    # body: if row is None: raise HTTPException(status_code=404, detail="Lab test not found")
    # body: return row
    row = db.collect_lab_test(id)
    if row is None: raise HTTPException(status_code=404, detail="Lab test not found")
    return row

class PostLabTestsReportByIdResponse(BaseModel):
    id: int
    doctor_id: int
    patient_name: str
    test_name: Literal['Blood test', 'X-ray', 'MRI', 'ECG', 'Urine test']
    cost: float
    status: Literal['Ordered', 'Collected', 'Reported']
    created_at: str

@router.post("/api/lab_tests/{id}/report", response_model=PostLabTestsReportByIdResponse)
def handle_post_lab_tests_report_by_id(id: int):
    # Report one lab_test: sets status to Reported and return the updated lab_test Answers 409 when: That status change is not allowed (the database refuses it by itself and the app turns that into the 409: never check it in the route function).
    # error: raise HTTPException(status_code=404, detail="Lab test not found")
    # body: row = db.report_lab_test(id)
    # body: if row is None: raise HTTPException(status_code=404, detail="Lab test not found")
    # body: return row
    row = db.report_lab_test(id)
    if row is None: raise HTTPException(status_code=404, detail="Lab test not found")
    return row
