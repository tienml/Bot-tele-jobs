"""Script chạy một lần — dùng cho GitHub Actions cron.

Không cần polling hay server. Chỉ cần BOT_TOKEN và CHAT_IDS.

Runner của GitHub Actions là ephemeral (xoá sạch sau mỗi lần chạy), nên
jobs.db được commit ngược lại repo ở bước sau trong workflow. Nhờ vậy
lịch sử "đã gửi" vẫn còn và mỗi sáng chỉ gửi tin MỚI.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import date

from telegram import Bot

# Thêm thư mục gốc vào path để import được các module
sys.path.insert(0, os.path.dirname(__file__))

import storage
from bot import fetch_all_jobs, format_summary, make_top_keyboard
from config import BOT_TOKEN

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


def get_chat_ids() -> list[int]:
    """Đọc danh sách chat ID từ biến môi trường CHAT_IDS.

    Định dạng: chuỗi số cách nhau bởi dấu phẩy.
    Ví dụ: CHAT_IDS=123456789,987654321
    """
    raw = os.environ.get("CHAT_IDS", "").strip()
    if not raw:
        log.error("CHAT_IDS chưa được cấu hình. Thêm secret CHAT_IDS vào GitHub repo.")
        sys.exit(1)
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                ids.append(int(part))
            except ValueError:
                log.warning("CHAT_IDS chứa giá trị không hợp lệ: %r, bỏ qua.", part)
    if not ids:
        log.error("CHAT_IDS không chứa ID hợp lệ nào.")
        sys.exit(1)
    return ids


async def main() -> None:
    if not BOT_TOKEN:
        log.error("BOT_TOKEN chưa được cấu hình.")
        sys.exit(1)

    chat_ids = get_chat_ids()
    log.info("Gửi tới %d chat(s): %s", len(chat_ids), chat_ids)

    storage.init_db()

    # Dọn lịch sử cũ hơn 60 ngày để DB không phình mãi.
    deleted = storage.purge_old_sent()
    if deleted:
        log.info("Đã xoá %d bản ghi sent_jobs cũ", deleted)

    all_jobs = fetch_all_jobs()
    new_jobs = storage.filter_unsent(all_jobs)
    log.info("Tổng job: %d, tin mới chưa gửi: %d", len(all_jobs), len(new_jobs))

    today = date.today()

    if not new_jobs:
        msg = (
            f"📋 <b>Cập nhật ngày {today.strftime('%d/%m/%Y')}</b>\n\n"
            "😔 Hôm nay chưa có tin tuyển dụng intern IT mới ở Hà Nội.\n"
            "Bot sẽ kiểm tra lại vào ngày mai."
        )
        keyboard = None
    else:
        msg = format_summary(new_jobs, today)
        keyboard = make_top_keyboard(new_jobs)

    sent_ok = False
    bot = Bot(token=BOT_TOKEN)
    async with bot:
        for chat_id in chat_ids:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=msg,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                    disable_web_page_preview=True,
                )
                sent_ok = True
                log.info("Đã gửi tới %s", chat_id)
            except Exception as exc:
                log.warning("Gửi tới %s thất bại: %s", chat_id, exc)

    # Chỉ đánh dấu đã gửi khi thực sự gửi được cho ít nhất 1 chat.
    # Nếu gửi lỗi hết thì để nguyên, mai gửi lại.
    if new_jobs and sent_ok:
        storage.mark_sent(new_jobs)
        log.info("Đã đánh dấu %d job là đã gửi", len(new_jobs))
    elif new_jobs:
        log.error("Không gửi được cho chat nào — không đánh dấu, sẽ thử lại lần sau.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
