# Telegram Bot – Tin tuyển dụng Thực tập IT Hà Nội

Bot tự động gửi tin tuyển dụng **thực tập** (intern) cho các vị trí **DevOps**, **Backend Java**, **Data Engineer** ở Hà Nội mỗi sáng. Message gồm top 5 tin tiềm năng nhất có nút bấm dẫn thẳng tới bài tuyển dụng, kèm một nút mở trang thống kê xem toàn bộ tin của ngày.

Chỉ tin **thực tập** được gửi qua Telegram. Tin **fresher/junior** vẫn được thu về nhưng chỉ liệt kê trên trang thống kê để tham khảo.

## Nguồn dữ liệu

| Nguồn | Phương thức | Ghi chú |
|---|---|---|
| **ITviec** | Scrape HTML qua TLS giả lập Chrome | Selector `div.job-card`. Xem lưu ý bên dưới |
| **VietnamWorks** | Public JSON API | `ms.vietnamworks.com/job-search`, lọc Hà Nội bằng `cityId=24` |
| **Glints** | JSON trong `__NEXT_DATA__` | Bỏ qua filter địa điểm trên URL nên phải lọc Hà Nội ở `filters.py` |
| **LinkedIn** | Endpoint `jobs-guest` | Không cần API/đăng nhập. Xem lưu ý bên dưới |

Đã thử và không dùng được (scraper đã xoá khỏi repo): **TopDev** chặn ngay ở tầng TLS handshake, **TopCV** / **JobsGO** trả Cloudflare 403, **Facebook** để tin thực tập IT trong group kín nên phải đăng nhập.

### Lưu ý về ITviec (Cloudflare 403)

ITviec đứng sau Cloudflare. Gọi bằng `requests` từ runner GitHub Actions luôn trả **403**, dù cùng đoạn code chạy ở máy nhà vẫn ra đủ 82 tin. Thêm header giống trình duyệt **không** cứu được, vì Cloudflare còn nhận dạng client qua **TLS fingerprint** (JA3/JA4) — OpenSSL của Python có fingerprint riêng, khác Chrome, nên chỉ cần nhìn cái bắt tay TLS là biết không phải trình duyệt.

Cách giải: `curl_cffi` giả lập đúng TLS fingerprint của Chrome. Nguồn thử ba đường, dừng ở đường nào chạy được:

| # | Đường | Ghi chú |
|---|---|---|
| 1 | TLS giả lập Chrome (`curl_cffi`) | Đường chính, qua được Cloudflare. Thực đo: 82 tin |
| 2 | `requests` trực tiếp | Nhanh nhất, chạy tốt ở máy nhà |
| 3 | Reader `r.jina.ai` | Họ tự mở trang bằng trình duyệt thật rồi trả markdown. Có hạn mức cho IP không token |

Đường nào bị chặn thì bỏ hẳn cho các query còn lại, đỡ mất thời gian gọi những request chắc chắn 403. Đổi phiên bản giả lập bằng biến `ITVIEC_IMPERSONATE` (mặc định `chrome124`).

Các hướng đã thử và tắc: `html.duckduckgo.com` trả HTTP 202 (chặn bot); `lite.duckduckgo.com` trả 200 nhưng chỉ ra trang danh sách, không ra tin; Google cần JS, Bing trả captcha.

### Lưu ý về LinkedIn
- LinkedIn **tự nới lỏng** truy vấn nhiều từ: query `"devops intern"` bị hiểu thành `"devops"` nên trả về toàn tin Senior/Middle. Vì vậy chỉ hỏi LinkedIn theo **cấp bậc** (`intern`, `thực tập`...) rồi để `filters.py` lọc ngành.
- Các filter `f_E` (cấp bậc) và `f_JT=I` (internship) bị endpoint guest **bỏ qua**; chỉ `f_TPR` (thời gian đăng) có tác dụng.
- LinkedIn trả HTTP 429 quanh trang thứ 6. `LINKEDIN_PAGES=5` và `LINKEDIN_QUERY_DELAY` giữ cho an toàn; gặp 429 thì tự nghỉ `LINKEDIN_COOLDOWN` giây rồi thử lại.

## Trang thống kê (GitHub Pages)

Mỗi lần chạy, bot sinh trang tĩnh vào `docs/` rồi workflow commit lên repo. GitHub Pages phục vụ miễn phí tại URL cố định nên nút trong Telegram không bao giờ đổi.

```
docs/index.html               danh sách + thống kê ngày mới nhất
docs/archive/YYYY-MM-DD.html  bản lưu từng ngày
docs/data.json                số liệu theo ngày (vẽ biểu đồ xu hướng)
```

Trang không dùng JavaScript: bộ lọc theo nhóm nghề làm bằng radio ẩn cộng selector `:checked ~`, nên mở bằng `file://` hay qua Pages đều chạy. Giao diện tự đổi sáng/tối theo `prefers-color-scheme`.

Bật một lần ở repo: **Settings → Pages → Source: Deploy from a branch → main / docs**.

Nếu tên repo khác, đặt biến `PAGES_URL` cho khớp.

## Deploy: GitHub Actions cron (miễn phí, không cần thẻ)

Bot không cần server chạy 24/7. GitHub Actions chạy `run_once.py` mỗi sáng 8:00 giờ Việt Nam rồi tắt.

