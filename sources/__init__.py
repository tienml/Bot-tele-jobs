"""Các nguồn thu thập tin tuyển dụng.

Đã thử và bỏ: **topdev.vn** chặn ngay ở tầng TLS (SSLEOFError) với mọi cấu
hình, **topcv.vn** trả 403 qua Cloudflare cho cả API và HTML. Hai scraper đó
đã xoá khỏi repo; xem lịch sử git nếu cần dựng lại.
"""
from .base import Job
from .glints import GlintsSource
from .itviec import ITviecSource
from .linkedin import LinkedInSource
from .vietnamworks import VietnamWorksSource

# Thứ tự cũng là thứ tự ưu tiên khi gộp job trùng nhau giữa các nguồn.
ALL_SOURCES = [
    ITviecSource(),
    LinkedInSource(),
    VietnamWorksSource(),
    GlintsSource(),
]

__all__ = [
    "Job",
    "ITviecSource",
    "LinkedInSource",
    "VietnamWorksSource",
    "GlintsSource",
    "ALL_SOURCES",
]
