import hmac
import hashlib
import json
import logging
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4

from fastapi import Depends, FastAPI, Header
from fastapi.responses import JSONResponse

from models import (
    CaseRecord,
    CompanyRecord,
    DisputeRecord,
    ErrorResponse,
    FamilyRelation,
    HotelRecord,
    HouseRecord,
    IncidentRecord,
    MotorVehicleRecord,
    NetbarRecord,
    NonMotorVehicleRecord,
    PageResult,
    PersonProfile,
    PersonQuery,
    QueryResponse,
    RailwayRecord,
    TrackQuery,
    TrackRecord,
)
from providers import LegacyProvider, MockProvider, ProviderError
from settings import setting


mode = setting("PEIXIAN_ADAPTER_MODE", "mock")
if mode not in ("mock", "legacy"):
    raise RuntimeError("PEIXIAN_ADAPTER_MODE must be mock or legacy")
if mode == "legacy" and (not setting("PEIXIAN_ADAPTER_TOKEN") or not setting("PEIXIAN_AUDIT_HMAC_KEY")):
    raise RuntimeError("legacy mode requires adapter token and audit HMAC key")

app = FastAPI(title="沛县公安统一数据适配服务", version="1.0.0")
provider = MockProvider() if mode == "mock" else LegacyProvider()
logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.INFO)


def authorize(authorization: str | None = Header(default=None)):
    expected = setting("PEIXIAN_ADAPTER_TOKEN")
    if not expected and mode == "mock":
        return
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not expected or not hmac.compare_digest(supplied, expected):
        raise ProviderError("UNAUTHORIZED", "未获得数据服务访问权限", False, 401)


@app.exception_handler(ProviderError)
async def provider_error(_, error: ProviderError):
    trace_id = error.trace_id or str(uuid4())
    if error.trace_id is None:
        audit(trace_id=trace_id, status="rejected", error_code=error.code)
    return JSONResponse(status_code=error.status_code, content={"error": {"code": error.code, "message": error.message, "retryable": error.retryable, "trace_id": trace_id}})


@app.get("/health", dependencies=[Depends(authorize)])
async def health():
    return {"ok": True, "mode": mode, "schema_version": "1.0"}


async def query(source: str, request: PersonQuery):
    trace_id = str(uuid4())
    started = monotonic()
    try:
        result = await provider.query(source, request)
    except ProviderError as error:
        error.trace_id = trace_id
        audit(trace_id=trace_id, source=source, subject_hash=subject_hash(request.certificate_no),
              status="error", error_code=error.code, elapsed_ms=int((monotonic() - started) * 1000))
        raise
    items = result["items"]
    audit(trace_id=trace_id, source=source, subject_hash=subject_hash(request.certificate_no),
          status="success", returned_count=len(items), elapsed_ms=int((monotonic() - started) * 1000))
    return {
        "schema_version": "1.0",
        "trace_id": trace_id,
        "source": result["source"],
        "queried_at": datetime.now(timezone.utc),
        "returned_count": len(items),
        "total_count": result["total_count"],
        "page": PageResult(number=request.page.number, size=request.page.size, has_more=request.page.number * request.page.size < result["total_count"]),
        "items": items,
        "warnings": result["warnings"],
    }


def subject_hash(value: str):
    key = setting("PEIXIAN_AUDIT_HMAC_KEY", "mock-only-audit-key")
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def audit(**fields):
    logger.info(json.dumps({"event": "peixian_data_query", **fields}, ensure_ascii=False, separators=(",", ":")))


@app.post("/v1/person/profile/query", response_model=QueryResponse[PersonProfile], responses={401: {"model": ErrorResponse}})
async def person_profile(request: PersonQuery, _: None = Depends(authorize)):
    return await query("profile", request)


@app.post("/v1/person/houses/query", response_model=QueryResponse[HouseRecord])
async def person_houses(request: PersonQuery, _: None = Depends(authorize)):
    return await query("houses", request)


@app.post("/v1/person/companies/query", response_model=QueryResponse[CompanyRecord])
async def person_companies(request: PersonQuery, _: None = Depends(authorize)):
    return await query("companies", request)


@app.post("/v1/person/family/query", response_model=QueryResponse[FamilyRelation])
async def person_family(request: PersonQuery, _: None = Depends(authorize)):
    return await query("family", request)


@app.post("/v1/police/cases/query", response_model=QueryResponse[CaseRecord])
async def police_cases(request: PersonQuery, _: None = Depends(authorize)):
    return await query("cases", request)


@app.post("/v1/police/incidents/query", response_model=QueryResponse[IncidentRecord])
async def police_incidents(request: PersonQuery, _: None = Depends(authorize)):
    return await query("incidents", request)


@app.post("/v1/police/disputes/query", response_model=QueryResponse[DisputeRecord])
async def police_disputes(request: PersonQuery, _: None = Depends(authorize)):
    return await query("disputes", request)


@app.post("/v1/mobility/tracks/query", response_model=QueryResponse[TrackRecord])
async def mobility_tracks(request: TrackQuery, _: None = Depends(authorize)):
    return await query("tracks", request)


@app.post("/v1/mobility/hotels/query", response_model=QueryResponse[HotelRecord])
async def mobility_hotels(request: PersonQuery, _: None = Depends(authorize)):
    return await query("hotels", request)


@app.post("/v1/mobility/railway/query", response_model=QueryResponse[RailwayRecord])
async def mobility_railway(request: PersonQuery, _: None = Depends(authorize)):
    return await query("railway", request)


@app.post("/v1/mobility/netbar/query", response_model=QueryResponse[NetbarRecord])
async def mobility_netbar(request: PersonQuery, _: None = Depends(authorize)):
    return await query("netbar", request)


@app.post("/v1/vehicle/motor/query", response_model=QueryResponse[MotorVehicleRecord])
async def vehicle_motor(request: PersonQuery, _: None = Depends(authorize)):
    return await query("motor", request)


@app.post("/v1/vehicle/non-motor/query", response_model=QueryResponse[NonMotorVehicleRecord])
async def vehicle_non_motor(request: PersonQuery, _: None = Depends(authorize)):
    return await query("non_motor", request)
