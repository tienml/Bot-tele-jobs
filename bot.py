"""Bot Telegram tự động lấy tin tuyển dụng intern IT ở Hà Nội.

Chạy:
    python bot.py

Lệnh bot:
    /start – đăng ký nhận tin hàng ngày
    /stop  – huỷ đăng ký
    /jobs  – xem tin ngay lập tức (không đợi lịch)
"""
from __future__ import annotations

import logging
import sys
from datetime import date, datetime, time as dtime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

import storage
from config import BOT_TOKEN, DAILY_HOUR, DAILY_MINUTE, MAX_AGE_DAYS, TIMEZONE, TOP_N
from filters import CATEGORY_LABELS, filter_and_score
from sources import ALL_SOURCES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def fetch_all_jobs() -> list:
    """Thu thập job từ tất cả nguồn, lọc và chấm điểm."""
    all_jobs = []
    for source in ALL_SOURCES:
        try:
            jobs = list(source.fetch())
            log.info("%s returned %d jobs", source.name, len(jobs))
            all_jobs.extend(jobs)
        except Exception:
            log.exception("%s fetch failed", source.name)

    # Loại job cũ hơn MAX_AGE_DAYS
    today = date.today()
    recent = [
        j for j in all_jobs
        if j.posted_date is None or (today - j.posted_date).days <= MAX_AGE_DAYS
    ]

    filtered = filter_and_score(recent, today)
    log.info("Fetched %d → recent %d → filtered %d", len(all_jobs), len(recent), len(filtered))
    return filtered


def format_summary(jobs: list, today: date) -> str:
    """Tạo message tổng hợp theo category."""
    # Nhóm theo category
    by_cat = {}
    for job in jobs:
        by_cat.setdefault(job.category, []).append(job)

    lines = [
        f"📋 <b>Tin tuyển dụng Intern IT – {today.strftime('%d/%m/%Y')}</b>",
        f"🔢 Tổng: <b>{len(jobs)} tin</b> | Hà Nội\n",
    ]

    # Icon cho từng category
    icons = {"devops": "🛠️", "backend_java": "☕", "data_engineer": "📊"}

    for category in ["devops", "backend_java", "data_engineer"]:
        jobs_in_cat = by_cat.get(category, [])
        if not jobs_in_cat:
            continue

        label = CATEGORY_LABELS.get(category, category)
        icon = icons.get(category, "•")
        lines.append(f"━━━ {icon} {label} ({len(jobs_in_cat)} tin) ━━━")

        for job in jobs_in_cat[:10]:  # Giới hạn 10 tin mỗi nhóm
            age = ""
            if job.posted_date:
                days = (today - job.posted_date).days
                if days == 0:
                    age = "🆕 Hôm nay"
                elif days == 1:
                    age = "📅 Hôm qua"
                else:
                    age = f"📅 {days} ngày trước"

            title_short = job.title if len(job.title) <= 60 else job.title[:57] + "..."
            lines.append(f'• <a href="{job.url}"><b>{title_short}</b></a>')
            lines.append(f"  🏢 {job.company} · {age}")

        lines.append("")  # Dòng trắng giữa các category

    lines.append("─────────────────────────")
    # Số nút thực tế có thể ít hơn TOP_N khi hôm đó ít job.
    top_count = min(TOP_N, len(jobs))
    lines.append(f"⭐ <b>Top {top_count} tiềm năng nhất có nút xem ngay bên dưới:</b>")

    return "\n".join(lines)


def make_top_keyboard(top_jobs: list) -> InlineKeyboardMarkup:
    """Tạo inline keyboard cho TOP_N job."""
    buttons = []
    for i, job in enumerate(top_jobs[:TOP_N], 1):
        title_short = job.title if len(job.title) <= 50 else job.title[:47] + "..."
        label = f"{i}. {title_short}"
        buttons.append([InlineKeyboardButton(text=label, url=job.url)])
    return InlineKeyboardMarkup(buttons)


