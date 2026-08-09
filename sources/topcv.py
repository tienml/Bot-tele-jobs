"""TopCV scraper – class TopCVSource(BaseSource).

TopCV đứng sau Cloudflare và chặn IP datacenter GitHub Actions. TLS giả lập
Chrome (curl_cffi impersonate='chrome124') bypass được: server trả HTML
server-side render đầy đủ, không cần JavaScript.

Nguồn này chạy HAI bộ query riêng (xem _INTERN_QUERIES / _FRESHER_QUERIES):
lọc cấp bậc `position=50` cho tin thực tập và lọc kinh nghiệm `exp=1,2` cho
tin fresher. Trước đây chỉ có exp=1,2 nên gần như chỉ ra fresher — 12 tin thô
mà chỉ 2 tin là thực tập.

Không phân trang được: thêm `&page=2` thì Cloudflare trả 403.

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
import os
import re
import time
from datetime import date, timedelta
from typing import Iterable
from urllib.parse import quote_plus, urlsplit

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

# ScraperAPI residential proxy — bypass Cloudflare IP-reputation block.
# Miễn phí 1000 req/tháng tại scraperapi.com (bot dùng ~90 req/tháng).
# Đặt secret SCRAPER_API_KEY trong GitHub Actions để bật fallback này.
_SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "")

# --- Hai bộ query, hai mục đích khác nhau --------------------------------
#
# TopCV có hai tham số lọc dễ nhầm lẫn, đã dò trực tiếp từ form filter:
#   exp=1,2       → KINH NGHIỆM: "không yêu cầu" + "dưới 1 năm". Đây là lọc
#                   FRESHER, không phải thực tập. Mỗi query trả 3-4 tin nên
#                   tin intern thật dễ bị đẩy khỏi trang.
#   position=50   → CẤP BẬC "Thực tập sinh". Đây mới là lọc intern thật.
#   type=5        → "Thực tập" (hình thức làm việc) nhưng server BỎ QUA
#                   tham số này: trả nguyên 50 tin gồm cả Senior/Trưởng nhóm.
#
# Nên dùng position=50 cho intern. Với slug hẹp theo ngành, nó chính xác
# tuyệt đối nhưng rất ít tin (data_engineer/backend_java ra 0). Vì vậy thêm
# slug rộng ("it", "data") để bắt tin mà slug hẹp bỏ sót — phần lọc ngành
# đã do detect_category() trong filters.py đảm nhiệm.
_INTERN_PARAMS = "position=50&type_keyword=1&sba=1&locations=l1"
_FRESHER_PARAMS = "exp=1,2&type_keyword=1&sba=1&locations=l1"

# Query intern (position=50). `category` để rỗng với slug rộng: không suy ra
# được ngành từ slug nên để detect_category() tự khớp theo tiêu đề/tag.
_INTERN_QUERIES: list[tuple[str, str, str]] = [
    ("devops", "devops", f"{BASE}/tim-viec-lam-devops-tai-ha-noi-kl1?{_INTERN_PARAMS}"),
    ("data_engineer", "data_engineer",
     f"{BASE}/tim-viec-lam-data-engineer-tai-ha-noi-kl1?{_INTERN_PARAMS}"),
    ("backend_java", "java", f"{BASE}/tim-viec-lam-java-tai-ha-noi-kl1?{_INTERN_PARAMS}"),
    ("", "rộng:it", f"{BASE}/tim-viec-lam-it-tai-ha-noi-kl1?{_INTERN_PARAMS}"),
    ("", "rộng:data", f"{BASE}/tim-viec-lam-data-tai-ha-noi-kl1?{_INTERN_PARAMS}"),
]

# Query fresher (exp=1,2) — giữ nguyên như trước, nhóm này chỉ hiện trên web.
_FRESHER_QUERIES: list[tuple[str, str, str]] = [
    ("devops", "devops", f"{BASE}/tim-viec-lam-devops-tai-ha-noi-kl1?{_FRESHER_PARAMS}"),
    ("data_engineer", "data_engineer",
     f"{BASE}/tim-viec-lam-data-engineer-tai-ha-noi-kl1?{_FRESHER_PARAMS}"),
    ("backend_java", "java", f"{BASE}/tim-viec-lam-java-tai-ha-noi-kl1?{_FRESHER_PARAMS}"),
]

# "Đăng 5 ngày trước", "Đăng1 tuần trước", "Đăng 2 tháng trước"
# TopCV đôi khi không chèn khoảng trắng giữa "Đăng" và số → \s*
_POSTED_RE = re.compile(r"Đăng\s*(\d+)\s*(giờ|ngày|tuần|tháng)\s*trước", re.I)
_CLEAN_RE = re.compile(r"\s+")

# Title trang khi TopCV không có tin nào khớp: "Tuyển dụng 0 việc làm ...".
# Dùng để phân biệt kết quả rỗng hợp lệ với trang bị Cloudflare chặn.
_ZERO_RESULT_RE = re.compile(r"tuyển dụng\s+0\s+việc làm", re.I)


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


def _parse_card(card, category: str, level_tag: str = "Không yêu cầu kinh nghiệm") -> Job | None:
    """Parse một div.job-item-search-result từ HTML trang tìm kiếm TopCV.

    `level_tag` là tag cấp bậc suy ra từ tham số URL đã dùng — card HTML không
    ghi cấp bậc nên phải gán từ query. Xem _INTERN_QUERIES / _FRESHER_QUERIES.
    """
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
        # Card HTML không ghi cấp bậc, nên gán tag theo tham số URL đã dùng:
        # position=50 → "Thực tập sinh" (khớp INTERN_KEYWORDS "thuc tap sinh"),
        # exp=1,2 → "Không yêu cầu kinh nghiệm" (khớp FRESHER_KEYWORDS).
        # Nhờ tag này filters.py phân loại được intern vs fresher.
        tags=[level_tag],
        posted_text=posted_text,
        posted_date=posted_date,
        category=category,
    )


def _fetch_scraperapi(url: str, api_key: str) -> str | None:
    """Fetch qua ScraperAPI residential proxy — bypass Cloudflare IP-reputation block.

    ScraperAPI route request qua IP residential ngẫu nhiên, Cloudflare không thể
    phân biệt với người dùng thật. render=false vì TopCV server-side render đủ.
    Free tier: 1000 req/tháng — đủ cho bot (~90 req/tháng).
    """
    api_url = (
        "https://api.scraperapi.com"
        f"?api_key={api_key}"
        f"&url={quote_plus(url)}"
        "&render=false"
        "&country_code=vn"
    )
    try:
        resp = curl_requests.get(api_url, timeout=HTTP_TIMEOUT + 30)
        if resp.status_code == 200:
            log.info("TopCV ScraperAPI: OK (len=%d)", len(resp.text))
            return resp.text
        log.warning("TopCV ScraperAPI: HTTP %s", resp.status_code)
        return None
    except Exception as exc:
        log.warning("TopCV ScraperAPI lỗi: %s", exc)
        return None


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


def _parse_html(
    html: str, category: str, level_tag: str = "Không yêu cầu kinh nghiệm"
) -> list[Job]:
    """Tách các tin từ HTML trang tìm kiếm TopCV."""
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("div.job-item-search-result")
    if not cards:
        title = soup.title.string.strip() if soup.title and soup.title.string else "?"
        # Phân biệt "TopCV thật sự không có tin nào khớp" với "bị chặn / HTML
        # đổi cấu trúc". Trang rỗng hợp lệ có title dạng
        # "Tuyển dụng 0 việc làm ..." — đó là kết quả bình thường, không phải lỗi.
        if _ZERO_RESULT_RE.search(title):
            log.info("TopCV %s: TopCV không có tin nào khớp bộ lọc.", category)
        else:
            log.warning(
                "TopCV %s: 0 card tìm thấy — page title=%r"
                " (Cloudflare block page hoặc HTML structure thay đổi)",
                category, title,
            )
    jobs: list[Job] = []
    for card in cards:
        try:
            job = _parse_card(card, category, level_tag)
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

    def _fetch_html(self, url: str, label: str) -> str | None:
        """Lấy HTML một URL, thử lần lượt 3 cách cho tới khi được."""
        # Bước 1: curl_cffi (giả lập TLS Chrome)
        try:
            resp = curl_requests.get(
                url,
                impersonate=_IMPERSONATE,
                headers={"Accept-Language": "vi,en-US;q=0.9,en;q=0.8"},
                timeout=HTTP_TIMEOUT,
            )
            if resp.status_code == 200:
                return resp.text
            log.warning(
                "TopCV %s: curl_cffi HTTP %s%s",
                label, resp.status_code,
                " — thử fallback" if resp.status_code == 403 else "",
            )
        except Exception as exc:
            log.warning("TopCV %s: lỗi kết nối curl_cffi (%s)", label, exc)

        # Bước 2: ScraperAPI residential proxy — bypass Cloudflare IP-reputation
        # block (curl_cffi dùng Azure IP bị block, ScraperAPI dùng IP residential).
        if _SCRAPER_API_KEY:
            log.info("TopCV %s: thử ScraperAPI...", label)
            html = _fetch_scraperapi(url, _SCRAPER_API_KEY)
            if html is not None:
                return html

        # Bước 3: Playwright — chỉ bypass JS challenge, không bypass IP block.
        if _PLAYWRIGHT_OK:
            log.info("TopCV %s: thử Playwright...", label)
            return _fetch_playwright(url)

        return None

    def _run_queries(
        self, queries: list[tuple[str, str, str]], level_tag: str, kind: str
    ) -> list[Job]:
        """Chạy một bộ query và gán `level_tag` cho mọi tin thu được."""
        jobs: list[Job] = []
        for category, slug_label, url in queries:
            label = f"{kind}/{slug_label}"
            html = self._fetch_html(url, label)
            if html is None:
                time.sleep(REQUEST_DELAY)
                continue
            found = _parse_html(html, category, level_tag)
            jobs.extend(found)
            log.info("TopCV %-20s -> %2d tin", label, len(found))
            time.sleep(REQUEST_DELAY)
        return jobs

    def fetch(self) -> Iterable[Job]:
        if curl_requests is None:
            log.warning("TopCV: chưa cài curl_cffi, bỏ qua nguồn này.")
            return []

        # Hai bộ query chạy riêng vì tag cấp bậc gán khác nhau: position=50 cho
        # tin thực tập, exp=1,2 cho tin fresher. Gộp chung một bộ như trước thì
        # tin intern bị lẫn và filters.py không phân biệt được.
        intern = self._run_queries(
            _INTERN_QUERIES, "Thực tập sinh", "intern"
        )
        fresher = self._run_queries(
            _FRESHER_QUERIES, "Không yêu cầu kinh nghiệm", "fresher"
        )

        # Cùng một tin có thể xuất hiện ở cả hai bộ (ví dụ "DevOps Intern" khớp
        # cả position=50 lẫn exp=1,2). Ưu tiên bản từ bộ intern để giữ tag
        # "Thực tập sinh" — nếu để bản fresher ghi đè thì tin thực tập bị xếp
        # nhầm sang nhóm chỉ-xem-trên-web.
        seen: dict[str, Job] = {}
        for job in intern + fresher:
            seen.setdefault(job.url, job)

        jobs = list(seen.values())
        log.info(
            "TopCV tổng: %d tin (intern-query %d, fresher-query %d, trùng %d)",
            len(jobs), len(intern), len(fresher),
            len(intern) + len(fresher) - len(jobs),
        )
        if not jobs:
            log.warning("TopCV không lấy được tin nào — có thể bị Cloudflare chặn IP.")
        return jobs
