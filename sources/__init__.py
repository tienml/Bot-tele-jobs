"""Các nguồn thu thập tin tuyển dụng."""
from .base import Job
from .itviec import ITviecSource
from .vietnamworks import VietnamWorksSource

# Thứ tự cũng là thứ tự ưu tiên khi gộp job trùng nhau giữa các nguồn.
ALL_SOURCES = [ITviecSource(), VietnamWorksSource()]

__all__ = ["Job", "ITviecSource", "VietnamWorksSource", "ALL_SOURCES"]
