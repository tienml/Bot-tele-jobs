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

Trang không dùng JavaScript. Phần lọc theo nhóm nghề làm bằng radio ẩn
cộng selector `:checked ~`, nên mở bằng file:// hay qua Pages đều chạy.
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
CATEGORY_ICONS = {"devops": "🛠", "backend_java": "☕", "data_engineer": "📊"}

SOURCE_COLORS = {
    "ITviec":       "#ff6b5b",
    "VietnamWorks": "#3b9eff",
    "Glints":       "#00c896",
    "LinkedIn":     "#7b8bff",
}

# Gradient nền cho từng nhóm nghề — dùng trong icon box
CAT_GRADIENTS = {
    "devops":       "linear-gradient(135deg,#f97316,#ea580c)",
    "backend_java": "linear-gradient(135deg,#8b5cf6,#7c3aed)",
    "data_engineer":"linear-gradient(135deg,#06b6d4,#0891b2)",
}

_CSS = """
/* ── Reset & base ─────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg:      #0a0c10;
  --surface: #111318;
  --card:    #161a22;
  --card-h:  #1c2130;
  --border:  rgba(255,255,255,.07);
  --border-h:rgba(255,255,255,.13);
  --text:    #e8eaf2;
  --text-2:  #9aa0b4;
  --text-3:  #5c6478;
  --brand:   #6c8fff;
  --green:   #22d3a0;
  --amber:   #ffb347;
  --red:     #ff6b5b;
  --r:       14px;
  --r-sm:    9px;
}
@media (prefers-color-scheme: light) {
  :root {
    --bg:      #f4f6fb;
    --surface: #ffffff;
    --card:    #ffffff;
    --card-h:  #f0f3fa;
    --border:  #dde2ee;
    --border-h:#bec6db;
    --text:    #0f1218;
    --text-2:  #47506a;
    --text-3:  #8a93aa;
    --brand:   #2a52cc;
    --green:   #059669;
    --amber:   #b45309;
    --red:     #dc3545;
  }
}
html { scroll-behavior: smooth; -webkit-text-size-adjust: 100%; }
body {
  background: var(--bg);
  color: var(--text);
  font: 400 15px/1.65
    ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",
    Roboto,"Helvetica Neue",Arial,sans-serif;
  -webkit-font-smoothing: antialiased;
  padding-bottom: 80px;
  min-height: 100vh;
}
a { color: var(--brand); text-decoration: none; }
.wrap { max-width: 920px; margin: 0 auto; padding: 0 20px; }

/* ── Header ───────────────────────────────────────────────── */
header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 40px 0 32px;
  margin-bottom: 36px;
  position: relative;
  overflow: hidden;
}
header::before {
  content: "";
  position: absolute; inset: 0;
  background:
    radial-gradient(ellipse 80% 120% at -10% -30%,
      rgba(108,143,255,.13) 0%, transparent 55%),
    radial-gradient(ellipse 60% 80% at 110% 110%,
      rgba(34,211,160,.09) 0%, transparent 50%);
  pointer-events: none;
}
.badge {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 11px; font-weight: 700; letter-spacing: .12em;
  text-transform: uppercase; color: var(--text-3);
  border: 1px solid var(--border);
  border-radius: 999px; padding: 4px 11px; margin-bottom: 18px;
}
.badge-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 0 3px rgba(34,211,160,.2);
}
h1 {
  font-size: clamp(28px, 6vw, 46px);
  font-weight: 800; letter-spacing: -.04em; line-height: 1.08;
  margin-bottom: 10px;
}
.h1-accent {
  background: linear-gradient(100deg, var(--brand) 0%, var(--green) 100%);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
}
.sub { color: var(--text-2); font-size: 15px; margin-bottom: 18px; }
.meta-row {
  display: flex; flex-wrap: wrap; gap: 6px 18px;
  color: var(--text-3); font-size: 12.5px;
}

/* ── Stat grid ─────────────────────────────────────────────── */
.stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 12px;
}
.stat {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 18px 20px 16px;
  position: relative; overflow: hidden;
  transition: border-color .2s, background .2s;
}
.stat::after {
  content: "";
  position: absolute; top: 0; left: 0; right: 0; height: 2px;
  background: var(--accent, var(--border));
  border-radius: var(--r) var(--r) 0 0;
}
.stat:hover { border-color: var(--border-h); }
.stat-val {
  font-size: 36px; font-weight: 800;
  letter-spacing: -.05em; line-height: 1;
  color: var(--c, var(--text));
  font-variant-numeric: tabular-nums;
  margin-bottom: 6px;
}
.stat-label {
  font-size: 11px; font-weight: 700;
  text-transform: uppercase; letter-spacing: .1em;
  color: var(--text-3);
}

/* ── Chips ─────────────────────────────────────────────────── */
.chips { display: flex; flex-wrap: wrap; gap: 7px; margin: 14px 0; }
.chip {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--card); border: 1px solid var(--border);
  border-radius: 999px; padding: 4px 12px;
  font-size: 12.5px; color: var(--text-2);
}
.chip strong { color: var(--text); font-variant-numeric: tabular-nums; }
.dot {
  width: 7px; height: 7px; border-radius: 50%;
  flex-shrink: 0;
}

/* ── Section heading ───────────────────────────────────────── */
.sec-head {
  display: flex; align-items: center; gap: 10px;
  margin: 40px 0 18px;
}
.sec-head-line {
  flex: 1; height: 1px; background: var(--border);
}
.sec-title {
  font-size: 11px; font-weight: 800;
  text-transform: uppercase; letter-spacing: .13em;
  color: var(--text-3); white-space: nowrap;
}

/* ── Category heading ─────────────────────────────────────── */
.cat-head {
  display: flex; align-items: center; gap: 10px;
  margin: 24px 0 12px;
}
.cat-icon {
  width: 32px; height: 32px; flex-shrink: 0;
  border-radius: 9px;
  display: grid; place-items: center;
  font-size: 15px;
  background: var(--g, var(--card));
  box-shadow: 0 2px 8px rgba(0,0,0,.25);
}
.cat-name { font-size: 15.5px; font-weight: 700; letter-spacing: -.01em; }
.badge-count {
  font-size: 11.5px; font-weight: 700;
  color: var(--text-3); background: var(--card);
  border: 1px solid var(--border); border-radius: 999px;
  padding: 2px 9px; font-variant-numeric: tabular-nums;
}

/* ── Filter tabs ───────────────────────────────────────────── */
.filter-wrap { margin-bottom: 20px; }
.filter-tabs { display: flex; flex-wrap: wrap; gap: 7px; }
.filter-tabs input { position: absolute; opacity: 0; pointer-events: none; }
.filter-tabs label {
  cursor: pointer; user-select: none;
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--card); border: 1px solid var(--border);
  border-radius: 999px; padding: 6px 14px;
  font-size: 13px; font-weight: 600; color: var(--text-2);
  transition: all .15s ease;
}
.filter-tabs label:hover { border-color: var(--border-h); color: var(--text); }
#f-all:checked    ~ .filter-wrap label[for="f-all"],
#f-devops:checked ~ .filter-wrap label[for="f-devops"],
#f-java:checked   ~ .filter-wrap label[for="f-java"],
#f-data:checked   ~ .filter-wrap label[for="f-data"] {
  background: var(--text); color: var(--bg);
  border-color: var(--text);
}
#f-devops:checked ~ .filter-wrap .cats .cat:not([data-cat="devops"]),
#f-java:checked   ~ .filter-wrap .cats .cat:not([data-cat="backend_java"]),
#f-data:checked   ~ .filter-wrap .cats .cat:not([data-cat="data_engineer"])
  { display: none; }

/* ── Job card ──────────────────────────────────────────────── */
.job-card {
  display: block; color: inherit;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 16px 18px 14px;
  margin-bottom: 9px;
  position: relative;
  overflow: hidden;
  transition: border-color .18s, background .18s, transform .18s, box-shadow .18s;
}
.job-card::before {
  content: "";
  position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
  background: var(--stripe, var(--green));
  border-radius: var(--r) 0 0 var(--r);
}
.job-card:hover {
  border-color: var(--border-h);
  background: var(--card-h);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px -8px rgba(0,0,0,.4);
}
.job-card:hover .job-title { color: var(--brand); }
.job-title {
  font-size: 15.5px; font-weight: 700;
  line-height: 1.4; letter-spacing: -.015em;
  padding-left: 10px;
  transition: color .18s;
}
.job-company {
  display: flex; align-items: center; gap: 6px;
  color: var(--text-2); font-size: 13.5px;
  margin-top: 5px; padding-left: 10px;
}
.job-meta {
  display: flex; flex-wrap: wrap; gap: 5px;
  margin-top: 10px; padding-left: 10px;
}
.tag {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 12px; border-radius: 6px;
  padding: 3px 8px;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text-3);
  white-space: nowrap;
}
.tag.new-tag {
  color: var(--green); font-weight: 700;
  border-color: rgba(34,211,160,.25);
  background: rgba(34,211,160,.08);
}
.tag.pay-tag {
  color: var(--amber); font-weight: 600;
  border-color: rgba(255,179,71,.2);
  background: rgba(255,179,71,.07);
}
.tag.src-tag { font-weight: 600; color: var(--text-2); }
.job-card.fresher { --stripe: var(--amber); }

/* ── Chart ─────────────────────────────────────────────────── */
.chart-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 20px 20px 14px;
  margin-bottom: 0;
}
.chart-title {
  font-size: 12px; font-weight: 700;
  text-transform: uppercase; letter-spacing: .1em;
  color: var(--text-3); margin-bottom: 16px;
}
.chart {
  display: flex; align-items: flex-end;
  gap: 5px; height: 100px;
}
.chart-col {
  flex: 1; display: flex; flex-direction: column;
  justify-content: flex-end; align-items: center; gap: 4px;
}
.chart-val {
  font-size: 10px; color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.chart-bar {
  width: 100%; min-height: 3px;
  border-radius: 4px 4px 2px 2px;
  background: var(--green);
  opacity: .6;
  transition: opacity .2s;
}
.chart-col:hover .chart-bar { opacity: 1; }
.chart-col.today .chart-bar { background: var(--brand); opacity: 1; }
.chart-col.zero .chart-bar { background: var(--border); opacity: 1; }
.chart-x {
  display: flex; gap: 5px; margin-top: 8px;
}
.chart-x div {
  flex: 1; text-align: center;
  font-size: 10px; color: var(--text-3);
  font-variant-numeric: tabular-nums;
}

/* ── Fresher fold ─────────────────────────────────────────── */
details.fresher-fold {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--r); overflow: hidden;
}
details.fresher-fold > summary {
  list-style: none; cursor: pointer;
  display: flex; align-items: center; gap: 10px;
  padding: 15px 18px;
  font-size: 14.5px; font-weight: 700;
  transition: background .15s;
}
details.fresher-fold > summary:hover { background: var(--card-h); }
details.fresher-fold > summary::-webkit-details-marker { display: none; }
.fold-arrow {
  width: 20px; height: 20px;
  border-radius: 6px;
  display: grid; place-items: center;
  font-size: 12px; color: var(--text-3);
  background: var(--surface); border: 1px solid var(--border);
  transition: transform .2s ease;
  flex-shrink: 0;
}
details.fresher-fold[open] .fold-arrow { transform: rotate(90deg); }
.fresher-inner { padding: 0 18px 18px; }
.fresher-note {
  font-size: 13px; color: var(--text-3);
  background: var(--surface); border-radius: var(--r-sm);
  padding: 10px 14px; margin-bottom: 14px;
  border-left: 3px solid var(--amber);
}

/* ── Archive ───────────────────────────────────────────────── */
.arch-grid { display: flex; flex-wrap: wrap; gap: 7px; }
.arch-grid a {
  display: block;
  background: var(--card); border: 1px solid var(--border);
  border-radius: var(--r-sm); padding: 6px 12px;
  font-size: 13px; color: var(--text-2);
  font-variant-numeric: tabular-nums;
  transition: border-color .15s, color .15s;
}
.arch-grid a:hover { border-color: var(--border-h); color: var(--text); }

/* ── Empty state ───────────────────────────────────────────── */
.empty-state {
  background: var(--card); border: 1px dashed var(--border-h);
  border-radius: var(--r); padding: 32px 20px;
  text-align: center; color: var(--text-3); font-size: 14px;
}

/* ── Footer / misc ─────────────────────────────────────────── */
.back-link {
  display: inline-flex; align-items: center; gap: 7px;
  margin-top: 32px; font-size: 14px; color: var(--text-2);
}
.back-link:hover { color: var(--text); }
footer {
  margin-top: 56px; padding-top: 20px;
  border-top: 1px solid var(--border);
  color: var(--text-3); font-size: 12.5px;
}

/* ── Mobile ────────────────────────────────────────────────── */
@media (max-width: 600px) {
  header { padding: 28px 0 24px; }
  .stats { grid-template-columns: repeat(2, 1fr); }
  .stat-val { font-size: 30px; }
  .job-title { font-size: 14.5px; }
}
"""

