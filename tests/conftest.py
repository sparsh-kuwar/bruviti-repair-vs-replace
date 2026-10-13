"""Shared fixtures. Every test runs with outbound networking disabled.

``block_network`` replaces socket connect/DNS calls for the whole session, so a
test that accidentally (or a library that silently) reaches the network fails
loudly. FastAPI's TestClient talks to the app in-process and needs no socket.
"""

from __future__ import annotations

import copy
import socket
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.policy import decide
from app.schemas import ServiceCase


class NetworkBlocked(RuntimeError):
    pass


def _blocked(*args: Any, **kwargs: Any):
    raise NetworkBlocked("network access attempted during tests")


@pytest.fixture(autouse=True, scope="session")
def block_network():
    mp = pytest.MonkeyPatch()
    mp.setattr(socket.socket, "connect", _blocked)
    mp.setattr(socket.socket, "connect_ex", _blocked)
    mp.setattr(socket, "create_connection", _blocked)
    mp.setattr(socket, "getaddrinfo", _blocked)
    yield
    mp.undo()


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


# A clean out-of-warranty repair (rule D2): cost 8150 = 22.6% of 36000, age 25%.
BASE: Dict[str, Any] = {
    "case_id": "T-1",
    "product_category": "washing_machine",
    "product_age_months": 30,
    "purchase_price": 38000,
    "replacement_price": 36000,
    "warranty_status": "out_of_warranty",
    "fault_category": "motor_or_drive",
    "parts": [{"sku": "P1", "description": "Drive motor", "price": 6200, "lead_time_days": 4}],
    "labour_hours": 1.5,
    "labour_rate_per_hour": 900,
    "technician_travel_minutes": 40,
    "prior_repairs_12m": 0,
    "customer_sentiment": "neutral",
    "symptom_text": "drum does not turn, motor hums",
}


def case(**overrides: Any) -> Dict[str, Any]:
    data = copy.deepcopy(BASE)
    data.update(overrides)
    return data


def ratio_case(part_price: float, replacement: float = 10000, **overrides: Any) -> Dict[str, Any]:
    """Labour and travel zeroed so cost/replacement == part_price/replacement exactly."""
    data = case(
        parts=[{"sku": "P1", "description": "part", "price": part_price, "lead_time_days": 2}],
        labour_hours=0,
        technician_travel_minutes=0,
        replacement_price=replacement,
        symptom_text="",
    )
    data.update(overrides)
    return data


def run(data: Dict[str, Any]):
    return decide(ServiceCase.model_validate(data))
