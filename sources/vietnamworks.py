"""VietnamWorks scraper – class VietnamWorksSource(BaseSource).

Dùng public JSON API: POST https://ms.vietnamworks.com/job-search/v1.0/search
  - Các query ngắn (<= 2 từ) hoạt động tốt; cụm dài trả về 0 hit.
  - Bộ lọc cityId qua body bị server bỏ qua → lọc client-side bằng
    workingLocations[].cityId == 24 (Hà Nội).
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from typing import Iterable

from config import HANOI_CITY_ID, HTTP_TIMEOUT, REQUEST_DELAY, USER_AGENT, VNW_HITS_PER_PAGE, VNW_QUERIES
from sources.base import BaseSource, Job

log = logging.getLogger(__name__)

API = "https://ms.vietnamworks.com/job-search/v1.0/search"

_EXTRA_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://www.vietnamworks.com",
    "Referer": "https://www.vietnamworks.com/",
}

_FIELDS = [
    "jobTitle", "jobUrl", "alias", "jobId", "companyName", "address",
    "workingLocations", "salaryMin", "salaryMax", "isSalaryVisible",
    "jobLevel", "jobLevelVI", "skills", "approvedOn",
    "jobDescription", "jobRequirement",
]


def _payload(query: str, page: int = 0) -> dict:
    return {
        "query": query,
        "filter": [],
        "ranges": [],
        "order": [],
        "hitsPerPage": VNW_HITS_PER_PAGE,
        "page": page,
        "retrieveFields": _FIELDS,
        "saveLog": False,
    }


def _is_hanoi(hit: dict) -> bool:
    for loc in hit.get("workingLocations") or []:
        if isinstance(loc, dict) and loc.get("cityId") == HANOI_CITY_ID:
            return True
    addr = _text(hit.get("address")).lower()
    return "hà nội" in addr or "ha noi" in addr


def _location_text(hit: dict) -> str:
    for loc in hit.get("workingLocations") or []:
        if isinstance(loc, dict) and loc.get("cityId") == HANOI_CITY_ID:
            return _text(loc.get("cityNameVI")) or _text(loc.get("cityName")) or "Hà Nội"
    return "Hà Nội"


def _text(value) -> str:
    """Ép mọi giá trị về chuỗi đã strip.

    API trả một số trường (jobLevel, companyName) dưới dạng số hoặc null tuỳ
    tin, nên gọi .strip() trực tiếp sẽ nổ AttributeError.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _num(value) -> float:
    """API có lúc trả số dưới dạng chuỗi, nên phải ép kiểu cho chắc."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _salary_text(hit: dict) -> str:
    if not hit.get("isSalaryVisible"):
        return ""
    lo = _num(hit.get("salaryMin"))
    hi = _num(hit.get("salaryMax"))
    if not lo and not hi:
        return ""
    if lo and hi:
        return f"${lo:,.0f} – ${hi:,.0f}"
    return f"${(hi or lo):,.0f}"


def _posted_date(hit: dict) -> date | None:
    raw = hit.get("approvedOn")
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).date()
    except (ValueError, TypeError):
        return None


def _tags(hit: dict) -> list[str]:
    result = []
    for skill in hit.get("skills") or []:
        if isinstance(skill, dict):
            name = skill.get("skillName") or skill.get("name") or ""
            if name:
                result.append(str(name).strip())
        elif isinstance(skill, str) and skill.strip():
            result.append(skill.strip())
    return result


def _job_url(hit: dict) -> str:
    """Lấy link tin tuyển dụng.

    API trả `jobUrl` rỗng với hầu hết kết quả, nên phải tự dựng lại link theo
    đúng định dạng của VietnamWorks: /{alias}-{jobId}-jv
    """
    url = _text(hit.get("jobUrl")).split("?")[0]
    if url:
        return url

    alias = _text(hit.get("alias")).strip("-")
    job_id = _text(hit.get("jobId"))
    if alias and job_id:
        return f"https://www.vietnamworks.com/{alias}-{job_id}-jv"
    return ""


def _to_job(hit: dict) -> Job | None:
    title = _text(hit.get("jobTitle"))
    url = _job_url(hit)
    if not title or not url:
        return None

    # posted_text ← level field (e.g. "Thực tập sinh", "Mới tốt nghiệp")
    # bộ lọc intern dùng trường này để nhận diện.
    level_vi = _text(hit.get("jobLevelVI")) or _text(hit.get("jobLevel"))

    return Job(
        title=title,
        company=_text(hit.get("companyName")),
        url=url,
        source="VietnamWorks",
        location=_location_text(hit),
        salary=_salary_text(hit),
        tags=_tags(hit),
        posted_text=level_vi,
        posted_date=_posted_date(hit),
    )


class VietnamWorksSource(BaseSource):
    name = "VietnamWorks"

    def __init__(self) -> None:
        super().__init__()
        self.session.headers.update(_EXTRA_HEADERS)

    def fetch(self) -> Iterable[Job]:
        jobs: list[Job] = []
        for query in VNW_QUERIES:
            total_hits = 0
            found = 0
            page = 0
            # Paginate through all available pages
            while page < 5:  # Max 5 pages to avoid runaway loops
                try:
                    resp = self.session.post(
                        API, json=_payload(query, page), timeout=HTTP_TIMEOUT
                    )
                    if resp.status_code != 200:
                        log.warning("VNW %r p%d -> HTTP %s", query, page, resp.status_code)
                        break
                    data = resp.json()
                    hits = data.get("data") or []
                    if not hits:
                        break
                    total_hits += len(hits)
                    for hit in hits:
                        if not _is_hanoi(hit):
                            continue
                        try:
                            job = _to_job(hit)
                        except Exception:
                            # Trước đây dùng log.debug nên lỗi parse bị ẩn hoàn
                            # toàn: mọi hit fail mà log vẫn báo "0 HN" như thể
                            # không có job nào ở Hà Nội.
                            log.warning(
                                "VNW parse lỗi ở job %r", hit.get("jobTitle"),
                                exc_info=True,
                            )
                            continue
                        if job:
                            jobs.append(job)
                            found += 1
                    page += 1
                    time.sleep(REQUEST_DELAY)
                except Exception as exc:
                    log.warning("VNW %r p%d failed: %s", query, page, exc)
                    break
            log.info("VNW %-16r -> %d hits (%d pages), %d HN", query, total_hits, page, found)
        return jobs
