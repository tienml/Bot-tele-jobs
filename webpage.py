"""Sinh trang web tĩnh thống kê toàn bộ job lấy được trong ngày.

Thay cho telegra.ph: trang nằm ngay trong repo (thư mục `docs/`), được
GitHub Pages phục vụ miễn phí. Ưu điểm so với Telegraph:

- Trang thuộc repo của bạn, sửa/xoá được bất cứ lúc nào.
- URL cố định nên nút bấm trong Telegram không đổi.
- Lưu được lịch sử theo ngày (`docs/archive/`) và số liệu tích luỹ
  (`docs/data.json`) để thống kê xu hướng.

Cấu trúc sinh ra:
    docs/.nojekyll              — tắt Jekyll để GitHub Pages đưa file thô
    docs/index.html             — danh sách + thống kê của ngày mới nhất
    docs/archive/YYYY-MM-DD.html — bản lưu từng ngày
    docs/data.json              — số liệu từng ngày, dùng vẽ biểu đồ
"""
from __future__ import annotations

import html
import json
import logging
from datetime import date, datetime

from config import ARCHIVE_KEEP_DAYS, PAGES_URL, SITE_DIR
from filters import CATEGORY_LABELS

log = logging.getLogger(__name__)

CATEGORY_ORDER = ["devops", "backend_java", "data_engineer"]
CATEGORY_ICONS = {"devops": "🛠️", "backend_java": "☕", "data_engineer": "📊"}

_CSS = """
:root {
  --bg: #0f1116;
  --card: #181b22;
  --line: #262a34;
  --text: #e6e8ee;
  --muted: #8b93a7;
  --accent: #5b9cff;
  --intern: #3ddc97;
  --fresher: #f0a24b;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 24px 16px 64px;
  background: var(--bg);
  color: var(--text);
  font: 16px/1.6 -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
}
.wrap { max-width: 900px; margin: 0 auto; }
h1 { font-size: 24px; margin: 0 0 4px; }
h2 { font-size: 19px; margin: 36px 0 12px; }
h3 { font-size: 16px; margin: 24px 0 8px; color: var(--muted); font-weight: 600; }
.sub { color: var(--muted); font-size: 14px; margin: 0 0 24px; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin-bottom: 8px;
}
.stat {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 14px 16px;
}
.stat .n { font-size: 26px; font-weight: 700; line-height: 1.2; }
.stat .l { color: var(--muted); font-size: 13px; }
.job {
  background: var(--card);
  border: 1px solid var(--line);
  border-left: 3px solid var(--intern);
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 10px;
}
.job.fresher { border-left-color: var(--fresher); }
.job a { color: var(--accent); text-decoration: none; font-weight: 600; }
.job a:hover { text-decoration: underline; }
.job .meta { color: var(--muted); font-size: 13.5px; margin-top: 4px; }
.pill {
  display: inline-block;
  background: #222633;
  border-radius: 20px;
  padding: 1px 9px;
  font-size: 12px;
  color: var(--muted);
  margin-right: 6px;
}
.pill.new { background: #17372a; color: var(--intern); }
.bars { display: flex; align-items: flex-end; gap: 6px; height: 90px; margin-top: 8px; }
.bars .b { flex: 1; background: var(--accent); border-radius: 3px 3px 0 0; min-height: 2px; }
.bars .b span { display: block; text-align: center; font-size: 10px; color: var(--muted);
                transform: translateY(-16px); }
.days { display: flex; gap: 6px; font-size: 10px; color: var(--muted); margin-top: 4px; }
.days div { flex: 1; text-align: center; }
.empty { color: var(--muted); font-style: italic; }
footer { margin-top: 48px; color: var(--muted); font-size: 13px;
         border-top: 1px solid var(--line); padding-top: 16px; }
footer a { color: var(--accent); }
ul.arch { list-style: none; padding: 0; display: flex; flex-wrap: wrap; gap: 8px; }
ul.arch a {
  display: block; background: var(--card); border: 1px solid var(--line);
  border-radius: 6px; padding: 5px 10px; color: var(--accent);
  text-decoration: none; font-size: 13.5px;
}
"""


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def _age_label(job, today: date) -> str:
    """Nhãn độ mới của tin, dựa vào ngày đăng."""
    if not job.posted_date:
        return job.posted_text or ""
    days = (today - job.posted_date).days
    if days <= 0:
        return "hôm nay"
    if days == 1:
        return "hôm qua"
    return f"{days} ngày trước"


