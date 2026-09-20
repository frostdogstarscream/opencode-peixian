from datetime import datetime, timedelta
import os
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageRequest(StrictModel):
    number: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=100)


class PersonQuery(StrictModel):
    certificate_no: str = Field(pattern=r"^[0-9]{17}[0-9Xx]$")
    begin_time: datetime | None = None
    end_time: datetime | None = None
    page: PageRequest = Field(default_factory=PageRequest)

    @model_validator(mode="after")
    def validate_range(self):
        if (self.begin_time is None) != (self.end_time is None):
            raise ValueError("begin_time and end_time must be supplied together")
        if self.begin_time and self.end_time and self.begin_time > self.end_time:
            raise ValueError("begin_time must not be later than end_time")
        if self.begin_time and self.end_time and self.end_time - self.begin_time > timedelta(days=int(os.environ.get("PEIXIAN_MAX_QUERY_DAYS", "366"))):
            raise ValueError("query time range exceeds the configured limit")
        return self


class TrackQuery(PersonQuery):
    begin_time: datetime
    end_time: datetime
    track_types: list[Literal[0, 1, 2]] = Field(default_factory=lambda: [0, 1, 2], min_length=1, max_length=3)


class PageResult(StrictModel):
    number: int
    size: int
    has_more: bool


class PersonProfile(StrictModel):
    name: str | None = None
    certificate_no: str | None = None
    household_address: str | None = None
    household_type: str | None = None
    household_status: str | None = None
    relation_to_head: str | None = None
    father_name: str | None = None
    father_certificate_no: str | None = None
    mother_name: str | None = None
    mother_certificate_no: str | None = None
    occupation: str | None = None
    source_record_id: str | None = None


class HouseRecord(StrictModel):
    source_record_id: str | None = None
    address: str | None = None
    room_count: str | None = None
    property_type: str | None = None
    usage: str | None = None
    status: str | None = None
    rented: bool | None = None


class CompanyRecord(StrictModel):
    source_record_id: str | None = None
    name: str | None = None
    address: str | None = None
    telephone: str | None = None
    business_scope: str | None = None
    employee_count: int | None = None
    issued_at: str | None = None


class FamilyRelation(StrictModel):
    related_name: str | None = None
    related_certificate_no: str | None = None
    relation: str | None = None
    age: int | None = None
    collected_at: str | None = None
    data_source: str | None = None
    source_record_id: str | None = None


class CaseRecord(StrictModel):
    source_record_id: str | None = None
    case_name: str | None = None
    category: str | None = None
    status: str | None = None
    occurred_at: str | None = None
    address: str | None = None
    summary: str | None = None
    unit: str | None = None
    person_role: str | None = None


class IncidentRecord(StrictModel):
    source_record_id: str | None = None
    category: str | None = None
    occurred_at: str | None = None
    address: str | None = None
    summary: str | None = None
    unit: str | None = None
    person_role: str | None = None


class DisputeRecord(StrictModel):
    source_record_id: str | None = None
    category: str | None = None
    registered_at: str | None = None
    mediation_at: str | None = None
    location: str | None = None
    result: str | None = None
    agreement: str | None = None
    unit: str | None = None


class TrackRecord(StrictModel):
    source_record_id: str | None = None
    captured_at: str | None = None
    track_type: str | None = None
    location_name: str | None = None
    location_code: str | None = None
    device_id: str | None = None
    plate_no: str | None = None


class HotelRecord(StrictModel):
    source_record_id: str | None = None
    hotel_name: str | None = None
    hotel_address: str | None = None
    room_no: str | None = None
    checked_in_at: str | None = None
    checked_out_at: str | None = None


class RailwayRecord(StrictModel):
    source_record_id: str | None = None
    name: str | None = None
    train_no: str | None = None
    departure_station: str | None = None
    arrival_station: str | None = None
    departure_date: str | None = None
    entered_at: str | None = None


class NetbarRecord(StrictModel):
    source_record_id: str | None = None
    venue_name: str | None = None
    venue_address: str | None = None
    seat_no: str | None = None
    started_at: str | None = None
    ended_at: str | None = None


class MotorVehicleRecord(StrictModel):
    source_record_id: str | None = None
    plate_no: str | None = None
    plate_type: str | None = None
    vehicle_type: str | None = None
    brand: str | None = None
    color: str | None = None
    vin: str | None = None
    registered_at: str | None = None
    status: str | None = None


class NonMotorVehicleRecord(StrictModel):
    source_record_id: str | None = None
    plate_no: str | None = None
    brand: str | None = None
    color: str | None = None
    registered_at: str | None = None
    status: str | None = None


Item = TypeVar("Item", bound=StrictModel)


class QueryResponse(StrictModel, Generic[Item]):
    schema_version: Literal["1.0"] = "1.0"
    trace_id: str
    source: str
    queried_at: datetime
    returned_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    page: PageResult
    items: list[Item]
    warnings: list[str] = Field(default_factory=list)


class ErrorDetail(StrictModel):
    code: str
    message: str
    retryable: bool
    trace_id: str


class ErrorResponse(StrictModel):
    error: ErrorDetail