1. Push code lên GitHub
2. **Settings → Secrets and variables → Actions → New repository secret**:
   - `BOT_TOKEN` – token từ [@BotFather](https://t.me/BotFather)
   - `CHAT_IDS` – chat ID của bạn, lấy từ [@userinfobot](https://t.me/userinfobot). Nhiều người thì cách nhau bằng dấu phẩy: `123456789,987654321`
3. **Settings → Pages → Source: main /docs**
4. Test ngay: tab **Actions** → *Gửi tin tuyển dụng hàng ngày* → **Run workflow**

Runner của GitHub Actions là ephemeral (xoá sạch sau mỗi lần chạy) nên `jobs.db` được commit ngược lại repo. Nhờ đó lịch sử "đã gửi" vẫn còn và mỗi sáng chỉ gửi tin **mới**.

Đổi giờ gửi ở [.github/workflows/daily.yml](.github/workflows/daily.yml) — cron dùng **giờ UTC**, `'0 1 * * *'` là 08:00 ICT.

## Chạy cục bộ

```bash
pip install -r requirements.txt
cp .env.example .env       # rồi điền BOT_TOKEN

python run_once.py         # gửi một lần rồi thoát — giống hệt lúc cron chạy
python bot.py              # tuỳ chọn: chế độ polling, có lệnh /start /jobs /stop
```

`run_once.py` cần thêm biến `CHAT_IDS`; `bot.py` thì không, vì nó tự lưu người
đăng ký qua lệnh `/start`. Bản deploy đang dùng là `run_once.py` + cron.

Trên Windows, terminal mặc định dùng cp1252 và sẽ crash khi in tiếng Việt. Đặt `PYTHONIOENCODING=utf-8` trước khi chạy.

### Lệnh Telegram
| Lệnh | Mô tả |
|---|---|
| `/start` | Đăng ký nhận tin hàng ngày |
| `/jobs`  | Xem tin ngay lập tức |
| `/stop`  | Huỷ đăng ký |

## Cấu trúc dự án

```
bot_tele/
├── bot.py                  # Telegram handlers + scheduler (chế độ polling)
├── run_once.py             # Chạy một lần — dùng cho GitHub Actions cron
├── webpage.py              # Sinh trang tĩnh docs/ cho GitHub Pages
├── config.py               # Toàn bộ cấu hình (đọc .env)
├── filters.py              # Lọc cấp bậc/ngành/địa điểm + chấm điểm
├── storage.py              # SQLite: subscriber + lịch sử đã gửi
├── sources/
│   ├── base.py             # Kiểu Job + lớp BaseSource
│   ├── itviec.py
│   ├── vietnamworks.py
│   ├── glints.py
│   └── linkedin.py
├── .github/workflows/daily.yml
├── docs/                   # Trang GitHub Pages, sinh tự động
└── jobs.db                 # Lịch sử đã gửi, commit theo repo
```

## Cách lọc hoạt động

Không nguồn nào cho filter "thực tập + Hà Nội + đúng ngành" ngay trên query, nên toàn bộ phần lọc thật nằm ở [filters.py](filters.py):

1. **Cấp bậc** – `is_intern_level()` nhận `intern`/`thực tập`/`TTS`, loại thẳng tiêu đề có dấu hiệu senior. `is_fresher_level()` gom nhóm fresher/junior riêng cho trang web.
2. **Ngành** – `detect_category()` khớp tiêu đề trước, rồi mới tới tag. `backend_java` yêu cầu từ khoá Java/Spring tường minh vì "backend" một mình quá chung (AI Engineer, .NET, Node.js đều mang tag đó).
3. **Loại trừ** – `EXCLUDE_KEYWORDS` bỏ helpdesk, frontend, AI/ML, tester và các nghề ngoài phạm vi.
4. **Địa điểm** – `is_in_hanoi()`, nhận cả tên quận và tin remote.
5. **Chấm điểm** – tin mới, có chữ "intern" ngay tiêu đề, công khai lương, khớp nhiều từ khoá ngành thì điểm cao.

Khớp theo **ranh giới từ** (regex lookaround), không phải substring: nếu không thì "java" khớp cả trong "javascript" và "hn" khớp trong "chuyen".

## Tuỳ chỉnh

### Thêm từ khoá ngành
```python
# filters.py
"data_engineer": [
    "data engineer", ...,
    "mlops",           # thêm ở đây
],
```

### Thêm nguồn mới
Tạo `sources/ten_nguon.py` kế thừa `BaseSource`, implement `fetch()` trả về `Iterable[Job]`, rồi thêm vào `ALL_SOURCES` trong `sources/__init__.py`.

Thứ tự nên thử khi khảo sát một nền tảng mới:
1. **Endpoint JSON/guest nội bộ** — mở DevTools tab Network, lọc XHR, xem trang tự gọi API nào. Cho dữ liệu sạch nhất.
2. **Scrape HTML trực tiếp** — được khi site render server-side và không có Cloudflare.
3. **Giả lập TLS fingerprint** (`curl_cffi`, `impersonate="chrome124"`) — dùng khi 2 trả 403 mà máy nhà vẫn vào được, tức là bị chặn theo fingerprint/IP. Đây là cách đang dùng cho ITviec.
4. **Reader proxy** (`r.jina.ai/<url>`) — bên thứ ba mở trang bằng trình duyệt thật rồi trả markdown. Có hạn mức cho IP không token, gọi dồn dập là bị chặn.
5. **Search engine → URL → scrape** — hiệu quả thấp nhất. Google yêu cầu JS, Bing trả captcha, `html.duckduckgo.com` trả HTTP 202; `lite.duckduckgo.com` còn chạy nhưng chỉ ra trang danh sách chứ không ra từng tin.

### Số tin ít thì làm sao
Thị trường thực tập DevOps/Java/Data Engineer ở Hà Nội thực sự mỏng — khoảng 3-5 tin trên tổng ~500 tin gần đây từ 4 nguồn. Muốn nhiều hơn phải nới một trong ba điều kiện: nhận thêm fresher, mở rộng ngành, hoặc bỏ giới hạn Hà Nội.
