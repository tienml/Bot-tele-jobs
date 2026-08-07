"""TopDev scraper – class TopDevSource(BaseSource).

TopDev dùng Next.js và nhúng dữ liệu vào <script id="__NEXT_DATA__">.
Scraper đọc JSON này để lấy danh sách job mà không cần gọi API riêng.

URL tìm kiếm: https://topdev.vn/it-jobs/{query}?city=ha-noi
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime, timezone
from typing import Iterable

from bs4 import BeautifulSoup

from config import HTTP_TIMEOUT, REQUEST_DELAY
from sources.base import BaseSource, Job

log = logging.getLogger(__name__)

BASE = "https://topdev.vn"
SEARCH_URL = BASE + "/it-jobs/{query}?city=ha-noi"

QUERIES = ["intern", "devops", "java", "data-engineer"]

_CLEAN = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _CLEAN.sub(" ", str(text or "")).strip()


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw[:26], fmt[:len(raw)])
            return dt.replace(tzinfo=timezone.utc).date()
        except ValueError:
            continue
    # Fallback: parse ISO with fromisoformat
    try:
        raw_clean = raw[:19]  # trim microseconds/tz
        return datetime.fromisoformat(raw_clean).date()
    except Exception:
        return None


def _job_url(item: dict) -> str:
    """Tạo URL job từ alias/slug hoặc id."""
    # TopDev URL pattern: /it-jobs/{slug}-{id}
    alias = _clean(item.get("alias") or item.get("slug") or "")
    job_id = item.get("id") or item.get("jobId") or ""
    if alias and job_id:
        return f"{BASE}/it-jobs/{alias}-{job_id}"
    if alias:
        return f"{BASE}/it-jobs/{alias}"
    return ""


def _extract_jobs(data: dict) -> list[dict]:
    """Trích xuất mảng job từ __NEXT_DATA__ theo nhiều path dự phòng."""
    candidates = []

    def _try(accessor):
        try:
            result = accessor(data)
            if isinstance(result, list) and result:
                candidates.extend(result)
        except (KeyError, TypeError, IndexError):
            pass

    page_props = data.get("props", {}).get("pageProps", {})

    # Các path phổ biến tuỳ phiên bản Next.js của TopDev
    _try(lambda d: page_props["jobs"]["data"])
    _try(lambda d: page_props["jobs"]["collection"])
    _try(lambda d: page_props["initialData"]["jobs"]["data"])
    _try(lambda d: page_props["dehydratedState"]["queries"][0]["state"]["data"]["data"])

    # Tìm bất kỳ mảng nào có phần tử chứa "title" và "company"
    if not candidates:
        def _deep_search(obj, depth=0):
            if depth > 8:
                return
            if isinstance(obj, list) and len(obj) > 0:
                first = obj[0]
                if isinstance(first, dict) and "title" in first:
                    candidates.extend(obj)
                    return
            if isinstance(obj, dict):
                for v in obj.values():
                    _deep_search(v, depth + 1)
        _deep_search(data)

    return candidates


def _to_job(item: dict) -> Job | None:
    title = _clean(item.get("title") or item.get("name") or "")
    if not title:
        return None

    # Company
    company_raw = item.get("company") or {}
    if isinstance(company_raw, dict):
        company = _clean(company_raw.get("name") or company_raw.get("shortName") or "")
    else:
        company = _clean(company_raw)

    # URL
    url = _clean(item.get("url") or item.get("href") or "")
    if not url:
        url = _job_url(item)
    if not url:
        return None
    if url.startswith("/"):
        url = BASE + url

    # Location
    locations = item.get("addresses") or item.get("workingLocation") or []
    if isinstance(locations, list):
        loc_parts = []
        for loc in locations:
            if isinstance(loc, dict):
                loc_parts.append(_clean(loc.get("label") or loc.get("city") or ""))
            elif isinstance(loc, str):
                loc_parts.append(_clean(loc))
        location = ", ".join(p for p in loc_parts if p)
    elif isinstance(locations, str):
        location = _clean(locations)
    else:
        location = ""

    if not location:
        location = _clean(item.get("location") or item.get("locationVI") or "")

    # Skills/tags
    skills_raw = item.get("skills") or item.get("tags") or []
    tags: list[str] = []
    for s in skills_raw:
        if isinstance(s, dict):
            name = _clean(s.get("name") or s.get("skillName") or "")
            if name:
                tags.append(name)
        elif isinstance(s, str) and s.strip():
            tags.append(s.strip())

    # Salary
    sal = item.get("salary") or {}
    salary = ""
    if isinstance(sal, dict):
        lo = sal.get("min") or 0
        hi = sal.get("max") or 0
        if sal.get("negotiable"):
            salary = "Thỏa thuận"
        elif lo or hi:
            salary = f"${lo:,}–${hi:,}" if lo and hi else f"${(hi or lo):,}"
    elif isinstance(sal, str) and sal.strip():
        salary = sal.strip()

    # Date
    posted_date = _parse_date(
        item.get("publishedAt") or item.get("createdAt") or item.get("updatedAt")
    )

    # Level text (để filter intern nhận ra)
    level = _clean(
        item.get("level") or item.get("jobLevel") or
        item.get("shortDescription") or ""
    )

    return Job(
        title=title,
        company=company,
        url=url,
        source="TopDev",
        location=location,
        salary=salary,
        tags=tags,
        posted_text=level,
        posted_date=posted_date,
    )


class TopDevSource(BaseSource):
    name = "TopDev"

    _EXTRA_HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://topdev.vn/",
    }

    def __init__(self) -> None:
        super().__init__()
        self.session.headers.update(self._EXTRA_HEADERS)

    def fetch(self) -> Iterable[Job]:
        jobs: list[Job] = []
        for query in QUERIES:
            url = SEARCH_URL.format(query=query)
            try:
                resp = self.get(url, timeout=HTTP_TIMEOUT)
                if resp.status_code != 200:
                    log.warning("TopDev %s -> HTTP %s", query, resp.status_code)
                    time.sleep(REQUEST_DELAY)
                    continue

                soup = BeautifulSoup(resp.text, "lxml")
                script = soup.find("script", id="__NEXT_DATA__")
                if not script or not script.string:
                    log.warning("TopDev %s: __NEXT_DATA__ không tìm thấy", query)
                    time.sleep(REQUEST_DELAY)
                    continue

                next_data = json.loads(script.string)
                items = _extract_jobs(next_data)
                found = 0
                for item in items:
                    try:
                        job = _to_job(item)
                    except Exception:
                        log.debug("TopDev parse error", exc_info=True)
                        continue
                    if job:
                        jobs.append(job)
                        found += 1

                log.info("TopDev %-16s -> %d jobs", query, found)

            except json.JSONDecodeError as exc:
                log.warning("TopDev %s: JSON lỗi – %s", query, exc)
            except Exception as exc:
                log.warning("TopDev %s failed: %s", query, exc)

            time.sleep(REQUEST_DELAY)

        return jobs
