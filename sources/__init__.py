"""Các nguồn thu thập tin tuyển dụng.

Đã thử và bỏ: **topdev.vn** chặn ngay ở tầng TLS (SSLEOFError) với mọi cấu
hình. Scraper đó đã xoá khỏi repo; xem lịch sử git nếu cần dựng lại.

**topcv.vn** đứng sau Cloudflare nhưng TLS giả lập Chrome (curl_cffi) bypass
được — server trả HTML server-side render đầy đủ (~4 tin mỗi query).
"""
from .base import Job
from .glints import GlintsSource
from .itviec import ITviecSource
from .linkedin import LinkedInSource
from .topcv import TopCVSource
from .vietnamworks import VietnamWorksSource

# Thứ tự cũng là thứ tự ưu tiên khi gộp job trùng nhau giữa các nguồn.
ALL_SOURCES = [
    ITviecSource(),
    LinkedInSource(),
    VietnamWorksSource(),
    GlintsSource(),
    TopCVSource(),
]

__all__ = [
    "Job",
    "ITviecSource",
    "LinkedInSource",
    "VietnamWorksSource",
    "GlintsSource",
    "TopCVSource",
    "ALL_SOURCES",
]
