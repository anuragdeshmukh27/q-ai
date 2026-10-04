from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import db

router = APIRouter()


class RegistrationIn(BaseModel):
    student_name: str
    email: str


@router.get("/events/{event_id}/registrations")
def list_registrations(event_id: int):
    # TODO: return {"items": [...]} with the registrations of this event, newest first (404 if the event does not exist)
    pass


@router.post("/events/{event_id}/registrations", status_code=201)
def add_registration(event_id: int, body: RegistrationIn):
    # TODO: store the registration with status "Registered" and return it (404 if the event does not exist)
    raise NotImplementedError


@router.post("/registrations/{registration_id}/check_in")
def check_in(registration_id: int):
    # TODO: set the status to "Checked in" and return the registration (404 if it does not exist)
    pass


@router.post("/registrations/{registration_id}/cancel")
def cancel(registration_id: int):
    # TODO: set the status to "Cancelled" and return the registration (404 if it does not exist)
    ...
