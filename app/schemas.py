"""Request/response schemas for POST /decide.

Design stance (see NOTES.md, "Input handling"):

* Be tolerant of *format*: enum casing/spacing/hyphens ("Out of Warranty"),
  a few common synonyms ("fridge", "geyser"), numbers sent as strings
  ("6,200", "Rs 900"), and the US spelling "labor_*". Hidden test data
  "will not look like yours in wording, format or distribution".
* Be strict about *meaning*: a value we cannot map to an allowed enum, a
  negative amount, NaN/Infinity, or a wrong JSON type is rejected with HTTP 422.
  Guessing would silently change the business decision.
* Missing optional inputs become ``None`` and are handled by the policy engine,
  which decides whether the missing value matters (app/policy.py). Only
  ``case_id`` is mandatory, because the response must echo it.
"""

from __future__ import annotations

import math
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------
# Allowed values (Appendix F of the brief)
# --------------------------------------------------------------------------


class ProductCategory(str, Enum):
    washing_machine = "washing_machine"
    refrigerator = "refrigerator"
    dishwasher = "dishwasher"
    oven_or_cooktop = "oven_or_cooktop"
    air_conditioner = "air_conditioner"
    water_heater = "water_heater"
    microwave = "microwave"


class WarrantyStatus(str, Enum):
    in_warranty = "in_warranty"
    extended = "extended"
    out_of_warranty = "out_of_warranty"
    unknown = "unknown"


class FaultCategory(str, Enum):
    no_power = "no_power"
    not_heating = "not_heating"
    not_cooling = "not_cooling"
    water_leak = "water_leak"
    drainage_or_blockage = "drainage_or_blockage"
    noise_or_vibration = "noise_or_vibration"
    door_seal_or_latch = "door_seal_or_latch"
    control_panel_or_display = "control_panel_or_display"
    electrical_or_control_board = "electrical_or_control_board"
    motor_or_drive = "motor_or_drive"
    installation_or_setup = "installation_or_setup"
    other = "other"


class Sentiment(str, Enum):
    negative = "negative"
    neutral = "neutral"
    positive = "positive"


class Decision(str, Enum):
    repair = "repair"
    replace = "replace"
    escalate = "escalate"


# Small, explicit synonym tables. Keys are already normalised
# (lower-case, spaces/hyphens -> underscores). Anything not here and not an
# exact enum value is rejected rather than guessed.
_PRODUCT_ALIASES = {
    "washer": "washing_machine",
    "washingmachine": "washing_machine",
    "fridge": "refrigerator",
    "refrigerator_freezer": "refrigerator",
    "fridge_freezer": "refrigerator",
    "dish_washer": "dishwasher",
    "oven": "oven_or_cooktop",
    "cooktop": "oven_or_cooktop",
    "hob": "oven_or_cooktop",
    "stove": "oven_or_cooktop",
    "range": "oven_or_cooktop",
    "oven_cooktop": "oven_or_cooktop",
    "ac": "air_conditioner",
    "a/c": "air_conditioner",
    "aircon": "air_conditioner",
    "air_conditioning": "air_conditioner",
    "geyser": "water_heater",
    "boiler": "water_heater",
    "microwave_oven": "microwave",
}
_WARRANTY_ALIASES = {
    "under_warranty": "in_warranty",
    "within_warranty": "in_warranty",
    "inwarranty": "in_warranty",
    "extended_warranty": "extended",
    "expired": "out_of_warranty",
    "no_warranty": "out_of_warranty",
    "out_warranty": "out_of_warranty",
    "outofwarranty": "out_of_warranty",
    "": "unknown",
    "na": "unknown",
    "n/a": "unknown",
    "none": "unknown",
    "null": "unknown",
    "unk": "unknown",
}
_FAULT_ALIASES = {
    "not_heating_up": "not_heating",
    "leak": "water_leak",
    "leaking": "water_leak",
    "drainage": "drainage_or_blockage",
    "blockage": "drainage_or_blockage",
    "noise": "noise_or_vibration",
    "vibration": "noise_or_vibration",
    "door": "door_seal_or_latch",
    "control_panel": "control_panel_or_display",
    "display": "control_panel_or_display",
    "electrical": "electrical_or_control_board",
    "control_board": "electrical_or_control_board",
    "motor": "motor_or_drive",
    "installation": "installation_or_setup",
    "setup": "installation_or_setup",
}
_SENTIMENT_ALIASES = {"neg": "negative", "pos": "positive", "angry": "negative", "happy": "positive"}

_NULL_TOKENS = {"", "null", "none", "na", "n/a", "unknown", "-"}


def _norm_token(value: str) -> str:
    return re.sub(r"[\s\-]+", "_", value.strip().lower())


def _normalise_enum(value: Any, enum_cls: type, aliases: Dict[str, str]) -> Any:
    if value is None or isinstance(value, enum_cls):
        return value
    if not isinstance(value, str):
        return value  # let pydantic produce the type error
    token = _norm_token(value)
    allowed = {m.value for m in enum_cls}
    if token in allowed:
        return token
    if token in aliases:
        return aliases[token]
    raise ValueError(
        f"{value!r} is not an allowed value; expected one of: {', '.join(sorted(allowed))}"
    )


_NUMBER_CLEAN = re.compile(r"^(?:rs\.?|inr|usd|eur|gbp|[$€£₹])?\s*([-+]?[\d,]*\.?\d+)\s*(?:rs\.?|inr|usd)?$")


