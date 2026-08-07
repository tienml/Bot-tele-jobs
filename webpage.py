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

# Màu nhận dạng từng nguồn, giúp mắt phân biệt nhanh khi cuộn danh sách dài.
SOURCE_COLORS = {
    "ITviec": "#f2705f",
    "VietnamWorks": "#57a5f0",
    "Glints": "#2ecfa4",
    "LinkedIn": "#7c8cff",
}

_CSS = """
:root {
  --bg: #0b0d12;
  --bg-2: #0f1218;
  --panel: rgba(255,255,255,.032);
  --panel-2: rgba(255,255,255,.055);
  --line: rgba(255,255,255,.085);
  --line-2: rgba(255,255,255,.14);
  --text: #f2f4f9;
  --text-2: #b9c0d0;
  --text-3: #7b8496;
  --brand: #7aa2ff;
  --intern: #35e0a1;
  --fresher: #ffb454;
  --r: 16px;
  --r-sm: 11px;
  --shadow: 0 1px 1px rgba(0,0,0,.4), 0 14px 40px -22px rgba(0,0,0,.9);
  --glow: radial-gradient(120% 100% at 15% 0%, rgba(122,162,255,.16), transparent 60%),
          radial-gradient(90% 80% at 90% 0%, rgba(53,224,161,.10), transparent 55%);
}
@media (prefers-color-scheme: light) {
  :root {
    --bg: #fbfbfd;
    --bg-2: #f2f4f9;
    --panel: #ffffff;
    --panel-2: #f5f7fb;
    --line: #e6e9f0;
    --line-2: #d4d9e4;
    --text: #10131a;
    --text-2: #444c5e;
    --text-3: #737c8d;
    --brand: #2b5fd9;
    --intern: #08996a;
    --fresher: #b56a10;
    --shadow: 0 1px 1px rgba(16,20,30,.04), 0 14px 34px -24px rgba(16,20,30,.4);
    --glow: radial-gradient(120% 100% at 15% 0%, rgba(43,95,217,.09), transparent 60%),
            radial-gradient(90% 80% at 90% 0%, rgba(8,153,106,.07), transparent 55%);
  }
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  padding: 0 0 80px;
  background: var(--bg);
  color: var(--text);
  font: 400 16px/1.62 ui-sans-serif, -apple-system, BlinkMacSystemFont,
        "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}
.wrap { max-width: 940px; margin: 0 auto; padding: 0 20px; }
a { color: var(--brand); }

/* ---------- Header ---------- */
header.top {
  position: relative;
  overflow: hidden;
  background: var(--bg-2);
  background-image: var(--glow);
  border-bottom: 1px solid var(--line);
  padding: 44px 0 34px;
  margin-bottom: 30px;
}
.eyebrow {
  display: inline-flex; align-items: center; gap: 7px;
  font-size: 11.5px; font-weight: 700; letter-spacing: .13em;
  text-transform: uppercase; color: var(--text-3);
  border: 1px solid var(--line); border-radius: 999px;
  padding: 4px 12px; margin-bottom: 15px;
}
.eyebrow .live {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--intern); box-shadow: 0 0 0 3px rgba(53,224,161,.18);
}
h1 {
  font-size: clamp(27px, 6vw, 42px);
  line-height: 1.1;
  margin: 0 0 12px;
  letter-spacing: -.03em;
  font-weight: 750;
}
h1 .acc {
  background: linear-gradient(96deg, var(--brand), var(--intern));
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
}
.tagline { color: var(--text-2); font-size: 15.5px; margin: 0; }
.stamp {
  color: var(--text-3); font-size: 13px; margin: 16px 0 0;
  display: flex; flex-wrap: wrap; gap: 6px 14px;
}

/* ---------- Ô số liệu ---------- */
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 13px;
}
.stat {
  position: relative;
  overflow: hidden;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--r);
  box-shadow: var(--shadow);
  padding: 17px 18px 15px;
}
.stat::after {
  content: ""; position: absolute; inset: 0 0 auto 0; height: 2px;
  background: var(--bar, var(--line-2));
}
.stat .n {
  font-size: 34px; font-weight: 750; line-height: 1.05;
  letter-spacing: -.035em; font-variant-numeric: tabular-nums;
}
.stat .l {
  color: var(--text-3); font-size: 11.5px; font-weight: 700;
  text-transform: uppercase; letter-spacing: .08em; margin-top: 5px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.stat.zero .n { color: var(--text-3); }

/* ---------- Chip ---------- */
.chiprow { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 15px; }
.chip {
  display: inline-flex; align-items: center; gap: 7px;
  background: var(--panel); border: 1px solid var(--line);
  border-radius: 999px; padding: 5px 13px;
  font-size: 13px; color: var(--text-2);
}
.chip b { color: var(--text); font-variant-numeric: tabular-nums; }
.dot { width: 7px; height: 7px; border-radius: 50%; flex: none; }

/* ---------- Tiêu đề mục ---------- */
h2 {
  display: flex; align-items: baseline; gap: 11px;
  font-size: 12.5px; font-weight: 750; text-transform: uppercase;
  letter-spacing: .11em; color: var(--text-3);
  margin: 44px 0 16px;
}
h2::after {
  content: ""; flex: 1; height: 1px; background: var(--line);
}
h3 {
  display: flex; align-items: center; gap: 9px;
  font-size: 16px; font-weight: 700; letter-spacing: -.01em;
  margin: 26px 0 11px;
}
h3 .ic {
  display: grid; place-items: center;
  width: 26px; height: 26px; flex: none;
  border-radius: 8px; font-size: 13px;
  background: var(--panel-2); border: 1px solid var(--line);
}
.count {
  font-size: 11.5px; font-weight: 700; color: var(--text-3);
  background: var(--panel-2); border: 1px solid var(--line);
  border-radius: 999px; padding: 2px 9px;
  font-variant-numeric: tabular-nums;
}

/* ---------- Thẻ job ---------- */
.job {
  position: relative;
  display: block;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--r);
  box-shadow: var(--shadow);
  padding: 16px 18px 15px 20px;
  margin-bottom: 11px;
  color: inherit;
  text-decoration: none;
  transition: border-color .16s ease, background .16s ease, transform .16s ease;
}
.job::before {
  content: ""; position: absolute; left: 0; top: 14px; bottom: 14px;
  width: 3px; border-radius: 0 3px 3px 0;
  background: var(--intern);
}
.job.fresher::before { background: var(--fresher); }
.job:hover {
  border-color: var(--line-2);
  background: var(--panel-2);
  transform: translateY(-1px);
}
.job:hover .title { color: var(--brand); }
.job .title {
  font-size: 16.5px; font-weight: 680; line-height: 1.38;
  letter-spacing: -.012em;
  transition: color .16s ease;
}
.job .company {
  color: var(--text-2); font-size: 14px; margin-top: 4px;
  display: flex; align-items: center; gap: 7px;
}
.job .meta {
  display: flex; flex-wrap: wrap; align-items: center;
  gap: 6px 7px; margin-top: 11px;
  font-size: 12.5px; color: var(--text-3);
}
.tag {
  display: inline-flex; align-items: center; gap: 5px;
  border-radius: 7px; padding: 3px 9px;
  background: var(--panel-2); border: 1px solid var(--line);
  white-space: nowrap;
}
.tag.src { font-weight: 650; color: var(--text-2); }
.tag.hot {
  color: var(--intern); font-weight: 650;
  border-color: color-mix(in srgb, var(--intern) 34%, transparent);
  background: color-mix(in srgb, var(--intern) 11%, transparent);
}
.tag.pay {
  color: var(--intern); font-weight: 650;
  border-color: color-mix(in srgb, var(--intern) 26%, transparent);
}

/* ---------- Lọc theo nhóm (không JS) ---------- */
.filters { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 20px; }
.filters input { position: absolute; opacity: 0; pointer-events: none; }
.filters label {
  cursor: pointer; user-select: none;
  display: inline-flex; align-items: center; gap: 7px;
  background: var(--panel); border: 1px solid var(--line);
  border-radius: 999px; padding: 7px 15px;
  font-size: 13.5px; font-weight: 600; color: var(--text-2);
  transition: border-color .15s ease, color .15s ease, background .15s ease;
}
.filters label:hover { border-color: var(--line-2); color: var(--text); }
/* Radio nào đang chọn thì nhãn tương ứng sáng lên. Mọi radio đều nằm
   trước .filters và .cats trong DOM nên `~` chạm được tới cả hai. */
#f-all:checked    ~ .filters label[for="f-all"],
#f-devops:checked ~ .filters label[for="f-devops"],
#f-java:checked   ~ .filters label[for="f-java"],
#f-data:checked   ~ .filters label[for="f-data"] {
  background: var(--text); color: var(--bg); border-color: var(--text);
}
/* Mặc định ẩn hết, rồi hiện lại nhóm khớp lựa chọn. */
#f-devops:checked ~ .cats .cat:not([data-cat="devops"]),
#f-java:checked   ~ .cats .cat:not([data-cat="backend_java"]),
#f-data:checked   ~ .cats .cat:not([data-cat="data_engineer"]) { display: none; }

/* ---------- Biểu đồ xu hướng ---------- */
.chart-box {
  background: var(--panel); border: 1px solid var(--line);
  border-radius: var(--r); box-shadow: var(--shadow);
  padding: 18px 18px 12px;
}
.chart { display: flex; align-items: flex-end; gap: 6px; height: 130px; }
.chart .col {
  flex: 1; height: 100%; display: flex; flex-direction: column;
  justify-content: flex-end; align-items: center; gap: 5px;
}
.chart .v {
  font-size: 11px; color: var(--text-3); font-variant-numeric: tabular-nums;
}
.chart .bar {
  width: 100%; min-height: 3px; border-radius: 6px 6px 2px 2px;
  background: linear-gradient(180deg, var(--intern),
              color-mix(in srgb, var(--intern) 22%, transparent));
}
.chart .col.zero .bar { background: var(--line); }
.chart .col.last .bar {
  background: linear-gradient(180deg, var(--brand),
              color-mix(in srgb, var(--brand) 22%, transparent));
}
.xaxis { display: flex; gap: 6px; margin-top: 9px; }
.xaxis div {
  flex: 1; text-align: center; font-size: 10.5px; color: var(--text-3);
  font-variant-numeric: tabular-nums;
}

/* ---------- Mục fresher thu gọn ---------- */
details.fold {
  background: var(--panel); border: 1px solid var(--line);
  border-radius: var(--r); box-shadow: var(--shadow); padding: 0 18px;
}
details.fold > summary {
  cursor: pointer; list-style: none;
  display: flex; align-items: center; gap: 10px;
  padding: 17px 0; font-size: 15.5px; font-weight: 700;
}
details.fold > summary::-webkit-details-marker { display: none; }
details.fold > summary::before {
  content: "›"; color: var(--fresher); font-size: 20px; line-height: 1;
  transition: transform .18s ease;
}
details.fold[open] > summary::before { transform: rotate(90deg); }
details.fold .inner { padding-bottom: 16px; }
details.fold .note {
  color: var(--text-3); font-size: 13.5px; margin: 0 0 16px;
  padding-left: 12px; border-left: 2px solid var(--line-2);
}
details.fold .job { background: var(--panel-2); }

/* ---------- Khác ---------- */
.empty {
  color: var(--text-3); font-size: 14.5px; text-align: center;
  background: var(--panel); border: 1px dashed var(--line-2);
  border-radius: var(--r); padding: 30px 20px;
}
.arch { display: flex; flex-wrap: wrap; gap: 8px; list-style: none;
        padding: 0; margin: 0; }
.arch a {
  display: block; background: var(--panel); border: 1px solid var(--line);
  border-radius: var(--r-sm); padding: 7px 12px; font-size: 13.5px;
  color: var(--text-2); text-decoration: none;
  font-variant-numeric: tabular-nums;
}
.arch a:hover { border-color: var(--line-2); color: var(--text); }
.backlink {
  display: inline-flex; align-items: center; gap: 7px;
  margin-top: 34px; font-size: 14.5px; text-decoration: none;
}
.backlink:hover { text-decoration: underline; }
footer {
  margin-top: 52px; padding-top: 20px;
  border-top: 1px solid var(--line);
  color: var(--text-3); font-size: 13px;
}
@media (max-width: 560px) {
  header.top { padding: 32px 0 26px; }
  .grid { grid-template-columns: repeat(2, 1fr); gap: 10px; }
  .stat .n { font-size: 28px; }
  .job { padding: 14px 15px 13px 17px; }
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
    """Một thẻ job. Cả thẻ là một link để bấm ở đâu cũng mở được tin."""
    tags: list[str] = []

    age = _age_label(job, today)
    if age:
        is_new = job.posted_date is not None and (today - job.posted_date).days <= 1
        tags.append(
            f'<span class="tag{" hot" if is_new else ""}">{"✦" if is_new else "🕒"} '
            f"{_esc(age)}</span>"
        )
    if job.location:
        tags.append(f'<span class="tag">📍 {_esc(job.location)}</span>')
    if job.salary:
        tags.append(f'<span class="tag pay">💰 {_esc(job.salary)}</span>')
    tags.append(
        f'<span class="tag src">'
        f'<i class="dot" style="background:{_source_color(job.source)}"></i>'
        f"{_esc(job.source)}</span>"
    )

    company = ""
    if job.company:
        company = (
            f'<div class="company">'
            f'<i class="dot" style="background:{_source_color(job.source)}"></i>'
            f"{_esc(job.company)}</div>"
        )
    klass = f"job {css_class}".strip()
    return (
        f'<a class="{klass}" href="{_esc(job.url)}"'
        f' target="_blank" rel="noopener">'
        f'<div class="title">{_esc(job.title)}</div>'
        f"{company}"
        f'<div class="meta">{"".join(tags)}</div>'
        f"</a>"
    )


def _section(cat: str, jobs: list, today: date, css_class: str = "") -> str:
    """Một nhóm nghề có tiêu đề. Trả về chuỗi rỗng nếu nhóm trống.

    `data-cat` để bộ lọc CSS ẩn/hiện được nhóm mà không cần JavaScript.
    """
    if not jobs:
        return ""
    icon = CATEGORY_ICONS.get(cat, "•")
    label = CATEGORY_LABELS.get(cat, cat)
    cards = "".join(_job_html(j, today, css_class) for j in jobs)
    return (
        f'<div class="cat" data-cat="{_esc(cat)}">'
        f'<h3><span class="ic">{icon}</span>{_esc(label)}'
        f'<span class="count">{len(jobs)}</span></h3>'
        f"{cards}</div>"
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
        bar = f' style="--bar:{color}"' if color and value else ""
        zero = " zero" if not value else ""
        return (
            f'<div class="stat{zero}"{bar}><div class="n"{style}>{value}</div>'
            f'<div class="l">{label}</div></div>'
        )

    cells = [
        cell(len(intern_jobs), "Thực tập", "var(--intern)"),
        cell(fresh_today, "Đăng hôm nay", "var(--brand)"),
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
    cols = []
    for i, v in enumerate(values):
        klass = "col"
        if not v:
            klass += " zero"
        if i == len(values) - 1:
            klass += " last"
        cols.append(
            f'<div class="{klass}"><span class="v">{v}</span>'
            f'<div class="bar" style="height:{max(3, round(v / peak * 100))}%"></div>'
            f"</div>"
        )
    labels = "".join(f"<div>{d[8:10]}/{d[5:7]}</div>" for d in days)
    return (
        f"<h2>Xu hướng {len(days)} ngày</h2>"
        f'<div class="chart-box"><div class="chart">{"".join(cols)}</div>'
        f'<div class="xaxis">{labels}</div></div>'
    )


def _filters_html(intern_jobs: list) -> str:
    """Nút lọc theo nhóm nghề, làm bằng radio ẩn + CSS (không cần JS).

    Các radio phải nằm TRƯỚC .filters và .cats trong DOM để selector
    `:checked ~` chạm được tới chúng.
    """
    counts = {
        cat: sum(1 for j in intern_jobs if j.category == cat)
        for cat in CATEGORY_ORDER
    }
    ids = {"devops": "f-devops", "backend_java": "f-java", "data_engineer": "f-data"}

    inputs = ['<input type="radio" name="cat" id="f-all" checked>']
    labels = [f'<label for="f-all">Tất cả <span class="count">'
              f'{len(intern_jobs)}</span></label>']
    for cat in CATEGORY_ORDER:
        if not counts[cat]:
            continue  # nhóm trống thì không cần nút lọc
        fid = ids[cat]
        inputs.append(f'<input type="radio" name="cat" id="{fid}">')
        labels.append(
            f'<label for="{fid}">{CATEGORY_ICONS.get(cat, "")} '
            f'{_esc(CATEGORY_LABELS.get(cat, cat))}'
            f'<span class="count">{counts[cat]}</span></label>'
        )
    if len(labels) < 3:
        return ""  # chỉ một nhóm có tin: nút lọc vô nghĩa
    return "".join(inputs) + f'<div class="filters">{"".join(labels)}</div>'


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
        sections = "".join(
            _section(cat, by_cat.get(cat, []), today) for cat in CATEGORY_ORDER
        )
        # Bọc chung một khối để radio lọc ở trên chạm được bằng `~ .cats`.
        body.append(
            f'<div class="filter-scope">{_filters_html(intern_jobs)}'
            f'<div class="cats">{sections}</div></div>'
        )
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
        inner += [
            _section(cat, fresher_by_cat.get(cat, []), today, "fresher")
            for cat in CATEGORY_ORDER
        ]
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
    heading = "Việc thực tập IT Hà Nội"
    title = f"{heading} – {today.strftime('%d/%m/%Y')}"
    n_total = len(intern_jobs) + len(fresher_jobs)

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
<span class="eyebrow"><i class="live"></i>Cập nhật hằng ngày 8:00</span>
<h1>Việc <span class="acc">thực tập IT</span><br>tại Hà Nội</h1>
<p class="tagline">🛠 DevOps · ☕ Backend Java · 📊 Data Engineer</p>
<p class="stamp"><span>📅 Dữ liệu ngày {today.strftime('%d/%m/%Y')}</span>
<span>🔄 Cập nhật {stamp}</span>
<span>📦 {n_total} tin</span></p>
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
