"""TopCV scraper – class TopCVSource(BaseSource).

TopCV đứng sau Cloudflare và chặn IP datacenter GitHub Actions. TLS giả lập
Chrome (curl_cffi impersonate='chrome124') bypass được: server trả HTML
server-side render đầy đủ, không cần JavaScript. Mỗi URL tìm kiếm cho ~4 tin.

Jina reader bị TopCV block ở tầng Cloudflare (403) nên không có fallback.
Nếu curl_cffi không cài, nguồn này bỏ qua hoàn toàn.

Cấu trúc HTML mỗi tin (div.job-item-search-result):
  data-job-id                  → ID job (không dùng trực tiếp, URL là key)
  h3.title a[href]             → URL job (có tracking param ta_source + u_sr_id)
  h3.title a span[data-toggle] → tiêu đề (lấy từ attr title để tránh icon text)
  span.company-name[title]     → tên công ty
  label.salary                 → mức lương ("0.0 - 0.0 triệu" = không có)
  [class*=address]             → địa điểm ("Hà Nội")
  text "Đăng X <đơn_vị> trước" → ngày đăng (quét toàn card)
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta
from typing import Iterable
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from config import HTTP_TIMEOUT, REQUEST_DELAY
from sources.base import BaseSource, Job

# curl_cffi là điều kiện bắt buộc của nguồn này — không có thì skip hoàn toàn.
try:
    from curl_cffi import requests as curl_requests
except ImportError:  # pragma: no cover
    curl_requests = None

# Playwright dùng làm fallback khi curl_cffi bị Cloudflare JS-challenge chặn.
# Không giải quyết được IP-reputation block thuần tuý (chỉ tầng TLS/JS).
try:
    import playwright  # noqa: F401 — chỉ kiểm tra cài đặt
    _PLAYWRIGHT_OK = True
except ImportError:
    _PLAYWRIGHT_OK = False

log = logging.getLogger(__name__)

BASE = "https://www.topcv.vn"

# Giả lập TLS Chrome — cùng giá trị với ITviec để dễ đồng bộ nếu cần đổi.
_IMPERSONATE = "chrome124"

# exp=1,2 bao gồm cả fresher (exp=1) lẫn dưới 1 năm kinh nghiệm (exp=2).
_QUERIES: dict[str, str] = {
    "devops": (
        BASE + "/tim-viec-lam-devops-tai-ha-noi-kl1"
        "?exp=1,2&type_keyword=1&sba=1&locations=l1"
    ),
    "data_engineer": (
        BASE + "/tim-viec-lam-data-engineer-tai-ha-noi-kl1"
        "?exp=1,2&type_keyword=1&sba=1&locations=l1"
    ),
    "backend_java": (
        BASE + "/tim-viec-lam-java-tai-ha-noi-kl1"
        "?exp=1,2&type_keyword=1&sba=1&locations=l1"
    ),
}

# "Đăng 5 ngày trước", "Đăng1 tuần trước", "Đăng 2 tháng trước"
# TopCV đôi khi không chèn khoảng trắng giữa "Đăng" và số → \s*
_POSTED_RE = re.compile(r"Đăng\s*(\d+)\s*(giờ|ngày|tuần|tháng)\s*trước", re.I)
_CLEAN_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _CLEAN_RE.sub(" ", text or "").strip()


def _strip_query(url: str) -> str:
    """Bỏ ta_source và u_sr_id — TopCV gắn tracking param khác nhau mỗi lần."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _parse_posted(text: str) -> tuple[str, date | None]:
    """Trả (posted_text chuẩn, posted_date) từ nhãn thời gian tiếng Việt."""
    m = _POSTED_RE.search(text or "")
    if not m:
        return _clean(text), None
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit == "giờ":
        days = 0
    elif unit == "ngày":
        days = n
    elif unit == "tuần":
        days = n * 7
    else:  # tháng
        days = n * 30
    return _clean(m.group(0)), date.today() - timedelta(days=days)


def _parse_card(card, category: str) -> Job | None:
    """Parse một div.job-item-search-result từ HTML trang tìm kiếm TopCV."""
    # --- Title + URL ---------------------------------------------------------
    title_a = card.select_one("h3.title a")
    if not title_a:
        return None
    # Tiêu đề nằm trong <span data-toggle="tooltip" title="..."> — lấy attr
    # title để tránh lấy text của icon verified employer kèm theo.
    title_span = title_a.select_one("span[data-toggle]")
    if title_span:
        title = _clean(title_span.get("title") or title_span.get_text())
    else:
        title = _clean(title_a.get_text())
    if not title:
        return None
    href = title_a.get("href", "")
    url = _strip_query(href) if href else ""
    if not url:
        return None

    # --- Company -------------------------------------------------------------
    # <span class="company-name" title="Tên đầy đủ">Tên đầy đủ</span>
    # Dùng attr title để tránh text bị cắt bớt khi tên quá dài.
    co_el = card.select_one("span.company-name")
    company = _clean(co_el.get("title") or co_el.get_text()) if co_el else ""

    # --- Salary --------------------------------------------------------------
    sal_el = card.select_one("label.salary") or card.select_one("label.title-salary")
    salary = ""
    if sal_el:
        # Xoá icon <i> (fa-circle-dollar) trước khi lấy text
        for icon in sal_el.select("i"):
            icon.decompose()
        salary = _clean(sal_el.get_text())
    # "0.0 - 0.0 triệu" là placeholder khi không có thông tin lương
    if salary.startswith("0.0"):
        salary = ""

    # --- Location ------------------------------------------------------------
    loc_el = (
        card.select_one("[class*=address]")
        or card.select_one("[class*=location]")
        or card.select_one(".address")
    )
    location = _clean(loc_el.get_text()) if loc_el else "Hà Nội"

    # --- Posted date ---------------------------------------------------------
    # Quét tất cả phần tử trong card, lấy element ngắn nhất chứa pattern
    # "Đăng X ... trước" để tránh lấy text lồng nhau của phần tử cha.
    posted_text = ""
    posted_date: date | None = None
    for el in card.select("label, span"):
        txt = _clean(el.get_text())
        if _POSTED_RE.search(txt):
            if not posted_text or len(txt) < len(posted_text):
                posted_text, posted_date = _parse_posted(txt)

    return Job(
        title=title,
        company=company,
        url=url,
        source="TopCV",
        location=location,
        salary=salary,
        # URL TopCV đã filter exp=1,2 (không yêu cầu kinh nghiệm + dưới 1 năm)
        # nên tất cả job đều là entry-level. Thêm tag để bộ lọc intern/fresher
        # trong filters.py nhận ra được (FRESHER_KEYWORDS có "khong yeu cau kinh nghiem").
        tags=["Không yêu cầu kinh nghiệm"],
        posted_text=posted_text,
        posted_date=posted_date,
        category=category,
    )


