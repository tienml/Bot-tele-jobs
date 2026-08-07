"""Nguồn LinkedIn Jobs (không cần API, không cần đăng nhập).

LinkedIn có một endpoint riêng phục vụ khách chưa đăng nhập:

    /jobs-guest/jobs/api/seeMoreJobPostings/search

Endpoint này trả về HTML thuần gồm danh sách <li> card job, mỗi lần 10 tin,
phân trang bằng tham số `start`. Nhờ vậy không vướng authwall như trang
/jobs/search thông thường và không cần token gì cả.

Lưu ý về bộ lọc phía LinkedIn:
- `f_TPR=r2592000` (tin trong 30 ngày) hoạt động — kết quả đổi rõ rệt.
- `f_E` (cấp bậc) và `f_JT=I` (loại hình internship) LinkedIn *bỏ qua*
  ở endpoint guest: đã thử và kết quả không đổi. Nên cấp bậc vẫn phải lọc
  ở filters.py như các nguồn khác.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Iterable
from urllib.parse import urlparse, urlunparse

from bs4 import BeautifulSoup

from config import (
    LINKEDIN_LOCATION,
    LINKEDIN_PAGES,
    LINKEDIN_QUERIES,
    LINKEDIN_TPR,
    REQUEST_DELAY,
)
from sources.base import BaseSource, Job

log = logging.getLogger(__name__)

API = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

_EXTRA_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
    # Thiếu Referer, LinkedIn có lúc trả rỗng cho endpoint guest.
    "Referer": "https://www.linkedin.com/jobs/search",
    "X-Requested-With": "XMLHttpRequest",
}


def _clean_url(raw: str) -> str:
    """Bỏ query string tracking của LinkedIn (position, refId, trackingId...).

    Các tham số này đổi mỗi lần request nên nếu giữ lại thì `job_id` sẽ khác
    nhau giữa các lần chạy và cơ chế chống gửi trùng mất tác dụng.
    """
    if not raw:
        return ""
    parts = urlparse(raw)
    return urlunparse((parts.scheme, parts.netloc, parts.path, "", "", ""))


def _posted_date(time_tag) -> date | None:
    """Lấy ngày đăng từ thuộc tính datetime của thẻ <time>."""
    if not time_tag:
        return None
    raw = (time_tag.get("datetime") or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _text(node) -> str:
    return node.get_text(strip=True) if node else ""


class LinkedInSource(BaseSource):
    name = "LinkedIn"

    def __init__(self) -> None:
        super().__init__()
        self.session.headers.update(_EXTRA_HEADERS)

    def fetch(self) -> Iterable[Job]:
        jobs: list[Job] = []
        seen_urls: set[str] = set()

        for query in LINKEDIN_QUERIES:
            found = 0
            for page in range(LINKEDIN_PAGES):
                try:
                    cards = self._fetch_page(query, page * 10)
                except Exception as exc:
                    log.warning("LinkedIn %r trang %d lỗi: %s", query, page, exc)
                    break

                if not cards:
                    break

                for card in cards:
                    job = self._parse(card)
                    if not job or job.url in seen_urls:
                        continue
                    seen_urls.add(job.url)
                    jobs.append(job)
                    found += 1

                time.sleep(REQUEST_DELAY)

            log.info("LinkedIn %-22r -> %d tin", query, found)

        log.info("LinkedIn: lấy được %d job", len(jobs))
        return jobs

    def _fetch_page(self, query: str, start: int) -> list:
        params = {
            "keywords": query,
            "location": LINKEDIN_LOCATION,
            "start": start,
            "f_TPR": LINKEDIN_TPR,
        }
        resp = self.get(API, params=params)
        if resp.status_code != 200:
            log.warning("LinkedIn %r start=%d -> HTTP %s", query, start, resp.status_code)
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        return soup.find_all("li")

    def _parse(self, card) -> Job | None:
        title = _text(card.select_one("h3.base-search-card__title"))
        link = card.select_one("a.base-card__full-link")
        url = _clean_url(link.get("href") if link else "")
        if not title or not url:
            return None

        return Job(
            title=title,
            company=_text(card.select_one("h4.base-search-card__subtitle")),
            url=url,
            source=self.name,
            location=_text(card.select_one("span.job-search-card__location")),
            salary="",  # endpoint guest không trả lương
            tags=[],    # cũng không trả skill; filters.py chỉ dựa vào tiêu đề
            posted_text=_text(card.select_one("time.job-search-card__listdate")),
            posted_date=_posted_date(card.select_one("time.job-search-card__listdate")),
        )
