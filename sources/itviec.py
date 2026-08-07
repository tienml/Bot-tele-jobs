"""ITviec scraper – class ITviecSource(BaseSource).

ITviec đứng sau Cloudflare và chặn IP datacenter: gọi thẳng bằng
`requests` từ runner GitHub Actions luôn trả 403, dù cùng đoạn code chạy
ở máy nhà vẫn ra đủ tin. Thêm header giống trình duyệt không cứu được,
vì Cloudflare không chỉ đọc header.

Nó còn nhận dạng client qua *TLS fingerprint* (JA3/JA4) và cách dựng
HTTP/2. OpenSSL của Python có fingerprint riêng, khác Chrome, nên chỉ
cần nhìn cái bắt tay TLS là biết không phải trình duyệt. Vì vậy nguồn
này thử ba đường, dừng ở đường nào chạy được:

  1. TLS giả lập Chrome (curl_cffi) — qua được vì fingerprint trùng
     Chrome thật. Đường chính, dùng luôn HTML gốc của ITviec.
  2. Gọi trực tiếp bằng requests — nhanh nhất, chạy tốt ở máy nhà.
  3. Reader r.jina.ai — họ tự mở trang bằng trình duyệt thật rồi trả
     markdown, nên Cloudflare xảy ra ở phía họ. Có hạn mức cho IP không
     token, gọi dồn dập là bị chặn.

Các hướng đã thử và tắc:
  - html.duckduckgo.com -> HTTP 202 (chặn bot)
  - lite.duckduckgo.com -> 200 nhưng chỉ ra trang danh sách, không ra tin
  - Google / Bing       -> cần JS / trả captcha

Markdown reader trả về có cấu trúc đều, mỗi tin một khối:

     Posted 4 days ago
    ### [DevOps Intern](https://itviec.com/it-jobs/devops-intern-fpt-is-5207?...)
    [![Image 33: FPT IS Vietnam Small Logo](...)](https://itviec.com/companies/fpt-is)
    [Sign in to view salary](https://itviec.com/sign_in?job=devops-intern-fpt-is-5207...)
    [Internship Accepted](https://itviec.com/it-jobs/internship-accepted?click_source=Skill+tag)
    [Fullstack Developer](https://itviec.com/it-jobs/fullstack-developer "Fullstack Developer")
     At office
     Ha Noi
    [DevOps](https://itviec.com/it-jobs/devops?click_source=Skill+tag)[English](...)
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta
from typing import Iterable
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from config import (
    HTTP_TIMEOUT,
    ITVIEC_IMPERSONATE,
    ITVIEC_QUERIES,
    ITVIEC_READER_TIMEOUT,
    REQUEST_DELAY,
)
from sources.base import BaseSource, Job

# curl_cffi là thư viện phụ: thiếu nó thì nguồn vẫn chạy bằng hai đường
# còn lại, chỉ kém hiệu quả trên CI.
try:
    from curl_cffi import requests as curl_requests
except ImportError:  # pragma: no cover
    curl_requests = None

log = logging.getLogger(__name__)

BASE = "https://itviec.com"
SEARCH_URL = BASE + "/it-jobs/{query}?city=ha-noi"
READER_URL = "https://r.jina.ai/{target}"

# Header giống trình duyệt thật, dùng cho đường gọi trực tiếp.
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

READER_HEADERS = {
    "Accept": "text/plain",
    # Không lấy bản cache của reader: tin tuyển dụng cần đúng ngày đăng.
    "X-No-Cache": "true",
}

_POSTED_RE = re.compile(r"(\d+)\s*(minute|hour|day|week|month)", re.I)
_CLEAN_RE = re.compile(r"\s+")

# --- Regex cho markdown của reader ---------------------------------------
# Tiêu đề tin: dòng h3 chứa link tới trang chi tiết. Bám đúng ba dấu # —
# trang tìm kiếm còn có khung xem trước ở cột phải dùng h2 và lặp lại tin
# đầu tiên, nếu nhận cả h2 thì tin đó bị đếm hai lần.
_MD_HEADING_RE = re.compile(
    r"^###\s*\[(?P<title>.+?)\]\((?P<url>https://itviec\.com/it-jobs/[^\s\)]+)\)",
)
# Tên công ty nằm trong alt của logo: "FPT IS Vietnam Small Logo".
_MD_COMPANY_RE = re.compile(
    r"!\[Image \d+:\s*(?P<name>.+?)\s+(?:Vietnam\s+)?(?:Small|Big)\s+Logo\]",
)
# Dự phòng khi alt logo thiếu: lấy slug từ link trang công ty.
_MD_COMPANY_LINK_RE = re.compile(r"\]\(https://itviec\.com/companies/([a-z0-9\-]+)")
# Tag kỹ năng và nhãn "Internship Accepted" đều mang click_source=Skill+tag.
_MD_SKILL_RE = re.compile(
    r"\[(?P<tag>[^\]\[]+?)\]\(https://itviec\.com/it-jobs/[^\)]*click_source=Skill\+tag[^\)]*\)",
)
# Nhóm vị trí ("DevOps Engineer") — link kèm title, không có click_source.
_MD_ROLE_RE = re.compile(
    r"\[(?P<role>[^\]\[]+?)\]\(https://itviec\.com/it-jobs/[^\s\)]+\s+\"(?P=role)\"\)",
)
_MD_SALARY_RE = re.compile(r"^\s*\[?\s*(\$[\d,\.]+\s*-\s*\$[\d,\.]+)", re.M)

# Dòng trơn (không markdown) trong khối tin: hình thức làm việc, địa điểm,
# nhãn nổi bật. Cần biết cái nào là cái nào để không nhét badge vào địa điểm.
_WORK_TYPES = {"at office", "hybrid", "remote", "wfh"}
_BADGES = {"hot", "super hot", "new", "no results found"}


def _clean(text: str) -> str:
    return _CLEAN_RE.sub(" ", text or "").strip()


def _strip_query(url: str) -> str:
    """Bỏ query string — ITviec gắn tham số tracking đổi theo từng request."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


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


