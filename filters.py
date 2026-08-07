"""Lọc theo vị trí/địa điểm/cấp bậc và tính điểm tiềm năng cho job.

Ba nguồn đều không cho phép filter "intern + Hà Nội + đúng ngành" ngay trên
query, nên phần lọc thật nằm ở đây.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date

from sources.base import Job


def normalize(text: str) -> str:
    """Bỏ dấu tiếng Việt, hạ chữ thường để so khớp từ khoá cho chắc."""
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text.lower()).strip()


# --- Cấp bậc: chỉ intern/thực tập ----------------------------------------
# Không lấy fresher, trainee, mới tốt nghiệp — người dùng chỉ muốn thực tập.
INTERN_KEYWORDS = [
    "intern", "internship", "thuc tap", "thuc tap sinh", "tts",
    "sinh vien",    # VietnamWorks ghi "Sinh viên" trong jobLevelVI
    "entry level",  # Một số tin IT ghi "Entry Level"
]

# Từ khoá loại thẳng: các tin senior lọt vào vì search "devops" trả cả tin cao cấp.
SENIOR_KEYWORDS = [
    # "sr" và "mid" viết tắt không có dấu chấm ("Sr Java Developer",
    # "Mid/Sr Java Engineer") nên phải liệt kê cả dạng trần.
    "senior", "sr.", "sr", "lead", "leader", "principal", "staff engineer",
    "manager", "truong nhom", "truong phong", "head of", "director",
    "chuyen gia", "expert", "architect", "giam doc", "mid", "middle",
    "junior-middle", "5+ years", "3+ years", "4+ years",
]

# --- Ngành nghề ----------------------------------------------------------
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "devops": [
        "devops", "sre", "site reliability", "platform engineer", "cloud engineer",
        "infrastructure", "ha tang", "kubernetes", "docker", "ci/cd", "cicd",
        "system engineer", "system admin", "linux engineer", "terraform",
        "van hanh he thong", "cloud ops",
    ],
    # backend_java: chỉ nhận khi có từ khoá Java/Spring tường minh.
    # Lý do: "backend" một mình quá chung — AI Engineer, .NET, Node.js đều
    # dùng tag "backend" nên sẽ bị nhận nhầm nếu để từ khoá quá rộng.
    "backend_java": [
        "java", "spring", "spring boot", "springboot", "j2ee", "jakarta ee",
        "java developer", "java engineer", "java backend", "java intern",
        "lap trinh java",
    ],
    "data_engineer": [
        "data engineer", "data engineering", "etl", "elt", "data pipeline",
        "big data", "spark", "hadoop", "airflow", "data warehouse", "datawarehouse",
        "data platform", "kafka", "dbt", "ky su du lieu",
        # Một số intern ở VN dùng tên "data analyst" nhưng thực chất làm pipeline.
        # "business intelligence" / "bi" cũng nằm giao với data engineering.
        # Lưu ý: "data analysis" KHÔNG đưa vào — đó là skill tag xuất hiện
        # trong hàng trăm tin tài chính/tư vấn không liên quan.
        "data analyst", "analytics engineer", "business intelligence",
        "phan tich du lieu",   # tiếng Việt: "phân tích dữ liệu" trong tiêu đề
    ],
}

CATEGORY_LABELS = {
    "devops": "DevOps",
    "backend_java": "Backend Java",
    "data_engineer": "Data Engineer",
}

# Nghề nằm ngoài phạm vi nhưng hay lọt vào vì trùng tag hạ tầng/dữ liệu
# (helpdesk có tag Linux, tin frontend có tag JavaScript...).
EXCLUDE_KEYWORDS = [
    # Hỗ trợ/vận hành người dùng, không phải devops.
    "helpdesk", "help desk", "it support", "ho tro ky thuat", "cskh",
    # Frontend/mobile: hay có tag JavaScript nên dễ bị nhận nhầm là Java.
    "frontend", "front-end", "front end", "reactjs", "react native",
    "ui/ux", "designer", "thiet ke",
    # AI/ML: khác với Data Engineer, không nằm trong 3 ngành mục tiêu.
    "ai engineer", "machine learning", "ml engineer", "data scientist",
    "nlp engineer", "computer vision", "artificial intelligence",
    # Nhóm nghề khác hẳn.
    "tester", "kiem thu", "business analyst", "marketing",
    "ke toan", "accounting", "nhan su", "tuyen dung", "bien tap",
    "logistics", "supply chain", "xuat nhap khau",
    "le tan", "khach san", "nha hang", "co khi",
    "kien truc", "xay dung", "giao vien", "phien dich",
]
# Cố ý không đưa vào: "ba", "sale", "duoc", "san xuat", "hr", "content"...
# Chúng quá ngắn hoặc trùng từ thông dụng tiếng Việt ("được", "sản xuất"),
# dễ loại oan cả tin đúng ngành.

# --- Địa điểm ------------------------------------------------------------
HANOI_KEYWORDS = ["ha noi", "hanoi", "hn", "cau giay", "thanh xuan", "ba dinh",
                  "dong da", "hoan kiem", "hai ba trung", "nam tu liem",
                  "bac tu liem", "long bien", "hoang mai", "tay ho", "ha dong"]

REMOTE_KEYWORDS = ["remote", "tu xa", "work from home", "wfh", "hybrid"]


class _WordPatternCache(dict):
    """Cache regex theo từ khoá, biên dịch một lần rồi dùng lại."""

    def __missing__(self, needle: str) -> re.Pattern:
        # Từ khoá có ký tự đặc biệt (ci/cd, sr., back-end, 5+ years) phải
        # escape; ranh giới dùng lookaround để không cắt giữa chữ và số.
        pattern = re.compile(
            rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])"
        )
        self[needle] = pattern
        return pattern


_WORD_RE = _WordPatternCache()


def _contains(haystack: str, needles: list[str]) -> bool:
    """Khớp theo ranh giới từ, không phải substring thô.

    Trước đây dùng `n in haystack` nên "java" khớp cả trong "javascript"
    (tin Frontend bị xếp vào Backend Java) và "hn" khớp trong "chuyen".
    """
    return any(_WORD_RE[n].search(haystack) for n in needles)


def is_intern_level(job: Job) -> bool:
    """Chỉ nhận tin intern/thực tập sinh; loại tin senior và non-intern."""
    haystack = normalize(f"{job.title} {' '.join(job.tags)} {job.posted_text}")
    title_norm = normalize(job.title)

    # Tiêu đề có dấu hiệu senior thì loại, kể cả khi có chữ "fresher" ở tag.
    if _contains(title_norm, SENIOR_KEYWORDS):
        return False
    return _contains(haystack, INTERN_KEYWORDS)


def is_excluded(job: Job) -> bool:
    """Loại nghề ngoài phạm vi dù có tag trùng.

    Ví dụ tin IT Support/Helpdesk mang tag Linux nên bị nhận là DevOps.
    Chỉ soi tiêu đề: tag chỉ là công nghệ dùng kèm, không nói lên vị trí.
    """
    return _contains(normalize(job.title), EXCLUDE_KEYWORDS)


def detect_category(job: Job) -> str | None:
    """Xác định job thuộc nhóm nào. Ưu tiên khớp ở tiêu đề rồi mới tới tag."""
    title_norm = normalize(job.title)
    tags_norm = normalize(" ".join(job.tags))

    for scope in (title_norm, tags_norm):
        for category, keywords in CATEGORY_KEYWORDS.items():
            if _contains(scope, keywords):
                return category
    return None


def is_in_hanoi(job: Job) -> bool:
    loc = normalize(job.location)
    if not loc:
        # Không rõ địa điểm: giữ lại, vì nguồn đã được query theo Hà Nội.
        return True
    return _contains(loc, HANOI_KEYWORDS) or _contains(loc, REMOTE_KEYWORDS)


def score_job(job: Job, today: date | None = None) -> int:
    """Điểm tiềm năng: tin mới, đúng intern, có lương, nhiều tag khớp thì điểm cao.

    Dùng để chọn ra TOP_N job đáng chú ý nhất.
    """
    today = today or date.today()
    score = 0
    title_norm = normalize(job.title)
    haystack = normalize(f"{job.title} {' '.join(job.tags)}")

    # Đúng từ khoá intern ngay ở tiêu đề là tín hiệu mạnh nhất.
    if _contains(title_norm, ["intern", "thuc tap", "internship", "tts"]):
        score += 40
    elif _contains(haystack, INTERN_KEYWORDS):  # sinh vien, entry level ở tag/level
        score += 15

    # Độ mới của tin.
    if job.posted_date:
        age = (today - job.posted_date).days
        if age <= 1:
            score += 30
        elif age <= 3:
            score += 22
        elif age <= 7:
            score += 14
        elif age <= 14:
            score += 6

    # Có công khai lương thì đáng chú ý hơn.
    if job.salary and "sign in" not in job.salary.lower():
        score += 12

    # Số từ khoá ngành khớp được (job càng khớp sâu càng điểm cao).
    if job.category:
        matched = sum(
            1
            for kw in CATEGORY_KEYWORDS[job.category]
            if _WORD_RE[kw].search(haystack)
        )
        score += min(matched * 4, 16)

    # Ưu tiên nhẹ tin nêu rõ ở Hà Nội.
    if _contains(normalize(job.location), HANOI_KEYWORDS):
        score += 5

    return score


def filter_and_score(jobs: list[Job], today: date | None = None) -> list[Job]:
    """Lọc intern + Hà Nội + đúng ngành, gộp trùng, tính điểm, sắp xếp giảm dần."""
    today = today or date.today()
    result: list[Job] = []
    seen: dict[str, Job] = {}

    for job in jobs:
        if not is_intern_level(job) or not is_in_hanoi(job):
            continue
        if is_excluded(job):
            continue
        category = detect_category(job)
        if not category:
            continue

        job.category = category
        job.score = score_job(job, today)

        # Job trùng giữa các nguồn: giữ bản điểm cao hơn.
        key = job.dedupe_key
        if key in seen:
            if job.score > seen[key].score:
                seen[key] = job
            continue
        seen[key] = job

    result = sorted(seen.values(), key=lambda j: j.score, reverse=True)
    return result
