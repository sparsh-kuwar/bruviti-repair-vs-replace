"""FastAPI service: POST /decide, GET /health, and the single page at /.

One process serves everything on port 8000. No outbound network calls are made
at request time (or at all); the UI's assets are served from app/static.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .policy import decide
from .schemas import DecisionResponse, ExplainedResponse, ServiceCase

STATIC_DIR = Path(__file__).parent / "static"
log = logging.getLogger("decide")

app = FastAPI(
    title="Repair vs Replace Decision Service",
    version="1.0.0",
    description="Applies the repair/replace/escalate policy (rules D0-D6) to one service case.",
)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Clean 422. The default handler echoes the offending input, which crashes
    JSON encoding when that input is NaN/Infinity -- so we return only the
    location and message of each error."""
    detail = [
        {"loc": list(e.get("loc", ())), "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detail})


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.post(
    "/decide",
    response_model=None,
    responses={200: {"model": DecisionResponse, "description": "Decision for one case"}},
)
def decide_case(
    case: ServiceCase,
    explain: bool = Query(False, description="Also return the rule trace (used by the UI)."),
) -> JSONResponse:
    try:
        result = decide(case)
    except Exception:  # pragma: no cover - defensive; no known path reaches here
        # A bug must never turn into a 500 for a valid case: hand it to a human.
        log.exception("policy engine failed for case %r", case.case_id)
        return JSONResponse({
            "case_id": case.case_id,
            "decision": "escalate",
            "estimated_repair_cost": None,
            "confidence": 0.3,
            "reason": "Escalate: the case could not be evaluated automatically and needs manual review.",
        })
    model = (
        ExplainedResponse(**result.public(), trace=result.trace)
        if explain
        else DecisionResponse(**result.public())
    )
    return JSONResponse(model.model_dump(mode="json"))


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
