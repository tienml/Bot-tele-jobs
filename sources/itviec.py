"""ITviec scraper – class ITviecSource(BaseSource).

Selectors đã xác minh trên live page (div.job-card):
  title   : h3 a
  company : a.text-rich-grey
  posted  : span.small-text (đầu tiên, dạng "Posted 4 days ago")
  role/loc: div.imt-1  (ví dụ "DevOps Engineer", "At officeHa Noi")
  tags    : a.itag
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config import HTTP_TIMEOUT, ITVIEC_QUERIES, REQUEST_DELAY
from sources.base import BaseSource, Job

log = logging.getLogger(__name__)

BASE = "https://itviec.com"
SEARCH_URL = BASE + "/it-jobs/{query}?city=ha-noi"

# ITviec đứng sau Cloudflare và chặn khá mạnh IP datacenter (GitHub Actions).
# Gửi kèm bộ header giống trình duyệt thật để giảm khả năng bị 403; nếu vẫn bị
# chặn thì đó là chặn theo IP, không phải lỗi parse.
BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "vi,en-US;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": BASE + "/it-jobs",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Chromium";v="120", "Not(A:Brand";v="24", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

_POSTED_RE = re.compile(r"(\d+)\s*(minute|hour|day|week|month)", re.I)
_CLEAN_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _CLEAN_RE.sub(" ", text or "").strip()


def _parse_posted_days(text: str) -> int | None:
    m = _POSTED_RE.search(text or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit in ("minute", "hour"):
        return 0
    if unit == "day":
        return n
    if unit == "week":
        return n * 7
    return n * 30  # month


def _parse_card(card) -> Job | None:
    title_a = card.select_one("h3 a")
    if not title_a:
        return None
    title = _clean(title_a.get_text())
    href = title_a.get("href") or ""
    if not title or not href:
        return None
    url = (urljoin(BASE, href) if href.startswith("/") else href).split("?")[0]

    company_a = card.select_one("a.text-rich-grey")
    company = _clean(company_a.get_text()) if company_a else ""

    # Ngày đăng
    posted_text = ""
    posted_date: date | None = None
    first_small = card.select_one("span.small-text")
    if first_small:
        posted_text = _clean(first_small.get_text())
        days = _parse_posted_days(posted_text)
        if days is not None:
            posted_date = date.today() - timedelta(days=days)

    # Địa điểm nằm trong div.imt-1 bắt đầu bằng "At"
    location = ""
    for div in card.select("div.imt-1"):
        txt = _clean(div.get_text())
        if txt.lower().startswith("at "):
            location = txt
            break

    tags = [_clean(a.get_text()) for a in card.select("a.itag")]
    tags = [t for t in tags if t]

    # Chuẩn hoá nhãn bổ sung ("Internship Accepted", "Fresher Accepted"…)
    # thành tags để bộ lọc intern dùng được.
    for a in card.select("a.text-reset.stretched-link"):
        txt = _clean(a.get_text())
        if txt and txt not in tags:
            tags.append(txt)

    salary = ""
    sal_el = card.select_one("span.salary-text")
    if sal_el:
        salary = _clean(sal_el.get_text())
    if "sign in" in salary.lower():
        salary = ""

    return Job(
        title=title,
        company=company,
        url=url,
        source="ITviec",
        location=location,
        salary=salary,
        tags=tags,
        posted_text=posted_text,
        posted_date=posted_date,
    )


class ITviecSource(BaseSource):
    name = "ITviec"

    def __init__(self) -> None:
        super().__init__()
        self.session.headers.update(BROWSER_HEADERS)

    def fetch(self) -> Iterable[Job]:
        jobs: list[Job] = []
        blocked = 0
        for query in ITVIEC_QUERIES:
            url = SEARCH_URL.format(query=query)
            try:
                resp = self.get(url, timeout=HTTP_TIMEOUT)
                if resp.status_code == 403:
                    # Cloudflare chặn theo IP: gặp trên runner GitHub Actions
                    # nhưng chạy ở máy nhà thì bình thường. Bỏ luôn các query
                    # còn lại vì chắc chắn cũng bị chặn, đỡ mất thời gian.
                    blocked += 1
                    log.warning(
                        "ITviec %s -> HTTP 403 (Cloudflare chặn IP, không phải lỗi parse)",
                        query,
                    )
                    if blocked >= 2:
                        log.warning(
                            "ITviec chặn IP này — bỏ qua %d query còn lại.",
                            len(ITVIEC_QUERIES) - ITVIEC_QUERIES.index(query) - 1,
                        )
                        break
                    time.sleep(REQUEST_DELAY)
                    continue
                if resp.status_code != 200:
                    log.warning("ITviec %s -> HTTP %s", query, resp.status_code)
                    continue
                soup = BeautifulSoup(resp.text, "lxml")
                cards = soup.select("div.job-card")
                found = 0
                for card in cards:
                    try:
                        job = _parse_card(card)
                    except Exception:
                        log.debug("ITviec card parse error", exc_info=True)
                        continue
                    if job:
                        jobs.append(job)
                        found += 1
                log.info("ITviec %-16s -> %d cards", query, found)
            except Exception as exc:
                log.warning("ITviec %s failed: %s", query, exc)
            time.sleep(REQUEST_DELAY)
        return jobs