def _job_html(job, today: date, css_class: str = "") -> str:
    """Một thẻ job."""
    bits = []
    if job.category:
        bits.append(CATEGORY_LABELS.get(job.category, job.category))
    bits.append(job.source)
    if job.location:
        bits.append(job.location)
    if job.salary:
        bits.append(job.salary)

    age = _age_label(job, today)
    is_new = job.posted_date is not None and (today - job.posted_date).days <= 1
    age_pill = f'<span class="pill{" new" if is_new else ""}">{_esc(age)}</span>' if age else ""

    return (
        f'<div class="job {css_class}">'
        f'<a href="{_esc(job.url)}" target="_blank" rel="noopener">{_esc(job.title)}</a>'
        f'<div class="meta">{age_pill}{_esc(" · ".join(bits))}</div>'
        f"</div>"
    )


def _section(title: str, jobs: list, today: date, css_class: str = "") -> str:
    """Một nhóm job có tiêu đề. Trả về chuỗi rỗng nếu nhóm trống."""
    if not jobs:
        return ""
    cards = "".join(_job_html(j, today, css_class) for j in jobs)
    return f"<h3>{_esc(title)} ({len(jobs)})</h3>{cards}"


def _stats_html(intern_jobs: list, fresher_jobs: list) -> str:
    """Các ô số liệu tổng quan."""
    by_source: dict[str, int] = {}
    for job in intern_jobs:
        by_source[job.source] = by_source.get(job.source, 0) + 1

    cells = [
        f'<div class="stat"><div class="n" style="color:var(--intern)">{len(intern_jobs)}</div>'
        f'<div class="l">Tin thực tập</div></div>',
        f'<div class="stat"><div class="n" style="color:var(--fresher)">{len(fresher_jobs)}</div>'
        f'<div class="l">Fresher (tham khảo)</div></div>',
    ]
    for cat in CATEGORY_ORDER:
        n = sum(1 for j in intern_jobs if j.category == cat)
        label = CATEGORY_LABELS.get(cat, cat)
        cells.append(
            f'<div class="stat"><div class="n">{n}</div>'
            f'<div class="l">{CATEGORY_ICONS.get(cat, "")} {_esc(label)}</div></div>'
        )
    if by_source:
        detail = ", ".join(f"{k} {v}" for k, v in sorted(by_source.items()))
        cells.append(
            f'<div class="stat"><div class="n">{len(by_source)}</div>'
            f'<div class="l">Nguồn: {_esc(detail)}</div></div>'
        )
    return f'<div class="grid">{"".join(cells)}</div>'


def _trend_html(history: dict) -> str:
    """Biểu đồ cột số tin thực tập theo ngày (14 ngày gần nhất)."""
    days = sorted(history.keys())[-14:]
    if len(days) < 2:
        return ""

    values = [history[d].get("intern", 0) for d in days]
    peak = max(values) or 1
    bars = "".join(
        f'<div class="b" style="height:{max(2, round(v / peak * 90))}px">'
        f"<span>{v}</span></div>"
        for v in values
    )
    labels = "".join(f"<div>{d[8:10]}/{d[5:7]}</div>" for d in days)
    return (
        f"<h2>Xu hướng {len(days)} ngày</h2>"
        f'<div class="bars">{bars}</div><div class="days">{labels}</div>'
    )


