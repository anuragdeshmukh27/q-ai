"""Request validation shared by every router (locked: engineers use it, they never edit it).

`Required` is a text field that must not be empty or only spaces. The generated request models use it for every required text field of a resource,
a parent and a child alike, so an empty title, an empty comment and an empty author are all refused the same way: HTTP 400 and `{"detail": "Comment is required"}`
(backend/main.py turns the error into that answer; a missing or mistyped field is still FastAPI's 422).
"""
from typing import Annotated

from pydantic import AfterValidator, ValidationInfo
from pydantic_core import PydanticCustomError

BLANK = "blank"


def _label(name: str | None) -> str:
    return (name or "this field").replace("_", " ").strip().capitalize()


def _required(value: str, info: ValidationInfo) -> str:
    if not value.strip():
        raise PydanticCustomError(BLANK, "{label} is required", {"label": _label(info.field_name)})
    return value


Required = Annotated[str, AfterValidator(_required)]
