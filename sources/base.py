"""Kiểu dữ liệu Job dùng chung và lớp cơ sở cho mọi nguồn."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

import requests

from config import REQUEST_TIMEOUT, USER_AGENT


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
    def dedupe_key(self) -> str:
        """Khoá gộp job trùng được đăng trên nhiều nguồn khác nhau."""
        norm = lambda s: re.sub(r"[^a-z0-9]+", "", s.lower())
        return f"{norm(self.title)}|{norm(self.company)}"


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
