import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import httpx

from models import PersonQuery, TrackQuery
from settings import setting


class ProviderError(Exception):
    def __init__(self, code: str, message: str, retryable: bool, status_code: int = 502, trace_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status_code = status_code
        self.trace_id = trace_id


class MockProvider:
    def __init__(self):
        self.data = json.loads((Path(__file__).parent / "fixtures" / "mock-data.json").read_text(encoding="utf-8"))

    async def query(self, source: str, request: PersonQuery):
        items = self.data.get(source, [])
        start = (request.page.number - 1) * request.page.size
        return {
            "source": "沛县公安脱敏合成数据",
            "total_count": len(items),
            "items": items[start : start + request.page.size],
            "warnings": ["当前结果来自本地脱敏 Mock 数据，不得作为真实研判依据。"],
        }


class LegacyProvider:
    profile_paths = {
        "profile": "/foreignApply/profileCensusRegister/{certificate_no}",
        "houses": "/foreignApply/profileHouse/{certificate_no}",
        "companies": "/foreignApply/profileCompany/{certificate_no}",
        "disputes": "/foreignApply/getDisputeList/{certificate_no}",
        "hotels": "/foreignApply/profileHotel/{certificate_no}",
        "railway": "/foreignApply/getRailwayList/{certificate_no}",
        "netbar": "/foreignApply/profileNetBar/{certificate_no}",
        "motor": "/foreignApply/profileVehicle/{certificate_no}",
        "non_motor": "/foreignApply/profileNonVehicle/{certificate_no}",
    }

    async def query(self, source: str, request: PersonQuery):
        if source in self.profile_paths:
            return await self.query_profile(source, request)
        if source == "family":
            return await self.query_post("FAMILY", source, request, {"certificate_no": request.certificate_no})
        if source == "tracks":
            if not isinstance(request, TrackQuery):
                raise ProviderError("INVALID_REQUEST", "轨迹查询参数不完整", False, 422)
            return await self.query_post("TRACKS", source, request, {
                "certificate_no": request.certificate_no,
                "begin_time": request.begin_time.strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": request.end_time.strftime("%Y-%m-%d %H:%M:%S"),
                "track_type": request.track_types,
            })
        if source == "cases":
            return await self.query_post("CASES", source, request, {"zjhm": [request.certificate_no]})
        if source == "incidents":
            payload = {"zjhm": [request.certificate_no]}
            if request.begin_time and request.end_time:
                payload |= {
                    "begin_time": request.begin_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "end_time": request.end_time.strftime("%Y-%m-%d %H:%M:%S"),
                }
            return await self.query_post("INCIDENTS", source, request, payload)
        raise ProviderError("CONTRACT_NOT_READY", "该数据接口尚未完成正式契约配置", False, 503)

    async def query_profile(self, source: str, request: PersonQuery):
        base_url = setting("PEIXIAN_PROFILE_BASE_URL").rstrip("/")
        if not base_url:
            raise ProviderError("CONTRACT_NOT_READY", "人员档案接口尚未配置正式服务地址", False, 503)
        url = base_url + self.profile_paths[source].format(certificate_no=quote(request.certificate_no, safe=""))
        return await self.send(source, request, "GET", url, None, self.credentials("PROFILE"))

    async def query_post(self, prefix: str, source: str, request: PersonQuery, payload: dict):
        url = setting(f"PEIXIAN_{prefix}_URL")
        if not url:
            raise ProviderError("CONTRACT_NOT_READY", "该数据接口尚未配置正式服务地址", False, 503)
        payload |= {"pageStart": request.page.number, "pageSize": request.page.size}
        return await self.send(source, request, "POST", url, payload, self.credentials(prefix))

    async def send(self, source: str, request: PersonQuery, method: str, url: str, payload: dict | None, credentials):
        headers, params = credentials
        timeout = float(setting("PEIXIAN_UPSTREAM_TIMEOUT_SECONDS", "15"))
        verify = setting("PEIXIAN_UPSTREAM_CA_FILE") or True
        try:
            async with httpx.AsyncClient(timeout=timeout, verify=verify, follow_redirects=False) as client:
                response = await client.request(method, url, headers=headers, params=params, json=payload)
        except httpx.TimeoutException as error:
            raise ProviderError("UPSTREAM_TIMEOUT", "数据服务响应超时，请稍后重试", True, 504) from error
        except httpx.HTTPError as error:
            raise ProviderError("UPSTREAM_UNAVAILABLE", "数据服务暂时不可用，请稍后重试", True) from error
        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderError("UPSTREAM_REJECTED", "数据服务未能完成查询", response.status_code >= 500)
        try:
            body = response.json()
        except ValueError as error:
            raise ProviderError("UPSTREAM_INVALID_RESPONSE", "数据服务返回了无法识别的结果", True) from error
        records = body.get("data", body) if isinstance(body, dict) else body
        records = [records] if isinstance(records, dict) else records
        if not isinstance(records, list):
            raise ProviderError("UPSTREAM_INVALID_RESPONSE", "数据服务返回了无法识别的结果", True)
        mapped = [item for item in (map_record(source, item) for item in records) if item]
        total = body.get("totalCount", len(mapped)) if isinstance(body, dict) else len(mapped)
        return {"source": source_label(source), "total_count": int(total), "items": mapped, "warnings": []}

    @staticmethod
    def credentials(prefix: str):
        headers = {}
        params = {}
        if value := setting(f"PEIXIAN_{prefix}_APP_ID"):
            headers["appId"] = value
        if value := setting(f"PEIXIAN_{prefix}_APP_SECRET"):
            headers["appSecret"] = value
        if value := setting(f"PEIXIAN_{prefix}_BEARER_TOKEN"):
            headers["Authorization"] = f"Bearer {value}"
        if value := setting(f"PEIXIAN_{prefix}_API_KEY"):
            params["apikey"] = value
        return headers, params


def map_record(source: str, item):
    if not isinstance(item, dict):
        return None
    mappings = {
        "profile": {
            "name": "xm", "certificate_no": "zjhm", "household_address": "hjdz", "household_type": "hkxz",
            "household_status": "glzt", "relation_to_head": "yhzgx", "father_name": "fqxm",
            "father_certificate_no": "fqZjhm", "mother_name": "mqxm", "mother_certificate_no": "mqZjhm",
            "occupation": "zy", "source_record_id": "id",
        },
        "houses": {"source_record_id": "id", "address": "fwdz", "room_count": "fwjs", "property_type": "fwxz", "usage": "fwyt", "status": "fwzt"},
        "companies": {"source_record_id": "id", "name": "dwmc", "address": "zcdz", "telephone": "dwdh", "business_scope": "jyfw", "employee_count": "cyrs", "issued_at": "fzsj"},
        "family": {"related_name": "related_name", "related_certificate_no": "related_certificate_no", "relation": "relation", "age": "age", "collected_at": "collection_time", "data_source": "data_source"},
        "cases": {"source_record_id": "ajbh", "case_name": "ajmc", "category": "ajlb", "status": "ajzt", "occurred_at": "fxsj", "address": "ajdzmc", "summary": "jyaq", "unit": "ajsszrqmc", "person_role": "rylbms"},
        "incidents": {"source_record_id": "jjbh", "category": "bjlx", "occurred_at": "bjsj", "address": "sfdd", "summary": "bjnr", "unit": "jjdwmc", "person_role": "sjlb"},
        "disputes": {"source_record_id": "jlbh", "category": "jflx", "registered_at": "djsj", "mediation_at": "tjsj", "location": "tjdd", "result": "tjjg", "agreement": "xynr", "unit": "tjbm"},
        "tracks": {"source_record_id": "id", "captured_at": "capture_time", "track_type": "track_type_desc", "location_name": "point_notes", "device_id": "device_id", "plate_no": "plate_no"},
        "hotels": {"source_record_id": "id", "hotel_name": "lgmc", "hotel_address": "lgdz", "room_no": "rzfh", "checked_in_at": "rzsj", "checked_out_at": "tfsj"},
        "railway": {"source_record_id": "dwd_xxzjbh", "name": "xm", "train_no": "cc", "departure_station": "sfz_mc", "arrival_station": "ddz_mc", "departure_date": "fc_rq", "entered_at": "jz_sj"},
        "netbar": {"source_record_id": "id", "venue_name": "wbcsmc", "venue_address": "wbcsdz", "seat_no": "zwh", "started_at": "sjsj", "ended_at": "xjsj"},
        "motor": {"source_record_id": "id", "plate_no": "wzhphm", "plate_type": "hpzl", "vehicle_type": "cllx", "color": "csys", "vin": "clsbdh", "registered_at": "ccrq"},
        "non_motor": {"source_record_id": "id", "plate_no": "cphm", "brand": "clpp", "color": "clys", "registered_at": "spsj", "status": "clzt"},
    }
    return {target: item.get(origin) for target, origin in mappings[source].items() if item.get(origin) is not None}


def source_label(source: str):
    return {
        "profile": "人员户籍档案", "houses": "房屋信息", "companies": "单位信息", "family": "家庭关系",
        "cases": "涉案人员", "incidents": "涉警人员", "disputes": "纠纷调解", "tracks": "人员轨迹",
        "hotels": "旅馆住宿", "railway": "铁路出行", "netbar": "网吧活动", "motor": "机动车",
        "non_motor": "非机动车",
    }[source]