def _fetch_playwright(url: str) -> str | None:
    """Dùng Playwright headless Chromium để bypass Cloudflare JS challenge.

    Chạy trong thread riêng để tránh xung đột với asyncio event loop
    (curl_cffi và python-telegram-bot đều dùng asyncio).
    Hiệu quả khi Cloudflare dùng 5-second shield / JS challenge.
    Không bypass được IP-reputation block thuần tuý (GitHub Actions Azure IP).
    """
    if not _PLAYWRIGHT_OK:
        return None

    import concurrent.futures

    def _run_sync() -> str | None:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    locale="vi-VN",
                    timezone_id="Asia/Ho_Chi_Minh",
                )
                page = ctx.new_page()
                resp = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                # Đợi 2s để JS challenge (nếu có) resolve xong
                page.wait_for_timeout(2_000)
                html = page.content()
                status = resp.status if resp else "?"
                title = page.title()
                log.info(
                    "TopCV Playwright: HTTP %s | title=%r | html_len=%d",
                    status, title, len(html),
                )
                browser.close()
                return html
        except Exception as exc:
            log.warning("TopCV Playwright lỗi: %s", exc)
            return None

    # Chạy trong thread riêng — sync_playwright() không chạy được trong asyncio loop
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_sync)
        try:
            return future.result(timeout=40)
        except concurrent.futures.TimeoutError:
            log.warning("TopCV Playwright: timeout sau 40s")
            return None
        except Exception as exc:
            log.warning("TopCV Playwright thread lỗi: %s", exc)
            return None


def _parse_html(html: str, category: str) -> list[Job]:
    """Tách các tin từ HTML trang tìm kiếm TopCV."""
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("div.job-item-search-result")
    if not cards:
        title = soup.title.string.strip() if soup.title and soup.title.string else "?"
        log.warning(
            "TopCV %s: 0 card tìm thấy — page title=%r"
            " (Cloudflare block page hoặc HTML structure thay đổi)",
            category, title,
        )
    jobs: list[Job] = []
    for card in cards:
        try:
            job = _parse_card(card, category)
        except Exception:
            log.debug("TopCV: lỗi parse job-item-search-result", exc_info=True)
            continue
        if job:
            jobs.append(job)
    return jobs


class TopCVSource(BaseSource):
    """Scraper TopCV — TLS giả lập Chrome qua curl_cffi.

    Không có fallback: Jina reader bị TopCV chặn ở Cloudflare (403).
    Nếu curl_cffi chưa cài thì nguồn này bỏ qua hoàn toàn và ghi log warning.
    """

    name = "TopCV"

    def fetch(self) -> Iterable[Job]:
        if curl_requests is None:
            log.warning("TopCV: chưa cài curl_cffi, bỏ qua nguồn này.")
            return []

        jobs: list[Job] = []
        for category, url in _QUERIES.items():
            html: str | None = None

            # Bước 1: thử curl_cffi (giả lập TLS Chrome)
            try:
                resp = curl_requests.get(
                    url,
                    impersonate=_IMPERSONATE,
                    headers={"Accept-Language": "vi,en-US;q=0.9,en;q=0.8"},
                    timeout=HTTP_TIMEOUT,
                )
                if resp.status_code == 200:
                    html = resp.text
                else:
                    log.warning(
                        "TopCV %s: curl_cffi HTTP %s%s",
                        category, resp.status_code,
                        " — thử Playwright fallback" if resp.status_code == 403 and _PLAYWRIGHT_OK else "",
                    )
            except Exception as exc:
                log.warning("TopCV %s: lỗi kết nối curl_cffi (%s)", category, exc)

            # Bước 2: fallback Playwright khi curl_cffi bị 403 (Cloudflare JS challenge)
            if html is None and _PLAYWRIGHT_OK:
                log.info("TopCV %s: thử Playwright...", category)
                html = _fetch_playwright(url)

            if html is None:
                time.sleep(REQUEST_DELAY)
                continue

            found = _parse_html(html, category)
            jobs.extend(found)
            log.info("TopCV %-14s -> %2d tin", category, len(found))
            time.sleep(REQUEST_DELAY)

        if not jobs:
            log.warning("TopCV không lấy được tin nào — có thể bị Cloudflare chặn IP.")
        return jobs