# ── Hàm tiện ích ────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    """Escape HTML entities."""
    return html.escape(str(text or ""), quote=True)


def _age_label(posted: date | None, today: date) -> str:
    """Trả về nhãn thời gian dạng '2 ngày trước', 'Hôm nay'…"""
    if posted is None:
        return ""
    delta = (today - posted).days
    if delta == 0:
        return "Hôm nay"
    if delta == 1:
        return "Hôm qua"
    if delta < 7:
        return f"{delta} ngày trước"
    if delta < 14:
        return "1 tuần trước"
    if delta < 21:
        return "2 tuần trước"
    return f"{delta // 7} tuần trước"


def _source_color(source: str) -> str:
    return SOURCE_COLORS.get(source, "#9aa0b4")


# ── Card từng job ────────────────────────────────────────────────────────────

def _job_html(job, today: date, is_new: bool = False, is_fresher: bool = False) -> str:
    age = _age_label(job.posted_date, today)
    color = _source_color(job.source)
    fresher_cls = " fresher" if is_fresher else ""

    tags_html = ""
    if is_new:
        tags_html += '<span class="tag new-tag">🆕 Mới</span>'
    if job.salary:
        tags_html += f'<span class="tag pay-tag">💰 {_esc(job.salary)}</span>'
    tags_html += f'<span class="tag src-tag" style="color:{color}">{_esc(job.source)}</span>'
    if age:
        tags_html += f'<span class="tag">🕐 {_esc(age)}</span>'
    for t in (job.tags or [])[:5]:
        tags_html += f'<span class="tag">{_esc(t)}</span>'

    return (
        f'<a class="job-card{fresher_cls}" href="{_esc(job.url)}" target="_blank" rel="noopener"'
        f' style="--stripe:{color}">'
        f'<div class="job-title">{_esc(job.title)}</div>'
        f'<div class="job-company">'
        f'<span>{_esc(job.company)}</span>'
        + (f'<span class="text-3" style="color:var(--text-3)">·</span>'
           f'<span style="color:var(--text-3);font-size:12.5px">{_esc(job.location)}</span>'
           if job.location else '')
        + f'</div>'
        f'<div class="job-meta">{tags_html}</div>'
        f'</a>'
    )


