from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import db

router = APIRouter()


class EventIn(BaseModel):
    name: str
    venue: str
    capacity: int = 100


@router.get("/events")
def list_events():
    return {"items": db.list_events()}


@router.post("/events", status_code=201)
def create_event(body: EventIn):
    return db.add_event(body.name, body.venue, body.capacity)


@router.delete("/events/{event_id}")
def delete_event(event_id: int):
    if not db.delete_event(event_id):
        raise HTTPException(404, "Event not found")
    return {"deleted": True}
