"""TopCV scraper – class TopCVSource(BaseSource).

TopCV cũng dùng Next.js, đọc __NEXT_DATA__ từ trang search.
URL tìm kiếm: https://www.topcv.vn/viec-lam-it?keyword={query}&city_id=1

city_id=1 = Hà Nội trên TopCV.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime, timezone
from typing import Iterable
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from config import HTTP_TIMEOUT, REQUEST_DELAY
from sources.base import BaseSource, Job

log = logging.getLogger(__name__)

BASE = "https://www.topcv.vn"
SEARCH_URL = BASE + "/viec-lam-it?keyword={query}&city_id=1"

QUERIES = ["intern", "thực tập devops", "intern java", "intern data engineer"]

_CLEAN = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _CLEAN.sub(" ", str(text or "")).strip()


def _parse_date(raw) -> date | None:
    if not raw:
        return None
    if isinstance(raw, (int, float)):
        # Unix timestamp
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc).date()
        except Exception:
            return None
    if isinstance(raw, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw[:19], fmt[:len(raw[:19])]).date()
            except ValueError:
                continue
    return None


def _extract_jobs(data: dict) -> list[dict]:
    """Trích job từ __NEXT_DATA__ của TopCV."""
    candidates = []

    def _try(accessor):
        try:
            result = accessor(data)
            if isinstance(result, list) and result:
                candidates.extend(result)
        except (KeyError, TypeError, IndexError):
            pass

    page_props = data.get("props", {}).get("pageProps", {})

    _try(lambda d: page_props["jobs"]["data"])
    _try(lambda d: page_props["listJobs"]["data"])
    _try(lambda d: page_props["initialData"]["data"])
    _try(lambda d: page_props["data"]["jobs"])
    _try(lambda d: page_props["serverData"]["jobs"]["data"])

    if not candidates:
        def _deep_search(obj, depth=0):
            if depth > 8:
                return
            if isinstance(obj, list) and obj:
                first = obj[0]
                if isinstance(first, dict) and (
                    "title" in first or "job_name" in first or "name" in first
                ):
                    candidates.extend(obj)
                    return
            if isinstance(obj, dict):
                for v in obj.values():
                    _deep_search(v, depth + 1)
        _deep_search(data)

    return candidates


def _to_job(item: dict) -> Job | None:
    # TopCV có thể dùng "title" hoặc "job_name"
    title = _clean(
        item.get("title") or item.get("job_name") or item.get("name") or ""
    )
    if not title:
        return None

    # Company
    comp = item.get("company") or {}
    if isinstance(comp, dict):
        company = _clean(comp.get("name") or comp.get("company_name") or "")
    else:
        company = _clean(item.get("company_name") or str(comp))

    # URL
    url = _clean(item.get("url") or item.get("job_url") or item.get("href") or "")
    if not url:
        slug = item.get("alias") or item.get("slug") or ""
        job_id = item.get("id") or item.get("job_id") or ""
        if slug:
            url = f"{BASE}/{slug}"
        elif job_id:
            url = f"{BASE}/viec-lam/{job_id}"
    if not url:
        return None
    if url.startswith("/"):
        url = BASE + url

    # Location
    location = ""
    loc_list = item.get("working_address") or item.get("locations") or []
    if isinstance(loc_list, list):
        parts = []
        for loc in loc_list:
            if isinstance(loc, dict):
                parts.append(_clean(loc.get("name") or loc.get("city") or ""))
            elif isinstance(loc, str):
                parts.append(_clean(loc))
        location = ", ".join(p for p in parts if p)
    elif isinstance(loc_list, str):
        location = _clean(loc_list)

    if not location:
        location = _clean(item.get("location") or item.get("city") or "Hà Nội")

    # Tags/skills
    tags: list[str] = []
    for field in ("skills", "tags", "categories"):
        raw = item.get(field) or []
        for s in raw:
            if isinstance(s, dict):
                name = _clean(s.get("name") or s.get("skill_name") or "")
                if name:
                    tags.append(name)
            elif isinstance(s, str) and s.strip():
                tags.append(s.strip())

    # Salary
    salary = _clean(item.get("salary") or item.get("salary_range") or "")

    # Date
    posted_date = _parse_date(
        item.get("updated_at") or item.get("created_at") or
        item.get("published_at") or item.get("expired_at")
    )

    # Level — để bộ lọc nhận ra intern
    level = _clean(
        item.get("job_level") or item.get("level") or
        item.get("rank_name") or ""
    )

    return Job(
        title=title,
        company=company,
        url=url,
        source="TopCV",
        location=location,
        salary=salary,
        tags=tags,
        posted_text=level,
        posted_date=posted_date,
    )


def _scrape_html_cards(soup: BeautifulSoup) -> list[Job]:
    """Fallback: đọc job card từ HTML nếu __NEXT_DATA__ không có."""
    jobs = []
    # TopCV card selectors (có thể thay đổi theo phiên bản)
    for card in soup.select("div.job-item-search-result, div.job-item, article.job-item"):
        try:
            title_el = card.select_one("h3 a, h2 a, .title a")
            if not title_el:
                continue
            title = _clean(title_el.get_text())
            href = title_el.get("href") or ""
            if not title or not href:
                continue
            url = urljoin(BASE, href).split("?")[0]

            company_el = card.select_one(".company a, .company-name, .employer-name")
            company = _clean(company_el.get_text()) if company_el else ""

            loc_el = card.select_one(".address, .location, .city")
            location = _clean(loc_el.get_text()) if loc_el else "Hà Nội"

            tags = [
                _clean(a.get_text())
                for a in card.select(".tag, .skill-tag, .label")
                if _clean(a.get_text())
            ]

            salary_el = card.select_one(".salary, .salary-text")
            salary = _clean(salary_el.get_text()) if salary_el else ""

            jobs.append(Job(
                title=title, company=company, url=url, source="TopCV",
                location=location, salary=salary, tags=tags,
            ))
        except Exception:
            log.debug("TopCV HTML card error", exc_info=True)
    return jobs


class TopCVSource(BaseSource):
    name = "TopCV"

    _EXTRA_HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
        "Referer": "https://www.topcv.vn/",
    }

    def __init__(self) -> None:
        super().__init__()
        self.session.headers.update(self._EXTRA_HEADERS)

    def fetch(self) -> Iterable[Job]:
        jobs: list[Job] = []
        for query in QUERIES:
            url = SEARCH_URL.format(query=quote_plus(query))
            try:
                resp = self.get(url, timeout=HTTP_TIMEOUT)
                if resp.status_code != 200:
                    log.warning("TopCV %r -> HTTP %s", query, resp.status_code)
                    time.sleep(REQUEST_DELAY)
                    continue

                soup = BeautifulSoup(resp.text, "lxml")
                script = soup.find("script", id="__NEXT_DATA__")

                found = 0
                if script and script.string:
                    try:
                        next_data = json.loads(script.string)
                        items = _extract_jobs(next_data)
                        for item in items:
                            try:
                                job = _to_job(item)
                            except Exception:
                                log.debug("TopCV item parse error", exc_info=True)
                                continue
                            if job:
                                jobs.append(job)
                                found += 1
                    except json.JSONDecodeError:
                        log.warning("TopCV %r: JSON decode failed, thử HTML", query)

                # Nếu __NEXT_DATA__ không trả về gì, thử HTML
                if found == 0:
                    html_jobs = _scrape_html_cards(soup)
                    jobs.extend(html_jobs)
                    found = len(html_jobs)

                log.info("TopCV %-20r -> %d jobs", query, found)

            except Exception as exc:
                log.warning("TopCV %r failed: %s", query, exc)

            time.sleep(REQUEST_DELAY)

        return jobs