# ── Section theo nhóm nghề ───────────────────────────────────────────────────

def _section(cat: str, jobs: list, today: date, new_ids: set[str] | None) -> str:
    label = CATEGORY_LABELS.get(cat, cat)
    icon = CATEGORY_ICONS.get(cat, "💼")
    gradient = CAT_GRADIENTS.get(cat, "var(--card)")

    cards = "".join(
        _job_html(j, today, is_new=(new_ids is None or j.job_id in new_ids))
        for j in jobs
    )
    if not cards:
        cards = '<div class="empty-state">Chưa có tin nào hôm nay.</div>'

    return (
        f'<div class="cat" data-cat="{_esc(cat)}">'
        f'<div class="cat-head">'
        f'<div class="cat-icon" style="background:{gradient}">{icon}</div>'
        f'<span class="cat-name">{_esc(label)}</span>'
        f'<span class="badge-count">{len(jobs)} tin</span>'
        f'</div>'
        f'{cards}'
        f'</div>'
    )


# ── Stat grid ────────────────────────────────────────────────────────────────

def _stats_html(
    total: int,
    new_count: int,
    fresher_count: int,
    sources_active: int,
    by_cat: dict[str, int],
) -> str:
    def stat(val: int, label: str, color: str, accent: str) -> str:
        return (
            f'<div class="stat" style="--c:{color};--accent:{accent}">'
            f'<div class="stat-val">{val}</div>'
            f'<div class="stat-label">{label}</div>'
            f'</div>'
        )

    grid = (
        stat(total,         "Tin thực tập",   "var(--text)",  "var(--green)")
        + stat(new_count,   "Đăng hôm nay",   "var(--green)", "var(--green)")
        + stat(fresher_count,"Fresher",        "var(--amber)", "var(--amber)")
        + stat(sources_active,"Nguồn có tin",  "var(--brand)", "var(--brand)")
    )

    chips = ""
    for cat in CATEGORY_ORDER:
        label = CATEGORY_LABELS.get(cat, cat)
        icon  = CATEGORY_ICONS.get(cat, "")
        count = by_cat.get(cat, 0)
        color = {
            "devops":       "#f97316",
            "backend_java": "#8b5cf6",
            "data_engineer":"#06b6d4",
        }.get(cat, "#9aa0b4")
        chips += (
            f'<span class="chip">'
            f'<span class="dot" style="background:{color}"></span>'
            f'{icon} {_esc(label)} <strong>{count}</strong>'
            f'</span>'
        )

    return f'<div class="stats">{grid}</div><div class="chips">{chips}</div>'


