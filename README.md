# Telegram Bot – Tin tuyển dụng Intern IT Hà Nội

Bot tự động gửi tin tuyển dụng intern/fresher cho các vị trí **DevOps**, **Backend Java**, **Data Engineer** ở Hà Nội mỗi ngày. Kèm top 5 job tiềm năng nhất có nút bấm dẫn thẳng tới tin.

## Nguồn dữ liệu
| Nguồn | Phương thức |
|---|---|
| **ITviec** | Scrape HTML (selectors ổn định) |
| **VietnamWorks** | Public JSON API (phân trang) |

## Cài đặt

```bash
pip install -r requirements.txt
```

## Cấu hình

```bash
cp .env.example .env
```

Mở `.env` và điền:
```env
BOT_TOKEN=your_token_here   # Lấy từ @BotFather
DAILY_HOUR=8                # Giờ gửi tin (7 giờ sáng)
DAILY_MINUTE=0
TOP_N=5                     # Số nút bấm job nổi bật
MAX_AGE_DAYS=21             # Loại job cũ hơn 21 ngày
```

### Lấy BOT_TOKEN
1. Mở Telegram, tìm **@BotFather**
2. Gửi `/newbot`, đặt tên và username
3. Sao chép token vào `.env`

## Chạy bot

```bash
python bot.py
```

## Lệnh Telegram
| Lệnh | Mô tả |
|---|---|
| `/start` | Đăng ký nhận tin hàng ngày |
| `/jobs`  | Xem tin ngay lập tức |
| `/stop`  | Huỷ đăng ký |

## Cấu trúc dự án

```
bot_tele/
├── bot.py                  # Entry point, Telegram handlers + scheduler
├── config.py               # Tất cả cấu hình (đọc từ .env)
├── filters.py              # Logic lọc intern/HN + chấm điểm
├── storage.py              # SQLite: lưu danh sách subscriber
├── sources/
│   ├── base.py             # Kiểu Job + lớp BaseSource
│   ├── itviec.py           # ITviec scraper
│   └── vietnamworks.py     # VietnamWorks API scraper
├── requirements.txt
├── .env.example
└── jobs.db                 # Tạo tự động khi chạy
```

## Chạy nền trên Windows

Dùng Task Scheduler để tự khởi động khi login:

1. Mở **Task Scheduler** → **Create Basic Task**
2. Trigger: **When I log on**
3. Action: **Start a program**
   - Program: `python`
   - Arguments: `d:\bot_tele\bot.py`
   - Start in: `d:\bot_tele`

Hoặc dùng `pm2` (nếu có Node.js):
```bash
npm install -g pm2
pm2 start "python bot.py" --name telegram-job-bot --cwd d:\bot_tele
pm2 save
pm2 startup
```

## Tuỳ chỉnh

### Thêm từ khoá ngành
Mở [filters.py](filters.py) và thêm vào `CATEGORY_KEYWORDS`:
```python
"data_engineer": [
    "data engineer", ...,
    "mlops",           # thêm ở đây
],
```

### Thêm nguồn mới
Tạo `sources/ten_nguon.py` kế thừa `BaseSource`, implement `fetch()` trả về `Iterable[Job]`. Thêm vào `sources/__init__.py` trong `ALL_SOURCES`.

### Thay đổi giờ gửi
```env
DAILY_HOUR=7
DAILY_MINUTE=30
```
