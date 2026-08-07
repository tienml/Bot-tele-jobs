"""Cấu hình bot. Đọc từ biến môi trường, có fallback từ file .env."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent


def _load_dotenv(path: Path) -> None:
    """Nạp file .env đơn giản vào os.environ (không ghi đè biến đã có)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(BASE_DIR / ".env")

# Token lấy từ @BotFather
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Múi giờ và giờ gửi tin mỗi ngày
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Ho_Chi_Minh")
DAILY_HOUR = int(os.environ.get("DAILY_HOUR", "8"))
DAILY_MINUTE = int(os.environ.get("DAILY_MINUTE", "0"))

# Số job tiềm năng nhất hiển thị kèm nút bấm
TOP_N = int(os.environ.get("TOP_N", "5"))

# Job cũ hơn số ngày này sẽ bị loại
MAX_AGE_DAYS = int(os.environ.get("MAX_AGE_DAYS", "21"))

DB_PATH = Path(os.environ.get("DB_PATH", BASE_DIR / "jobs.db"))

REQUEST_TIMEOUT = 30
HTTP_TIMEOUT = REQUEST_TIMEOUT   # alias dùng trong scrapers

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# --- Nguồn ITviec -------------------------------------------------------
# Các từ khoá truy vấn (khớp URL slug: /it-jobs/{query}?city=ha-noi).
ITVIEC_QUERIES = ["intern", "fresher", "devops", "java", "data-engineer"]

# --- Nguồn VietnamWorks --------------------------------------------------
# Chỉ dùng cụm ngắn; cụm dài > 2 từ thường trả về 0 hit từ API.
VNW_QUERIES = ["intern", "thực tập", "devops", "java", "data engineer"]
VNW_HITS_PER_PAGE = 100

# --- Nguồn Glints --------------------------------------------------------
# Glints bỏ qua filter địa điểm trên URL nên phải quét rộng rồi lọc Hà Nội
# ở filters.py. Mỗi trang trả 20-30 tin, 3 trang là đủ phủ.
GLINTS_QUERIES = [
    "intern", "thực tập", "devops", "java", "data engineer", "backend",
]
GLINTS_PAGES = 3

# --- Nguồn LinkedIn ------------------------------------------------------
# Dùng endpoint "jobs-guest" — LinkedIn dành riêng cho khách chưa đăng nhập,
# trả HTML danh sách job nên không cần token và không vướng authwall.
# Mỗi lần trả 10 tin, phân trang bằng tham số `start` (0, 10, 20...).
#
# Quan trọng: LinkedIn tự nới lỏng truy vấn nhiều từ. Query "devops intern"
# bị hiểu thành "devops" nên trả về toàn tin Senior/Middle — 110 tin lấy về
# mà không tin nào là thực tập. Ngược lại query "intern" thuần cho tỉ lệ
# đúng cấp bậc rất cao (66/75 tin là thực tập thật).
# Vì vậy: chỉ hỏi LinkedIn theo CẤP BẬC, còn lọc NGÀNH để filters.py làm.
LINKEDIN_QUERIES = [
    "intern",
    "internship",
    "thực tập",
    "thực tập sinh",
]
LINKEDIN_LOCATION = "Hanoi, Hanoi, Vietnam"
LINKEDIN_PAGES = 10         # 10 x 10 = 100 tin mỗi truy vấn
LINKEDIN_TPR = "r2592000"   # chỉ tin đăng trong 30 ngày gần nhất

# cityId = 24 là Hà Nội (xác minh qua facet API).
HANOI_CITY_ID = 24

# Thời gian nghỉ giữa các request để tránh bị chặn (giây).
REQUEST_DELAY = 1.2