# ── Biểu đồ xu hướng 14 ngày ─────────────────────────────────────────────────

def _trend_html(history: list[dict], today_count: int, today: date) -> str:
    """history: danh sách {date, count} từ data.json, đã sắp xếp tăng dần."""
    # Lấy 14 ngày gần nhất (bao gồm hôm nay)
    hist_map: dict[str, int] = {r["date"]: r["count"] for r in history}
    from datetime import timedelta
    days = [(today - timedelta(days=13 - i)) for i in range(14)]
    counts = [
        today_count if d == today else hist_map.get(str(d), 0)
        for d in days
    ]
    max_c = max(counts) if counts else 1
    max_c = max_c or 1  # tránh chia 0

    bars = ""
    labels = ""
    for i, (d, c) in enumerate(zip(days, counts)):
        pct = round(c / max_c * 100)
        is_today = "today" if d == today else ("zero" if c == 0 else "")
        bars += (
            f'<div class="chart-col {is_today}">'
            f'<div class="chart-val">{c if c else ""}</div>'
            f'<div class="chart-bar" style="height:{max(pct,3)}%"></div>'
            f'</div>'
        )
        # Hiển thị nhãn ngày mỗi 3 cột hoặc hôm nay
        lbl = str(d.day) if (i % 3 == 0 or d == today) else ""
        labels += f'<div>{lbl}</div>'

    return (
        f'<div class="chart-card">'
        f'<div class="chart-title">📈 Xu hướng 14 ngày</div>'
        f'<div class="chart" style="height:100px">{bars}</div>'
        f'<div class="chart-x">{labels}</div>'
        f'</div>'
    )


