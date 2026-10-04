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


# --- the rules of a skill pack: request types that refuse a bad value with a 400 and a message the form can show ---------------------------------------------------

INVALID = "invalid"


def _phone(value: str, info: ValidationInfo) -> str:
    digits = "".join(c for c in value if c.isdigit())
    if len(digits) == 12 and digits.startswith("91"):  # +91 98765 43210
        digits = digits[2:]
    if len(digits) != 10 or digits[0] not in "6789":
        raise PydanticCustomError(INVALID, "{label} must be a 10-digit mobile number", {"label": _label(info.field_name)})
    return digits


def _email(value: str, info: ValidationInfo) -> str:
    name, _, domain = value.strip().partition("@")
    if not name or "." not in domain or " " in value.strip() or domain.startswith(".") or domain.endswith("."):
        raise PydanticCustomError(INVALID, "{label} must be a valid email address", {"label": _label(info.field_name)})
    return value.strip()


def _positive(value: float, info: ValidationInfo) -> float:
    if value <= 0:
        raise PydanticCustomError(INVALID, "{label} must be greater than 0", {"label": _label(info.field_name)})
    return value


Phone = Annotated[str, AfterValidator(_phone)]
Email = Annotated[str, AfterValidator(_email)]
Positive = Annotated[float, AfterValidator(_positive)]
PositiveInt = Annotated[int, AfterValidator(_positive)]


def between(low: float, high: float, integer: bool = False):
    """A number that must lie between low and high (both included): a rating from 1 to 5."""
    def check(value, info: ValidationInfo):
        if not low <= value <= high:
            raise PydanticCustomError(INVALID, "{label} must be between {low} and {high}", {"label": _label(info.field_name), "low": f"{low:g}", "high": f"{high:g}"})
        return value

    return Annotated[int if integer else float, AfterValidator(check)]