async def send_daily(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback được gọi mỗi ngày theo lịch."""
    log.info("=== Daily job started ===")

    # Dọn lịch sử cũ hơn 60 ngày để DB không phình mãi.
    deleted = storage.purge_old_sent()
    if deleted:
        log.info("Purged %d old sent_jobs records", deleted)

    all_jobs = fetch_all_jobs()
    new_jobs = storage.filter_unsent(all_jobs)
    log.info("Total jobs: %d, new (unsent): %d", len(all_jobs), len(new_jobs))

    subscribers = storage.get_all_subscribers()
    if not subscribers:
        log.info("No subscribers, skipping send")
        return

    today = date.today()

    if not new_jobs:
        # Không có tin mới — gửi thông báo ngắn thay vì im lặng.
        msg = (
            f"📋 <b>Cập nhật ngày {today.strftime('%d/%m/%Y')}</b>\n\n"
            "😔 Hôm nay chưa có tin tuyển dụng intern IT mới ở Hà Nội.\n"
            "Bot sẽ kiểm tra lại vào ngày mai."
        )
        for chat_id in subscribers:
            try:
                await context.bot.send_message(
                    chat_id=chat_id, text=msg, parse_mode="HTML"
                )
            except Exception as exc:
                log.warning("Failed to send to %s: %s", chat_id, exc)
        log.info("=== Daily job completed (no new jobs) ===")
        return

    summary = format_summary(new_jobs, today)
    keyboard = make_top_keyboard(new_jobs)

    log.info("Sending to %d subscribers", len(subscribers))
    for chat_id in subscribers:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=summary,
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
        except Exception as exc:
            log.warning("Failed to send to %s: %s", chat_id, exc)

    # Đánh dấu đã gửi SAU khi gửi xong (tránh mất dữ liệu nếu gửi lỗi giữa chừng).
    storage.mark_sent(new_jobs)
    log.info("=== Daily job completed (%d new jobs sent) ===", len(new_jobs))


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Đăng ký nhận tin hàng ngày."""
    chat_id = update.effective_chat.id
    storage.add_subscriber(chat_id)

    await update.message.reply_text(
        "✅ <b>Đăng ký thành công!</b>\n\n"
        f"Bot sẽ gửi tin tuyển dụng intern IT (DevOps / Backend Java / Data Engineer) "
        f"ở Hà Nội mỗi ngày lúc {DAILY_HOUR:02d}:{DAILY_MINUTE:02d}.\n\n"
        "📌 Lệnh:\n"
        "/jobs – xem tin ngay\n"
        "/stop – huỷ đăng ký",
        parse_mode="HTML",
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Huỷ đăng ký."""
    chat_id = update.effective_chat.id
    storage.remove_subscriber(chat_id)
    await update.message.reply_text("❌ Đã huỷ đăng ký. Gửi /start để đăng ký lại.")


async def cmd_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lấy tin thủ công ngay lập tức."""
    await update.message.reply_text("⏳ Đang tìm kiếm job...")

    jobs = fetch_all_jobs()
    if not jobs:
        await update.message.reply_text("😔 Không tìm thấy tin phù hợp.")
        return

    today = date.today()
    summary = format_summary(jobs, today)
    keyboard = make_top_keyboard(jobs)

    await update.message.reply_text(
        text=summary,
        parse_mode="HTML",
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


def main() -> None:
    if not BOT_TOKEN:
        log.error("BOT_TOKEN chưa được cấu hình. Tạo file .env hoặc export BOT_TOKEN=...")
        sys.exit(1)

    storage.init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("jobs", cmd_jobs))

    # Lịch chạy hàng ngày
    job_queue = app.job_queue
    job_queue.run_daily(
        send_daily,
        time=dtime(hour=DAILY_HOUR, minute=DAILY_MINUTE),
        days=(0, 1, 2, 3, 4, 5, 6),  # mỗi ngày
        name="daily_jobs",
    )

    log.info("Bot started. Daily schedule: %02d:%02d %s", DAILY_HOUR, DAILY_MINUTE, TIMEZONE)
    log.info("Subscribers: %d", storage.count_subscribers())

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