# ── Filter tabs (CSS-only, không JS) ─────────────────────────────────────────

def _filters_html(by_cat: dict[str, int]) -> str:
    total = sum(by_cat.values())
    tabs = (
        f'<input type="radio" name="fcat" id="f-all" checked>'
        f'<input type="radio" name="fcat" id="f-devops">'
        f'<input type="radio" name="fcat" id="f-java">'
        f'<input type="radio" name="fcat" id="f-data">'
        f'<div class="filter-wrap">'
        f'<div class="filter-tabs">'
        f'<label for="f-all">Tất cả <strong>{total}</strong></label>'
        f'<label for="f-devops">🛠 DevOps <strong>{by_cat.get("devops",0)}</strong></label>'
        f'<label for="f-java">☕ Java <strong>{by_cat.get("backend_java",0)}</strong></label>'
        f'<label for="f-data">📊 Data <strong>{by_cat.get("data_engineer",0)}</strong></label>'
        f'</div>'
    )
    return tabs


# ── Render trang chính ────────────────────────────────────────────────────────

def _render(
    jobs: list,
    fresher_jobs: list,
    today: date,
    new_ids: set[str] | None,
    history: list[dict],
    archives: list[str],
    is_archive: bool = False,
    site_url: str = "",
) -> str:
    by_cat: dict[str, int] = {}
    for j in jobs:
        by_cat[j.category] = by_cat.get(j.category, 0) + 1

    active_sources = len({j.source for j in jobs})
    new_count = len(jobs) if new_ids is None else sum(
        1 for j in jobs if j.job_id in new_ids
    )

    today_str = today.strftime("%d/%m/%Y")
    today_iso = str(today)

    # ── Header
    if is_archive:
        header_title = f'<span class="h1-accent">{today_str}</span>'
        sub_text = "Lưu trữ tin thực tập"
    else:
        header_title = 'Tin thực tập <span class="h1-accent">IT Hà Nội</span>'
        sub_text = "DevOps · Backend Java · Data Engineer — tổng hợp hàng ngày"

    back_btn = ""
    if is_archive and site_url:
        back_btn = f'<a class="back-link" href="{_esc(site_url)}">← Trang chính</a>'

    header_html = (
        f'<header>'
        f'<div class="wrap">'
        f'<div class="badge"><span class="badge-dot"></span>Cập nhật hàng ngày</div>'
        f'<h1>{header_title}</h1>'
        f'<p class="sub">{sub_text}</p>'
        f'<div class="meta-row">'
        f'<span>📅 {today_str}</span>'
        f'<span>🔢 {len(jobs)} tin intern</span>'
        + (f'<span>🆕 {new_count} tin mới</span>' if new_count and not is_archive else '')
        + f'</div>'
        f'{back_btn}'
        f'</div>'
        f'</header>'
    )

    # ── Stats
    stats_html = _stats_html(len(jobs), new_count, len(fresher_jobs), active_sources, by_cat)

    # ── Trend chart (chỉ trang chính)
    trend_html = ""
    if not is_archive:
        trend_html = _trend_html(history, len(jobs), today)

    # ── Sections section heading + filter
    filter_html = _filters_html(by_cat)

    cats_html = ""
    for cat in CATEGORY_ORDER:
        cat_jobs = [j for j in jobs if j.category == cat]
        cats_html += _section(cat, cat_jobs, today, new_ids)

    # Đóng filter wrapper
    sections_block = (
        f'{filter_html}'
        f'<div class="cats">'
        f'{cats_html}'
        f'</div>'
        f'</div>'  # đóng .filter-wrap
    )

    # ── Fresher fold
    fresher_html = ""
    if fresher_jobs:
        f_cards = "".join(_job_html(j, today, is_fresher=True) for j in fresher_jobs)
        fresher_html = (
            f'<details class="fresher-fold">'
            f'<summary>'
            f'<span class="fold-arrow">▶</span>'
            f'🌱 Fresher ({len(fresher_jobs)} tin) — Không yêu cầu kinh nghiệm'
            f'</summary>'
            f'<div class="fresher-inner">'
            f'<p class="fresher-note">'
            f'Các tin này yêu cầu 0 năm kinh nghiệm hoặc ghi rõ "fresher welcome".'
            f'</p>'
            f'{f_cards}'
            f'</div>'
            f'</details>'
        )

    # ── Archive links (chỉ trang chính)
    archive_html = ""
    if archives and not is_archive:
        links = "".join(
            f'<a href="archive/{_esc(a)}.html">{_esc(a)}</a>'
            for a in sorted(archives, reverse=True)[:30]
        )
        archive_html = (
            f'<div class="sec-head">'
            f'<div class="sec-line sec-head-line"></div>'
            f'<div class="sec-title">📂 Lưu trữ</div>'
            f'<div class="sec-head-line"></div>'
            f'</div>'
            f'<div class="arch-grid">{links}</div>'
        )

    body = (
        f'{header_html}'
        f'<main class="wrap">'
        f'{stats_html}'
        + (f'<div class="sec-head"><div class="sec-head-line"></div>'
           f'<div class="sec-title">📈 Xu hướng</div>'
           f'<div class="sec-head-line"></div></div>{trend_html}' if trend_html else '')
        + f'<div class="sec-head">'
        f'<div class="sec-head-line"></div>'
        f'<div class="sec-title">💼 Danh sách tin</div>'
        f'<div class="sec-head-line"></div>'
        f'</div>'
        f'{sections_block}'
        + (f'<div class="sec-head">'
           f'<div class="sec-head-line"></div>'
           f'<div class="sec-title">🌱 Fresher</div>'
           f'<div class="sec-head-line"></div>'
           f'</div>{fresher_html}' if fresher_html else '')
        + f'{archive_html}'
        f'<footer>Dữ liệu tổng hợp tự động từ ITviec, VietnamWorks, Glints, LinkedIn.</footer>'
        f'</main>'
    )

    return (
        f'<!doctype html>'
        f'<html lang="vi">'
        f'<head>'
        f'<meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Thực tập IT Hà Nội – {today_str}</title>'
        f'<style>{_CSS}</style>'
        f'</head>'
        f'<body>{body}</body>'
        f'</html>'
    )