def _posted_to_date(text: str) -> date | None:
    days = _parse_posted_days(text)
    return None if days is None else date.today() - timedelta(days=days)


# --- Parser cho markdown của reader --------------------------------------
def _parse_markdown(text: str) -> list[Job]:
    """Tách các tin từ markdown reader trả về.

    Mỗi tin bắt đầu ở dòng h3 chứa link tới trang chi tiết; các dòng nằm
    giữa hai h3 là thông tin của tin phía trước. Dòng "Posted x days ago"
    lại nằm NGAY TRƯỚC h3, nên phải nhớ dòng posted gần nhất.
    """
    lines = text.split("\n")

    # Chỉ số các dòng h3 mở đầu mỗi tin.
    starts = [i for i, line in enumerate(lines) if _MD_HEADING_RE.match(line)]
    if not starts:
        return []

    jobs: list[Job] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        head = _MD_HEADING_RE.match(lines[start])
        title = _clean(head.group("title"))
        url = _strip_query(head.group("url"))
        if not title or not url:
            continue

        # Ngày đăng nằm ở các dòng trước h3, sau khối của tin trước đó.
        prev_end = starts[idx - 1] if idx else 0
        posted_text = ""
        for line in reversed(lines[prev_end:start]):
            stripped = _clean(line)
            if stripped.lower().startswith("posted "):
                posted_text = stripped
                break

        block = "\n".join(lines[start:end])

        company = ""
        m = _MD_COMPANY_RE.search(block)
        if m:
            company = _clean(m.group("name"))
        else:
            m = _MD_COMPANY_LINK_RE.search(block)
            if m:
                # Slug không có dấu và viết hoa, nhưng vẫn nhận diện được
                # công ty — đủ dùng cho việc gộp tin trùng.
                company = m.group(1).replace("-", " ").title()

        # Reader ghi nguyên chữ "Vietnam" vào alt logo của mọi công ty.
        if company.endswith(" Vietnam"):
            company = company[: -len(" Vietnam")].strip()

        tags = []
        for tag in _MD_SKILL_RE.findall(block):
            tag = _clean(tag)
            if tag and tag not in tags:
                tags.append(tag)
        for role in _MD_ROLE_RE.findall(block):
            role = _clean(role)
            if role and role not in tags:
                tags.append(role)

        # Địa điểm và hình thức làm việc là các dòng trơn trong khối.
        location = ""
        work_type = ""
        for line in lines[start:end]:
            stripped = _clean(line)
            if not stripped or "[" in stripped or "]" in stripped:
                continue
            low = stripped.lower()
            if low in _WORK_TYPES:
                work_type = stripped
            elif low in _BADGES or low.startswith("posted ") or low.startswith("+"):
                continue
            elif not location and re.fullmatch(r"[A-Za-zÀ-ỹ\s\-]{3,40}", stripped):
                # "Ha Noi", "Ho Chi Minh - Ha Noi"…
                location = stripped
        if work_type and location:
            location = f"{work_type} {location}"
        elif work_type:
            location = work_type

        salary = ""
        m = _MD_SALARY_RE.search(block)
        if m:
            salary = _clean(m.group(1))

        jobs.append(Job(
            title=title,
            company=company,
            url=url,
            source="ITviec",
            location=location,
            salary=salary,
            tags=tags,
            posted_text=posted_text,
            posted_date=_posted_to_date(posted_text),
        ))
    return jobs


