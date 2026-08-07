"""Các nguồn thu thập tin tuyển dụng.

TopDev và TopCV vẫn còn file scraper nhưng KHÔNG nằm trong ALL_SOURCES:
- topdev.vn chặn ngay ở tầng TLS (SSLEOFError) với mọi cấu hình.
- topcv.vn trả 403 qua Cloudflare cho cả API và HTML.
Để trong danh sách chạy chỉ làm mỗi lần fetch chờ timeout vô ích. Khi nào
hai site này mở lại thì thêm vào ALL_SOURCES là dùng được ngay.
"""
from .base import Job
from .glints import GlintsSource
from .itviec import ITviecSource
from .linkedin import LinkedInSource
from .topcv import TopCVSource
from .topdev import TopDevSource
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
    "TopDevSource",
    "TopCVSource",
    "ALL_SOURCES",
]
