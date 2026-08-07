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

# Màu nhận dạng từng nguồn, giúp mắt phân biệt nhanh khi cuộn danh sách dài.
SOURCE_COLORS = {
    "ITviec": "#e0574f",
    "VietnamWorks": "#4a9be0",
    "Glints": "#2fc39b",
    "LinkedIn": "#5b9cff",
}

_CSS = """
:root {
  --bg: #0e1015;
  --bg-soft: #14171f;
  --card: #171b23;
  --card-hi: #1d222c;
  --line: #262b36;
  --line-soft: #1f242e;
  --text: #eceef4;
  --text-dim: #b6bdcd;
  --muted: #848da3;
  --accent: #6ba6ff;
  --intern: #3ddc97;
  --fresher: #f5a94f;
  --radius: 14px;
  --shadow: 0 1px 2px rgba(0,0,0,.35), 0 8px 24px -16px rgba(0,0,0,.7);
}
@media (prefers-color-scheme: light) {
  :root {
    --bg: #f6f7fa;
    --bg-soft: #eef0f5;
    --card: #ffffff;
    --card-hi: #f4f6fa;
    --line: #e0e4ec;
    --line-soft: #eaedf3;
    --text: #171a21;
    --text-dim: #40485a;
    --muted: #6b7488;
    --accent: #1f63d6;
    --intern: #10a06a;
    --fresher: #c1741a;
    --shadow: 0 1px 2px rgba(20,26,40,.06), 0 10px 24px -18px rgba(20,26,40,.35);
  }
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  padding: 0 0 72px;
  background: var(--bg);
  color: var(--text);
  font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
        "Helvetica Neue", Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 860px; margin: 0 auto; padding: 0 18px; }

/* ---------- Header ---------- */
header.top {
  border-bottom: 1px solid var(--line);
  background: linear-gradient(180deg, var(--bg-soft), var(--bg));
  padding: 30px 0 22px;
  margin-bottom: 26px;
}
h1 {
  font-size: clamp(21px, 4.4vw, 27px);
  line-height: 1.25;
  margin: 0 0 8px;
  letter-spacing: -.015em;
}
.tagline { color: var(--text-dim); font-size: 14.5px; margin: 0; }
.stamp { color: var(--muted); font-size: 13px; margin: 6px 0 0; }

/* ---------- Thống kê ---------- */
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
}
.stat {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 15px 16px;
  min-height: 92px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}
.stat .n {
  font-size: 30px;
  font-weight: 700;
  line-height: 1.1;
  letter-spacing: -.02em;
  font-variant-numeric: tabular-nums;
}
.stat .l {
  color: var(--muted);
  font-size: 12.5px;
  text-transform: uppercase;
  letter-spacing: .05em;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.stat.zero .n { color: var(--muted); }

/* ---------- Hàng chip nguồn ---------- */
.chiprow { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 13px;
  color: var(--text-dim);
}
.chip b { color: var(--text); font-variant-numeric: tabular-nums; }
.dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }

/* ---------- Tiêu đề mục ---------- */
h2 {
  font-size: 15px;
  text-transform: uppercase;
  letter-spacing: .07em;
  color: var(--muted);
  margin: 38px 0 14px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
  font-weight: 700;
}
h3 {
  font-size: 15.5px;
  margin: 22px 0 10px;
  font-weight: 650;
  display: flex;
  align-items: center;
  gap: 8px;
}
h3 .count {
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
  background: var(--card-hi);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 1px 9px;
}

/* ---------- Thẻ job ---------- */
.job {
  position: relative;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: var(--shadow);
  padding: 14px 16px 13px 18px;
  margin-bottom: 10px;
  transition: transform .12s ease, border-color .12s ease;
}
.job::before {
  content: "";
  position: absolute;
  left: 0; top: 10px; bottom: 10px;
  width: 3px;
  border-radius: 3px;
  background: var(--intern);
}
.job.fresher::before { background: var(--fresher); }
.job:hover { transform: translateY(-1px); border-color: var(--accent); }
.job .title {
  display: block;
  color: var(--text);
  font-size: 16px;
  font-weight: 650;
  line-height: 1.4;
  text-decoration: none;
}
.job .title:hover { color: var(--accent); }
.job .company { color: var(--text-dim); font-size: 14px; margin-top: 3px; }
.job .meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 8px;
  margin-top: 9px;
  font-size: 12.5px;
  color: var(--muted);
}
.tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border-radius: 6px;
  padding: 2px 8px;
  background: var(--card-hi);
  border: 1px solid var(--line-soft);
  white-space: nowrap;
}
.tag.src { font-weight: 600; }
.tag.new { color: var(--intern); border-color: color-mix(in srgb, var(--intern) 40%, transparent); }
.tag.pay { color: var(--intern); }
.tag.cat { color: var(--text-dim); }

/* ---------- Biểu đồ xu hướng ---------- */
.chart {
  display: flex;
  align-items: flex-end;
  gap: 7px;
  height: 132px;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 14px 14px 10px;
}
.chart .col {
  flex: 1;
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  align-items: center;
}
.chart .v { font-size: 11px; color: var(--muted); margin-bottom: 4px;
            font-variant-numeric: tabular-nums; }
.chart .bar {
  width: 100%;
  min-height: 3px;
  border-radius: 5px 5px 0 0;
  background: linear-gradient(180deg, var(--intern), color-mix(in srgb, var(--intern) 45%, transparent));
}
.chart .col.zero .bar { background: var(--line); }
.xaxis { display: flex; gap: 7px; margin-top: 7px; padding: 0 14px; }
.xaxis div { flex: 1; text-align: center; font-size: 10.5px; color: var(--muted); }

/* ---------- Mục fresher thu gọn ---------- */
details.fold {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 0 16px;
  box-shadow: var(--shadow);
}
details.fold > summary {
  cursor: pointer;
  padding: 15px 0;
  font-weight: 650;
  font-size: 15px;
  list-style: none;
  display: flex;
  align-items: center;
  gap: 9px;
}
details.fold > summary::-webkit-details-marker { display: none; }
details.fold > summary::before {
  content: "▸";
  color: var(--fresher);
  transition: transform .15s ease;
}
details.fold[open] > summary::before { transform: rotate(90deg); }
details.fold > summary .count {
  font-size: 12px; font-weight: 600; color: var(--muted);
  background: var(--card-hi); border: 1px solid var(--line);
  border-radius: 999px; padding: 1px 9px;
}
details.fold .inner { padding-bottom: 14px; }
details.fold .note { color: var(--muted); font-size: 13.5px; margin: 0 0 14px; }
details.fold .job { background: var(--card-hi); }

/* ---------- Khác ---------- */
.empty {
  color: var(--muted);
  font-size: 14.5px;
  background: var(--card);
  border: 1px dashed var(--line);
  border-radius: var(--radius);
  padding: 18px;
  text-align: center;
}
ul.arch { list-style: none; padding: 0; margin: 0;
          display: flex; flex-wrap: wrap; gap: 8px; }
ul.arch a {
  display: block; background: var(--card); border: 1px solid var(--line);
  border-radius: 8px; padding: 6px 11px; color: var(--accent);
  text-decoration: none; font-size: 13.5px;
}
ul.arch a:hover { border-color: var(--accent); }
.backlink { display: inline-block; margin-top: 30px; color: var(--accent);
            text-decoration: none; font-size: 14.5px; }
footer {
  margin-top: 46px; padding-top: 18px;
  border-top: 1px solid var(--line);
  color: var(--muted); font-size: 13px;
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


def _source_color(source: str) -> str:
    return SOURCE_COLORS.get(source, "#8b93a7")


def _job_html(job, today: date, css_class: str = "") -> str:
    """Một thẻ job: tiêu đề, công ty, rồi hàng nhãn phụ."""
    tags: list[str] = []

    age = _age_label(job, today)
    if age:
        is_new = job.posted_date is not None and (today - job.posted_date).days <= 1
        tags.append(f'<span class="tag{" new" if is_new else ""}">🕒 {_esc(age)}</span>')

    tags.append(
        f'<span class="tag src">'
        f'<i class="dot" style="background:{_source_color(job.source)}"></i>'
        f"{_esc(job.source)}</span>"
    )
    if job.category:
        icon = CATEGORY_ICONS.get(job.category, "")
        label = CATEGORY_LABELS.get(job.category, job.category)
        tags.append(f'<span class="tag cat">{icon} {_esc(label)}</span>')
    if job.location:
        tags.append(f'<span class="tag">📍 {_esc(job.location)}</span>')
    if job.salary:
        tags.append(f'<span class="tag pay">💰 {_esc(job.salary)}</span>')

    company = (
        f'<div class="company">{_esc(job.company)}</div>' if job.company else ""
    )
    return (
        f'<div class="job {css_class}">'
        f'<a class="title" href="{_esc(job.url)}" target="_blank" rel="noopener">'
        f"{_esc(job.title)}</a>"
        f"{company}"
        f'<div class="meta">{"".join(tags)}</div>'
        f"</div>"
    )


def _section(title: str, jobs: list, today: date, css_class: str = "") -> str:
    """Một nhóm job có tiêu đề. Trả về chuỗi rỗng nếu nhóm trống."""
    if not jobs:
        return ""
    cards = "".join(_job_html(j, today, css_class) for j in jobs)
    return (
        f"<h3>{_esc(title)}<span class=\"count\">{len(jobs)}</span></h3>{cards}"
    )


def _stats_html(intern_jobs: list, fresher_jobs: list, today: date) -> str:
    """Bốn ô số liệu chính + hàng chip chi tiết theo nhóm và theo nguồn.

    Nhãn trong ô luôn ngắn gọn (một dòng) để các ô cùng chiều cao; phần chi
    tiết dài như danh sách nguồn được đẩy xuống hàng chip bên dưới.
    """
    fresh_today = sum(
        1 for j in intern_jobs
        if j.posted_date is not None and (today - j.posted_date).days <= 0
    )
    by_source: dict[str, int] = {}
    for job in intern_jobs:
        by_source[job.source] = by_source.get(job.source, 0) + 1

    def cell(value: int, label: str, color: str = "") -> str:
        style = f' style="color:{color}"' if color and value else ""
        zero = " zero" if not value else ""
        return (
            f'<div class="stat{zero}"><div class="n"{style}>{value}</div>'
            f'<div class="l">{label}</div></div>'
        )

    cells = [
        cell(len(intern_jobs), "Thực tập", "var(--intern)"),
        cell(fresh_today, "Đăng hôm nay"),
        cell(len(fresher_jobs), "Fresher", "var(--fresher)"),
        cell(len(by_source), "Nguồn có tin"),
    ]

    chips = []
    for cat in CATEGORY_ORDER:
        n = sum(1 for j in intern_jobs if j.category == cat)
        label = CATEGORY_LABELS.get(cat, cat)
        chips.append(
            f'<span class="chip">{CATEGORY_ICONS.get(cat, "")} '
            f"{_esc(label)} <b>{n}</b></span>"
        )
    for src, n in sorted(by_source.items(), key=lambda kv: (-kv[1], kv[0])):
        chips.append(
            f'<span class="chip"><i class="dot" style="background:'
            f'{_source_color(src)}"></i>{_esc(src)} <b>{n}</b></span>'
        )

    return (
        f'<div class="grid">{"".join(cells)}</div>'
        f'<div class="chiprow">{"".join(chips)}</div>'
    )


def _trend_html(history: dict) -> str:
    """Biểu đồ cột số tin thực tập theo ngày (14 ngày gần nhất)."""
    days = sorted(history.keys())[-14:]
    if len(days) < 2:
        return ""

    values = [history[d].get("intern", 0) for d in days]
    peak = max(values) or 1
    cols = "".join(
        f'<div class="col{" zero" if not v else ""}">'
        f'<span class="v">{v}</span>'
        f'<div class="bar" style="height:{max(3, round(v / peak * 100))}%"></div>'
        f"</div>"
        for v in values
    )
    labels = "".join(f"<div>{d[8:10]}/{d[5:7]}</div>" for d in days)
    return (
        f"<h2>Xu hướng {len(days)} ngày</h2>"
        f'<div class="chart">{cols}</div><div class="xaxis">{labels}</div>'
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

    body = [_stats_html(intern_jobs, fresher_jobs, today)]

    if is_index:
        body.append(_trend_html(history))

    body.append("<h2>Tin thực tập</h2>")
    if intern_jobs:
        for cat in CATEGORY_ORDER:
            icon = CATEGORY_ICONS.get(cat, "")
            label = CATEGORY_LABELS.get(cat, cat)
            body.append(_section(f"{icon} {label}", by_cat.get(cat, []), today))
    else:
        body.append('<p class="empty">Hôm nay không có tin thực tập nào khớp.</p>')

    # Fresher gấp lại mặc định: đây là nhóm tham khảo, không nên chiếm chỗ
    # của nhóm chính khi cuộn trang.
    body.append("<h2>Tham khảo thêm</h2>")
    if fresher_jobs:
        fresher_by_cat: dict[str, list] = {}
        for job in fresher_jobs:
            fresher_by_cat.setdefault(job.category, []).append(job)
        inner = [
            '<p class="note">Các tin fresher / junior này KHÔNG được gửi qua '
            "Telegram vì không phải thực tập, liệt kê ở đây để bạn cân nhắc "
            "thêm.</p>"
        ]
        for cat in CATEGORY_ORDER:
            icon = CATEGORY_ICONS.get(cat, "")
            label = CATEGORY_LABELS.get(cat, cat)
            inner.append(
                _section(f"{icon} {label}", fresher_by_cat.get(cat, []), today, "fresher")
            )
        body.append(
            f'<details class="fold"><summary>Fresher / Junior'
            f'<span class="count">{len(fresher_jobs)}</span></summary>'
            f'<div class="inner">{"".join(inner)}</div></details>'
        )
    else:
        body.append('<p class="empty">Không có tin fresher/junior nào.</p>')

    if is_index and len(archive_days) > 1:
        links = "".join(
            f'<li><a href="archive/{d}.html">{d[8:10]}/{d[5:7]}</a></li>'
            for d in reversed(archive_days)
        )
        body.append(f'<h2>Lưu trữ theo ngày</h2><ul class="arch">{links}</ul>')

    if not is_index:
        body.append('<a class="backlink" href="../index.html">← Về trang mới nhất</a>')

    stamp = datetime.now().strftime("%d/%m/%Y %H:%M")
    heading = f"Việc thực tập IT Hà Nội"
    title = f"{heading} – {today.strftime('%d/%m/%Y')}"

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<meta name="description" content="Tin thực tập DevOps, Backend Java, Data Engineer tại Hà Nội, cập nhật hằng ngày.">
<title>{_esc(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<header class="top"><div class="wrap">
<h1>{_esc(heading)}</h1>
<p class="tagline">🛠️ DevOps · ☕ Backend Java · 📊 Data Engineer</p>
<p class="stamp">Dữ liệu ngày {today.strftime('%d/%m/%Y')} · cập nhật {stamp}</p>
</div></header>
<div class="wrap">
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