def _coerce_number(value: Any) -> Any:
    """Accept "6,200", "₹ 900", "Rs. 900"; map "", "null", "n/a" to None.

    Anything else is passed through so pydantic reports a clean type error.
    Booleans are rejected explicitly (JSON true is not a price).
    """
    if isinstance(value, bool):
        raise ValueError("boolean is not a valid number")
    if isinstance(value, str):
        token = value.strip().lower()
        if token in _NULL_TOKENS:
            return None
        match = _NUMBER_CLEAN.match(token)
        if match:
            return float(match.group(1).replace(",", ""))
    return value


def _check_finite_non_negative(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    if math.isnan(value) or math.isinf(value):
        raise ValueError("must be a finite number")
    if value < 0:
        raise ValueError("must not be negative")
    return value


# --------------------------------------------------------------------------
# Request
# --------------------------------------------------------------------------


class Part(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sku: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    lead_time_days: Optional[float] = None

    @field_validator("sku", "description", mode="before")
    @classmethod
    def _stringify(cls, v: Any) -> Any:
        return str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v

    @field_validator("price", "lead_time_days", mode="before")
    @classmethod
    def _numbers(cls, v: Any) -> Any:
        return _coerce_number(v)

    @field_validator("price", "lead_time_days")
    @classmethod
    def _ranges(cls, v: Optional[float]) -> Optional[float]:
        return _check_finite_non_negative(v)


class ServiceCase(BaseModel):
    """One service case. Every field except ``case_id`` may be absent or null."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    case_id: Union[str, int]
    product_category: Optional[ProductCategory] = None
    product_age_months: Optional[float] = None
    purchase_price: Optional[float] = None
    replacement_price: Optional[float] = None
    warranty_status: WarrantyStatus = WarrantyStatus.unknown
    fault_category: Optional[FaultCategory] = None
    parts: List[Part] = Field(default_factory=list)
    labour_hours: Optional[float] = Field(
        default=None, validation_alias=AliasChoices("labour_hours", "labor_hours")
    )
    labour_rate_per_hour: Optional[float] = Field(
        default=None,
        validation_alias=AliasChoices("labour_rate_per_hour", "labor_rate_per_hour"),
    )
    technician_travel_minutes: Optional[float] = None
    prior_repairs_12m: Optional[float] = None
    customer_sentiment: Optional[Sentiment] = None
    symptom_text: str = ""

    @field_validator("case_id", mode="before")
    @classmethod
    def _case_id(cls, v: Any) -> Any:
        if isinstance(v, bool) or v is None:
            raise ValueError("case_id is required and must be a string")
        if isinstance(v, str) and not v.strip():
            raise ValueError("case_id must not be empty")
        return v

    @field_validator("product_category", mode="before")
    @classmethod
    def _product(cls, v: Any) -> Any:
        if isinstance(v, str) and _norm_token(v) in _NULL_TOKENS:
            return None
        return _normalise_enum(v, ProductCategory, _PRODUCT_ALIASES)

    @field_validator("warranty_status", mode="before")
    @classmethod
    def _warranty(cls, v: Any) -> Any:
        # Absent or null warranty is, literally, unknown -> rule D4 applies.
        if v is None:
            return WarrantyStatus.unknown
        return _normalise_enum(v, WarrantyStatus, _WARRANTY_ALIASES)

    @field_validator("fault_category", mode="before")
    @classmethod
    def _fault(cls, v: Any) -> Any:
        if isinstance(v, str) and _norm_token(v) in _NULL_TOKENS:
            return None
        return _normalise_enum(v, FaultCategory, _FAULT_ALIASES)

    @field_validator("customer_sentiment", mode="before")
    @classmethod
    def _sentiment(cls, v: Any) -> Any:
        if isinstance(v, str) and _norm_token(v) in _NULL_TOKENS:
            return None
        return _normalise_enum(v, Sentiment, _SENTIMENT_ALIASES)

    @field_validator("parts", mode="before")
    @classmethod
    def _parts(cls, v: Any) -> Any:
        return [] if v is None else v

    @field_validator("symptom_text", mode="before")
    @classmethod
    def _text(cls, v: Any) -> Any:
        return "" if v is None else v

    @field_validator(
        "product_age_months",
        "purchase_price",
        "replacement_price",
        "labour_hours",
        "labour_rate_per_hour",
        "technician_travel_minutes",
        "prior_repairs_12m",
        mode="before",
    )
    @classmethod
    def _numbers(cls, v: Any) -> Any:
        return _coerce_number(v)

    @field_validator(
        "product_age_months",
        "purchase_price",
        "replacement_price",
        "labour_hours",
        "labour_rate_per_hour",
        "technician_travel_minutes",
        "prior_repairs_12m",
    )
    @classmethod
    def _ranges(cls, v: Optional[float]) -> Optional[float]:
        return _check_finite_non_negative(v)


# --------------------------------------------------------------------------
# Response
# --------------------------------------------------------------------------


class DecisionResponse(BaseModel):
    case_id: Union[str, int]
    decision: Decision
    estimated_repair_cost: Optional[float]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class ExplainedResponse(DecisionResponse):
    """Returned only for ``POST /decide?explain=true`` (used by the UI)."""

    trace: Dict[str, Any]
