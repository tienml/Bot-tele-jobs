"""Kiểu dữ liệu Job dùng chung và lớp cơ sở cho mọi nguồn."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

import requests

from config import REQUEST_TIMEOUT, USER_AGENT

# Từ chỉ loại hình pháp nhân và lĩnh vực chung. Bỏ chúng đi thì chỉ còn tên
# riêng, nhờ vậy "Công Ty Cổ Phần Chứng Khoán SSI" và "SSI Securities
# Corporation" nhận ra được là cùng một công ty.
_COMPANY_STOPWORDS = frozenset("""
cong ty co phan tnhh ctcp mtv hh tap doan
corporation corp company jsc ltd limited inc llc plc
group holdings holding joint stock
chung khoan securities finance tai chinh bank ngan hang
nghe technology technologies tech software phan mem
solution solutions giai phap system systems he thong
service services dich vu thuong mai trading
dau tu investment vietnam viet nam global digital
""".split())


def _words(text: str) -> list[str]:
    """Tách thành từ đã bỏ dấu tiếng Việt và ký tự đặc biệt.

    Lưu ý đ/Đ là chữ riêng trong Unicode, NFD không tách được thành d + dấu,
    nên phải đổi tay — nếu không "Tập Đoàn" ra "tap oan" và mất chữ đầu.
    """
    text = (text or "").replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]+", text.lower())


@dataclass
class Job:
    title: str
    company: str
    url: str
    source: str
    location: str = ""
    salary: str = ""
    tags: list[str] = field(default_factory=list)
    posted_text: str = ""
    posted_date: date | None = None
    category: str = ""  # devops | backend_java | data_engineer
    score: int = 0

    @property
    def job_id(self) -> str:
        """ID ổn định để phát hiện job đã gửi rồi.

        Dùng URL đã bỏ query string, vì ITviec gắn thêm tham số tracking
        thay đổi giữa các lần request cho cùng một tin.
        """
        clean_url = self.url.split("?")[0].rstrip("/")
        return hashlib.sha1(clean_url.encode("utf-8")).hexdigest()[:16]

    @property
    def company_key(self) -> str:
        """Tên riêng của công ty, đã bỏ loại hình pháp nhân và ngành nghề.

        Cùng một công ty thường được các nguồn ghi khác nhau, ví dụ
        "Công Ty Cổ Phần Chứng Khoán SSI" và "SSI Securities Corporation" —
        bỏ hết từ chung thì cả hai còn lại "ssi" nên gộp được.
        """
        words = [w for w in _words(self.company) if w not in _COMPANY_STOPWORDS]
        if not words:
            # Tên chỉ gồm từ chung (hiếm): dùng nguyên tên để không gộp bừa
            # mọi công ty "không tên riêng" vào cùng một khoá.
            words = _words(self.company)
        return "".join(sorted(set(words)))

    @property
    def title_key(self) -> str:
        """Tiêu đề đã chuẩn hoá, dùng cùng company_key để phát hiện trùng."""
        return "".join(_words(self.title))

    @property
    def dedupe_key(self) -> str:
        """Khoá gộp job trùng được đăng trên nhiều nguồn khác nhau."""
        return f"{self.title_key}|{self.company_key}"

    @property
    def detail_score(self) -> int:
        """Mức chi tiết của tin — dùng chọn bản tốt hơn khi hai tin trùng nhau.

        Tin nào nêu rõ lương, địa điểm, ngày đăng và nhiều tag công nghệ thì
        đọc được nhiều thông tin hơn, nên được giữ lại.
        """
        score = 0
        if self.salary:
            score += 30
        if self.posted_date:
            score += 20
        if self.location:
            score += 10
        if self.company:
            score += 10
        score += min(len(self.tags) * 3, 18)
        # Tiêu đề dài hơn thường mô tả rõ vị trí hơn ("Thực tập sinh Data
        # Engineer" so với "Intern"), nhưng chỉ tính nhẹ để không lấn các
        # tiêu chí trên.
        score += min(len(self.title) // 20, 5)
        return score


class BaseSource:
    """Lớp cơ sở: mỗi nguồn tự lo phần lấy và parse dữ liệu."""

    name = "base"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def get(self, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        return self.session.get(url, **kwargs)

    def fetch(self) -> Iterable[Job]:
        raise NotImplementedError
