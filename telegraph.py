"""Telegraph helper — tạo trang công khai để xem toàn bộ danh sách job.

Dùng API miễn phí của telegra.ph (không cần đăng ký).
Trang được tạo mỗi ngày khi bot gửi digest, URL được đính kèm vào message.
"""
from __future__ import annotations

import json
import logging
from datetime import date

import requests

log = logging.getLogger(__name__)

_API = "https://api.telegra.ph/createPage"
_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
)

# Nhãn category cho Telegraph page
_ICONS = {"devops": "DevOps", "backend_java": "Backend Java", "data_engineer": "Data Engineer"}


def _node(tag: str, children: list, attrs: dict | None = None) -> dict:
    n: dict = {"tag": tag, "children": children}
    if attrs:
        n["attrs"] = attrs
    return n


def _build_content(jobs: list, today: date) -> list:
    """Xây dựng mảng Node cho Telegraph theo đặc tả telegra.ph."""
    content = [
        _node("p", [f"Tổng: {len(jobs)} tin intern IT tại Hà Nội — {today.strftime('%d/%m/%Y')}"]),
        _node("hr", []),
    ]

    # Nhóm theo category
    by_cat: dict[str, list] = {}
    for job in jobs:
        by_cat.setdefault(job.category, []).append(job)

    icons = {"devops": "🛠️", "backend_java": "☕", "data_engineer": "📊"}

    for cat in ["devops", "backend_java", "data_engineer"]:
        cat_jobs = by_cat.get(cat, [])
        if not cat_jobs:
            continue

        label = _ICONS.get(cat, cat)
        icon = icons.get(cat, "•")
        content.append(_node("h4", [f"{icon} {label} ({len(cat_jobs)} tin)"]))

        items = []
        for job in cat_jobs:
            age = ""
            if job.posted_date:
                days = (today - job.posted_date).days
                age = f" · hôm nay" if days == 0 else f" · {days} ngày trước"

            salary = f" · {job.salary}" if job.salary else ""
            items.append(
                _node("li", [
                    _node("a", [job.title], {"href": job.url, "target": "_blank"}),
                    f" – {job.company}{salary}{age}",
                ])
            )
        content.append(_node("ul", items))

    content.append(_node("hr", []))
    content.append(_node("p", [
        f"Tạo tự động bởi Bot Tuyển Dụng Intern IT · {today.strftime('%d/%m/%Y')}"
    ]))
    return content


def create_page(jobs: list, today: date) -> str | None:
    """Tạo trang Telegraph với toàn bộ danh sách job.

    Trả về URL trang (vd: https://telegra.ph/Intern-IT-Ha-Noi-07-08) hoặc
    None nếu thất bại (lỗi mạng, giới hạn tốc độ, v.v.).

    Trang không cần auth — bất kỳ ai có link đều xem được.
    """
    if not jobs:
        return None

    title = f"Intern IT Hà Nội – {today.strftime('%d/%m/%Y')}"
    content = _build_content(jobs, today)

    try:
        resp = _SESSION.post(
            _API,
            json={
                "title": title,
                "author_name": "Bot Tuyển Dụng Intern",
                "content": json.dumps(content),
            },
            timeout=15,
        )
        data = resp.json()
        if data.get("ok") and data.get("result", {}).get("url"):
            url = data["result"]["url"]
            log.info("Telegraph page created: %s", url)
            return url
        log.warning("Telegraph API lỗi: %s", data.get("error") or data)
    except Exception as exc:
        log.warning("Không tạo được trang Telegraph: %s", exc)

    return None