# --- Parser cho HTML gốc (đường gọi trực tiếp) ---------------------------
def _parse_card(card) -> Job | None:
    """Parse một div.job-card từ HTML gốc của ITviec.

    Selector đã xác minh trên live page:
      title h3 a · company a.text-rich-grey · posted span.small-text
      location div.imt-1 bắt đầu bằng "At" · tags a.itag
    """
    title_a = card.select_one("h3 a")
    if not title_a:
        return None
    title = _clean(title_a.get_text())
    href = title_a.get("href") or ""
    if not title or not href:
        return None
    url = _strip_query(urljoin(BASE, href) if href.startswith("/") else href)

    company_a = card.select_one("a.text-rich-grey")
    company = _clean(company_a.get_text()) if company_a else ""

    posted_text = ""
    first_small = card.select_one("span.small-text")
    if first_small:
        posted_text = _clean(first_small.get_text())

    location = ""
    for div in card.select("div.imt-1"):
        txt = _clean(div.get_text())
        if txt.lower().startswith("at "):
            location = txt
            break

    tags = [t for t in (_clean(a.get_text()) for a in card.select("a.itag")) if t]

    # Nhãn bổ sung ("Internship Accepted", "Fresher Accepted"…) cũng đưa vào
    # tags để bộ lọc intern dùng được.
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
        posted_date=_posted_to_date(posted_text),
    )


def _parse_html(html: str) -> list[Job]:
    """Tách các tin từ HTML gốc của trang tìm kiếm ITviec."""
    soup = BeautifulSoup(html, "lxml")
    jobs: list[Job] = []
    for card in soup.select("div.job-card"):
        try:
            job = _parse_card(card)
        except Exception:
            log.debug("ITviec: lỗi parse job-card", exc_info=True)
            continue
        if job:
            jobs.append(job)
    return jobs


class ITviecSource(BaseSource):
    """Ba đường lấy dữ liệu, chuyển đường khi bị Cloudflare chặn.

    Thứ tự: TLS giả lập Chrome → requests trực tiếp → reader r.jina.ai.
    Đường nào chặn thì bỏ hẳn cho các query còn lại, đỡ mất thời gian
    gọi những request chắc chắn 403.
    """

    name = "ITviec"

    def __init__(self) -> None:
        super().__init__()
        self.session.headers.update(BROWSER_HEADERS)

    # --- Ba đường lấy dữ liệu -------------------------------------------
    def _try_impersonate(self, query: str) -> list[Job] | None:
        """TLS giả lập Chrome. None = bị chặn hoặc không dùng được."""
        if curl_requests is None:
            return None
        try:
            resp = curl_requests.get(
                SEARCH_URL.format(query=query),
                impersonate=ITVIEC_IMPERSONATE,
                headers={"Accept-Language": "vi,en-US;q=0.9,en;q=0.8"},
                timeout=HTTP_TIMEOUT,
            )
        except Exception as exc:
            log.info("ITviec %s: TLS giả lập lỗi (%s)", query, exc)
            return None
        if resp.status_code != 200:
            log.info("ITviec %s: TLS giả lập -> HTTP %s", query, resp.status_code)
            return None
        return _parse_html(resp.text)

    def _try_direct(self, query: str) -> list[Job] | None:
        """Gọi thẳng bằng requests. None = bị chặn."""
        try:
            resp = self.get(SEARCH_URL.format(query=query), timeout=HTTP_TIMEOUT)
        except Exception as exc:
            log.info("ITviec %s: gọi trực tiếp lỗi (%s)", query, exc)
            return None
        if resp.status_code != 200:
            log.info("ITviec %s: gọi trực tiếp -> HTTP %s", query, resp.status_code)
            return None
        return _parse_html(resp.text)

    def _try_reader(self, query: str) -> list[Job] | None:
        """Đọc qua r.jina.ai. None = reader chặn (hết hạn mức cho IP này)."""
        target = SEARCH_URL.format(query=query)
        try:
            resp = self.session.get(
                READER_URL.format(target=target),
                headers=READER_HEADERS,
                timeout=ITVIEC_READER_TIMEOUT,
            )
        except Exception as exc:
            log.info("ITviec %s: reader lỗi (%s)", query, exc)
            return None
        if resp.status_code != 200:
            log.info("ITviec %s: reader -> HTTP %s", query, resp.status_code)
            return None
        return _parse_markdown(resp.text)

    def fetch(self) -> Iterable[Job]:
        routes = [
            ("TLS giả lập", self._try_impersonate),
            ("trực tiếp", self._try_direct),
            ("reader", self._try_reader),
        ]
        if curl_requests is None:
            log.info("ITviec: chưa có curl_cffi, bỏ qua đường TLS giả lập.")
            routes = routes[1:]

        jobs: list[Job] = []
        # Đường nào đã bị chặn thì thôi không thử lại ở query sau.
        dead: set[str] = set()

        for query in ITVIEC_QUERIES:
            for label, route in routes:
                if label in dead:
                    continue
                found = route(query)
                if found is None:
                    dead.add(label)
                    log.info("ITviec: bỏ đường '%s' cho các query còn lại.", label)
                    continue
                jobs.extend(found)
                log.info("ITviec %-14s -> %2d tin (%s)", query, len(found), label)
                break
            else:
                log.warning("ITviec %s: mọi đường đều bị chặn.", query)
                break
            time.sleep(REQUEST_DELAY)

        if not jobs:
            log.warning(
                "ITviec không lấy được tin nào — Cloudflare chặn cả ba đường."
            )
        return jobs

