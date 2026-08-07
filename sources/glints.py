"""Nguồn Glints Việt Nam.

Glints là site Next.js: toàn bộ danh sách job nằm trong thẻ
<script id="__NEXT_DATA__"> dưới dạng JSON, nên không cần parse HTML.

Hai điểm cần lưu ý:
- Tham số địa điểm trên URL bị Glints bỏ qua (queryVariableData chỉ giữ
  SearchTerm + CountryCode), nên phải tự lọc Hà Nội ở phía client.
- Trường `city` luôn null; tỉnh/thành nằm trong location.parents[].
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from typing import Iterable

from bs4 import BeautifulSoup

from config import GLINTS_PAGES, GLINTS_QUERIES, REQUEST_DELAY
from sources.base import BaseSource, Job

log = logging.getLogger(__name__)

BASE_URL = "https://glints.com/vn/opportunities/jobs/explore"


class GlintsSource(BaseSource):
    name = "Glints"

    def fetch(self) -> Iterable[Job]:
        jobs: list[Job] = []
        seen_ids: set[str] = set()

        for query in GLINTS_QUERIES:
            for page in range(1, GLINTS_PAGES + 1):
                try:
                    raw_jobs = self._fetch_page(query, page)
                except Exception as exc:
                    log.warning("Glints '%s' trang %d lỗi: %s", query, page, exc)
                    break

                if not raw_jobs:
                    break

                for raw in raw_jobs:
                    job_id = str(raw.get("id") or "")
                    if not job_id or job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)
                    job = self._parse(raw)
                    if job:
                        jobs.append(job)

                time.sleep(REQUEST_DELAY)

        log.info("Glints: lấy được %d job", len(jobs))
        return jobs

    def _fetch_page(self, query: str, page: int) -> list[dict]:
        """Lấy một trang kết quả, trả về list job thô từ __NEXT_DATA__."""
        params = {"keyword": query, "country": "VN", "page": page}
        resp = self.get(BASE_URL, params=params)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        tag = soup.find("script", id="__NEXT_DATA__")
        if not tag or not tag.string:
            return []

        data = json.loads(tag.string)
        page_props = data.get("props", {}).get("pageProps", {})
        initial = page_props.get("initialJobs") or {}
        return initial.get("jobsInPage") or []

    # --- Chuyển dữ liệu thô sang Job -------------------------------------

    def _parse(self, raw: dict) -> Job | None:
        title = (raw.get("title") or "").strip()
        job_id = str(raw.get("id") or "")
        if not title or not job_id:
            return None

        location = self._location(raw)
        # Không có thông tin địa điểm thì bỏ, vì Glints trả cả nước.
        if not location:
            return None

        company = raw.get("company") or {}
        company_name = (
            company.get("name") or company.get("brandName") or ""
        ).strip()

        slug = self._slug(title)
        url = f"https://glints.com/vn/opportunities/jobs/{slug}/{job_id}"

        tags = [
            s["skill"]["name"]
            for s in (raw.get("skills") or [])
            if isinstance(s, dict) and (s.get("skill") or {}).get("name")
        ]
        # Loại job (INTERNSHIP/FULL_TIME) là tín hiệu cấp bậc quan trọng,
        # đưa vào tags để filters.py nhìn thấy.
        job_type = (raw.get("type") or "").replace("_", " ").lower()
        if job_type:
            tags.append(job_type)

        posted_date = self._posted_date(raw.get("createdAt"))

        return Job(
            title=title,
            company=company_name,
            url=url,
            source=self.name,
            location=location,
            salary=self._salary(raw.get("salaries")),
            tags=tags,
            posted_text=raw.get("createdAt") or "",
            posted_date=posted_date,
        )

    @staticmethod
    def _location(raw: dict) -> str:
        """Ghép tên địa điểm + toàn bộ cấp cha (quận > tỉnh > quốc gia).

        `city` luôn null nên phải lần theo location.parents để biết tỉnh.
        """
        loc = raw.get("location") or {}
        parts = [loc.get("name") or ""]
        for parent in loc.get("parents") or []:
            if isinstance(parent, dict) and parent.get("name"):
                parts.append(parent["name"])
        return ", ".join(p for p in parts if p)

    @staticmethod
    def _slug(title: str) -> str:
        """Tạo slug từ tiêu đề. Glints chỉ dùng ID để định tuyến nên slug
        không cần khớp tuyệt đối, chỉ cần hợp lệ."""
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()
        return slug or "job"

    @staticmethod
    def _salary(salaries) -> str:
        """Lấy khoảng lương đầu tiên nếu tin có công khai."""
        if not salaries or not isinstance(salaries, list):
            return ""
        for item in salaries:
            if not isinstance(item, dict):
                continue
            lo, hi = item.get("minAmount"), item.get("maxAmount")
            cur = item.get("CurrencyCode") or item.get("currencyCode") or "VND"
            mode = (item.get("salaryMode") or "").lower()
            unit = "/tháng" if "month" in mode else ""
            if lo and hi:
                return f"{int(lo):,} - {int(hi):,} {cur}{unit}"
            if lo:
                return f"Từ {int(lo):,} {cur}{unit}"
        return ""

    @staticmethod
    def _posted_date(created_at):
        """Đổi createdAt (ISO 8601) sang date."""
        if not created_at:
            return None
        try:
            text = str(created_at).replace("Z", "+00:00")
            return datetime.fromisoformat(text).date()
        except ValueError:
            return None
