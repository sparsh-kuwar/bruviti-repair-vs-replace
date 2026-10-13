"""Shared fixtures. Every test runs with outbound networking disabled.

``block_network`` replaces socket connect/DNS calls for the whole session, so a
test that accidentally (or a library that silently) reaches the network fails
loudly. FastAPI's TestClient talks to the app in-process and needs no socket.

Loopback (127.0.0.1, ::1, localhost) stays allowed: on Windows, Python's event
loop builds its internal self-pipe with a socketpair that connects to
127.0.0.1, and the startup tests talk to a server on this machine. Nothing
outside the machine is reachable.
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


LOOPBACK = {"127.0.0.1", "::1", "localhost", "0:0:0:0:0:0:0:1"}
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_create_connection = socket.create_connection
_real_getaddrinfo = socket.getaddrinfo


def _is_local(address: Any) -> bool:
    if isinstance(address, (str, bytes)):  # AF_UNIX path: local by definition
        return True
    host = address[0] if isinstance(address, tuple) and address else None
    return host in LOOPBACK


def _guard(real):
    def wrapper(self_or_addr, *args: Any, **kwargs: Any):
        address = args[0] if real in (_real_connect, _real_connect_ex) else self_or_addr
        if not _is_local(address):
            raise NetworkBlocked(f"network access attempted during tests: {address!r}")
        return real(self_or_addr, *args, **kwargs)
    return wrapper


def _guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any):
    if host not in LOOPBACK and host is not None:
        raise NetworkBlocked(f"DNS lookup attempted during tests: {host!r}")
    return _real_getaddrinfo(host, *args, **kwargs)


@pytest.fixture(autouse=True, scope="session")
def block_network():
    mp = pytest.MonkeyPatch()
    mp.setattr(socket.socket, "connect", _guard(_real_connect))
    mp.setattr(socket.socket, "connect_ex", _guard(_real_connect_ex))
    mp.setattr(socket, "create_connection", _guard(_real_create_connection))
    mp.setattr(socket, "getaddrinfo", _guarded_getaddrinfo)
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
