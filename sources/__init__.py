"""Các nguồn thu thập tin tuyển dụng."""
from .base import Job
from .glints import GlintsSource
from .itviec import ITviecSource
from .topcv import TopCVSource
from .topdev import TopDevSource
from .vietnamworks import VietnamWorksSource

# Thứ tự cũng là thứ tự ưu tiên khi gộp job trùng nhau giữa các nguồn.
ALL_SOURCES = [
    ITviecSource(),
    VietnamWorksSource(),
    GlintsSource(),
    TopDevSource(),
    TopCVSource(),
]

__all__ = [
    "Job",
    "ITviecSource",
    "VietnamWorksSource",
    "GlintsSource",
    "TopDevSource",
    "TopCVSource",
    "ALL_SOURCES",
]