def _render(
    today: date,
    intern_jobs: list,
    fresher_jobs: list,
    history: dict,
    archive_days: list[str],
    is_index: bool,
) -> str:
    """Dựng HTML hoàn chỉnh cho một trang."""
    by_cat: dict[str, list] = {}
    for job in intern_jobs:
        by_cat.setdefault(job.category, []).append(job)

    body = [_stats_html(intern_jobs, fresher_jobs)]

    if is_index:
        body.append(_trend_html(history))

    body.append("<h2>Tin thực tập (đúng yêu cầu)</h2>")
    if intern_jobs:
        for cat in CATEGORY_ORDER:
            icon = CATEGORY_ICONS.get(cat, "")
            label = CATEGORY_LABELS.get(cat, cat)
            body.append(_section(f"{icon} {label}", by_cat.get(cat, []), today))
    else:
        body.append('<p class="empty">Hôm nay không có tin thực tập nào khớp.</p>')

    body.append("<h2>Fresher / Junior — chỉ để tham khảo</h2>")
    if fresher_jobs:
        body.append(
            '<p class="sub">Những tin này KHÔNG được gửi trong Top 5 vì không phải '
            "thực tập, liệt kê ở đây để bạn cân nhắc thêm.</p>"
        )
        fresher_by_cat: dict[str, list] = {}
        for job in fresher_jobs:
            fresher_by_cat.setdefault(job.category, []).append(job)
        for cat in CATEGORY_ORDER:
            icon = CATEGORY_ICONS.get(cat, "")
            label = CATEGORY_LABELS.get(cat, cat)
            body.append(
                _section(f"{icon} {label}", fresher_by_cat.get(cat, []), today, "fresher")
            )
    else:
        body.append('<p class="empty">Không có tin fresher/junior nào.</p>')

    if is_index and archive_days:
        links = "".join(
            f'<li><a href="archive/{d}.html">{d[8:10]}/{d[5:7]}</a></li>'
            for d in reversed(archive_days)
        )
        body.append(f'<h2>Lưu trữ theo ngày</h2><ul class="arch">{links}</ul>')

    if not is_index:
        body.append('<p style="margin-top:32px"><a href="../index.html">← Về trang mới nhất</a></p>')

    stamp = datetime.now().strftime("%d/%m/%Y %H:%M")
    title = f"Việc thực tập IT Hà Nội – {today.strftime('%d/%m/%Y')}"

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
<h1>{_esc(title)}</h1>
<p class="sub">DevOps · Backend Java · Data Engineer — khu vực Hà Nội.
Cập nhật {stamp}.</p>
{"".join(body)}
<footer>
Sinh tự động bởi bot tuyển dụng · nguồn: ITviec, VietnamWorks, Glints, LinkedIn.
</footer>
</div>
</body>
</html>
"""


def _load_history() -> dict:
    """Đọc số liệu tích luỹ; trả về dict rỗng nếu chưa có hoặc file hỏng."""
    path = SITE_DIR / "data.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("data.json không đọc được (%s), tạo lại từ đầu.", exc)
        return {}


def _prune_archive(keep_days: int) -> None:
    """Xoá bản lưu quá cũ để repo không phình mãi."""
    arch_dir = SITE_DIR / "archive"
    if not arch_dir.exists():
        return
    files = sorted(arch_dir.glob("*.html"))
    for old in files[:-keep_days] if len(files) > keep_days else []:
        old.unlink(missing_ok=True)
        log.info("Đã xoá bản lưu cũ %s", old.name)


def build(intern_jobs: list, fresher_jobs: list, today: date) -> str:
    """Sinh toàn bộ trang tĩnh, trả về URL công khai của trang.

    URL luôn cố định (PAGES_URL) nên nút trong Telegram không đổi. Trang chỉ
    thực sự cập nhật sau khi `docs/` được commit lên repo — GitHub Actions
    làm việc đó ở bước cuối của workflow.
    """
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "archive").mkdir(exist_ok=True)
    # GitHub Pages mặc định chạy Jekyll và bỏ qua file/thư mục bắt đầu bằng "_".
    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")

    key = today.isoformat()
    history = _load_history()
    history[key] = {
        "intern": len(intern_jobs),
        "fresher": len(fresher_jobs),
        "by_cat": {
            cat: sum(1 for j in intern_jobs if j.category == cat)
            for cat in CATEGORY_ORDER
        },
        "by_source": {
            src: sum(1 for j in intern_jobs if j.source == src)
            for src in sorted({j.source for j in intern_jobs})
        },
    }
    # Giữ số liệu gọn, cùng khoảng thời gian với bản lưu HTML.
    for stale in sorted(history.keys())[:-ARCHIVE_KEEP_DAYS]:
        history.pop(stale, None)

    _prune_archive(ARCHIVE_KEEP_DAYS)
    archive_days = sorted(p.stem for p in (SITE_DIR / "archive").glob("*.html"))
    if key not in archive_days:
        archive_days.append(key)

    (SITE_DIR / "archive" / f"{key}.html").write_text(
        _render(today, intern_jobs, fresher_jobs, history, archive_days, is_index=False),
        encoding="utf-8",
    )
    (SITE_DIR / "index.html").write_text(
        _render(today, intern_jobs, fresher_jobs, history, archive_days, is_index=True),
        encoding="utf-8",
    )
    (SITE_DIR / "data.json").write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    log.info(
        "Đã sinh trang tĩnh: %d tin thực tập, %d tin fresher -> %s",
        len(intern_jobs), len(fresher_jobs), PAGES_URL,
    )
    return PAGES_URL