# ── Lịch sử & lưu trữ ────────────────────────────────────────────────────────

def _load_history(data_file: "Path") -> list[dict]:
    """Đọc data.json → list[{date, count}], tạo file rỗng nếu chưa có."""
    if not data_file.exists():
        return []
    try:
        with data_file.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        log.warning("data.json lỗi, khởi tạo lại.")
        return []


def _prune_archive(archive_dir: "Path", keep: int) -> list[str]:
    """Giữ lại `keep` bản archive gần nhất, xoá cũ hơn. Trả danh sách ngày còn lại."""
    pages = sorted(archive_dir.glob("????-??-??.html"))
    for old in pages[:-keep] if keep < len(pages) else []:
        old.unlink(missing_ok=True)
        log.info("Xoá archive cũ: %s", old.name)
    remaining = sorted(archive_dir.glob("????-??-??.html"))
    return [p.stem for p in remaining]


# ── Entry point ───────────────────────────────────────────────────────────────

def build(
    jobs: list,
    fresher_jobs: list,
    today: date,
    new_ids: set[str] | None = None,
    site_url: str = "",
) -> str:
    """Sinh toàn bộ trang web, trả về URL trang chính.

    Tạo / cập nhật:
      docs/index.html
      docs/archive/{today}.html
      docs/data.json
      docs/.nojekyll
    """
    from pathlib import Path

    # Ưu tiên tham số truyền vào, fallback về PAGES_URL trong config.
    # KHÔNG được trả về đường dẫn local — Telegram yêu cầu URL hợp lệ.
    resolved_url = site_url or PAGES_URL

    out_dir = Path(SITE_DIR)
    archive_dir = out_dir / "archive"
    out_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(exist_ok=True)

    # Tắt Jekyll
    nojekyll = out_dir / ".nojekyll"
    if not nojekyll.exists():
        nojekyll.touch()

    # Tải lịch sử
    data_file = out_dir / "data.json"
    history = _load_history(data_file)

    # Cập nhật / thêm bản ghi hôm nay
    today_iso = str(today)
    hist_map = {r["date"]: r for r in history}
    hist_map[today_iso] = {"date": today_iso, "count": len(jobs)}
    history = sorted(hist_map.values(), key=lambda r: r["date"])

    with data_file.open("w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    # Lấy danh sách archive sau khi prune
    archives = _prune_archive(archive_dir, ARCHIVE_KEEP_DAYS)

    # Render trang chính
    index_html = _render(
        jobs, fresher_jobs, today, new_ids, history, archives,
        is_archive=False, site_url=resolved_url,
    )
    (out_dir / "index.html").write_text(index_html, encoding="utf-8")
    log.info("Đã ghi docs/index.html (%d jobs)", len(jobs))

    # Render trang lưu trữ ngày hôm nay
    archive_html = _render(
        jobs, fresher_jobs, today, new_ids, history, archives,
        is_archive=True, site_url=resolved_url,
    )
    (archive_dir / f"{today_iso}.html").write_text(archive_html, encoding="utf-8")
    log.info("Đã ghi docs/archive/%s.html", today_iso)

    return resolved_url
