# SSI Python SDK

Python SDK cho nền tảng giao dịch chứng khoán SSI. Hỗ trợ REST API và WebSocket streaming, cả đồng bộ (sync) và bất đồng bộ (async).

[![PyPI version](https://img.shields.io/pypi/v/ssi-sdk?logo=pypi&logoColor=white)](https://pypi.org/project/ssi-sdk/)
[![Downloads](https://static.pepy.tech/badge/ssi-sdk/month)](https://pepy.tech/project/ssi-sdk)
[![Python version](https://img.shields.io/pypi/pyversions/ssi-sdk?logo=python&logoColor=white)](https://pypi.org/project/ssi-sdk/)
[![License](https://img.shields.io/github/license/SSI-Securities-Inc/ssi-sdk-python)](https://github.com/SSI-Securities-Inc/ssi-sdk-python/blob/main/LICENSE)

## Mục lục

- [Cài đặt](#cài-đặt)
- [Cấu hình](#cấu-hình)
- [Kiến trúc Client](#kiến-trúc-client)
- [Xác thực](#1-xác-thực)
- [Tài khoản](#2-tài-khoản)
- [Dữ liệu thị trường](#3-dữ-liệu-thị-trường)
- [Danh mục đầu tư](#4-danh-mục-đầu-tư)
- [Giao dịch](#5-giao-dịch)
- [Streaming realtime](#6-streaming-realtime)
- [Xử lý lỗi](#7-xử-lý-lỗi)
- [Cấu hình nâng cao](#8-cấu-hình-nâng-cao)
- [Gợi ý trong IDE và kiểu dữ liệu](#9-gợi-ý-trong-ide-và-kiểu-dữ-liệu)
- [Nâng cấp & deprecation](#10-nâng-cấp--deprecation)

---

## Cài đặt

```bash
pip install ssi-sdk
```

---

## Cấu hình

Tạo đối tượng `Config` với thông tin xác thực:

```python
from ssi_sdk import Config

config = Config(
    client_id="YOUR_CLIENT_ID",
    api_key="YOUR_API_KEY",
    api_secret="YOUR_API_SECRET",
    private_key="YOUR_PRIVATE_KEY",
)
```

**Tất cả tuỳ chọn cấu hình:**

| Tham số | Kiểu | Mặc định | Mô tả |
|---------|------|----------|-------|
| `client_id` | `str` | `""` | Client ID xác thực |
| `api_key` | `str` | `""` | API key từ SSI |
| `api_secret` | `str` | `""` | API secret từ SSI |
| `private_key` | `str` | `""` | Private key cho ký lệnh giao dịch |
| `api_url` | `str` | `"https://api.ssi.com.vn"` | URL REST API |
| `streaming_url` | `str` | `"wss://stream.ssi.com.vn/ws/v3"` | URL WebSocket streaming |
| `trading_api_domain` | `str` | `"https://api.ssi.com.vn"` | URL của **REST API giao dịch** (đặt lệnh, FCO, tài khoản, danh mục: `/api/v3/trading/*`, `/api/v3/account/*`), cùng kiểu với `api_url`. Giữ mặc định thì **theo `api_url`** (đổi `api_url` sang môi trường khác là trading đi theo); đặt host khác để tách riêng. Auth và dữ liệu thị trường luôn dùng `api_url`. Chấp nhận cả `host`/`host:port` (tự thêm `https://`). Token và rate limit dùng chung. URL thực tế: `Config.trading_api_url` |
| `trading_ws_domain` | `str` | `"wss://api.ssi.com.vn/ws/v3/trading"` | URL WebSocket đặt lệnh (thử nghiệm), cùng kiểu với `streaming_url`. Đổi khi server đổi tên miền; chấp nhận cả `host`/`host:port` (tự thêm `wss://` và `/ws/v3/trading`). URL thực tế: `Config.trading_ws_url`. Mọi cấu hình khác dùng chung `Config` |
| `timeout` | `int` | `60` | Timeout request (giây) |
| `max_retries` | `int` | `5` | Số lần retry tối đa |
| `retry_delay` | `float` | `2.0` | Delay cơ sở giữa các lần retry (exponential backoff, giây) |
| `rate_limit_per_second` | `int` | `10` | Giới hạn request/giây (0 = không giới hạn) |
| `log_level` | `str` | `"INFO"` | Mức log: DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `user_agent` | `str \| None` | `None` | User-Agent cho HTTP và payload lệnh (mặc định giữ nguyên như trước) |
| `auto_reconnect` | `bool` | `True` | Tự mở lại socket streaming khi bị rớt (xem mục 6) |
| `otp_poll_interval` | `float` | `5.0` | Khoảng cách giữa các lần poll Smart OTP (giây) |
| `otp_poll_max_wait` | `float` | `60.0` | Tổng thời gian tối đa chờ approve Smart OTP (giây) |

> `api_url`, `streaming_url`, `trading_api_domain` và `trading_ws_domain`: không truyền, `None` hoặc `""` đều lấy giá trị mặc định trong `ssi_sdk/constant.py`.

> `repr(Config(...))` che `api_secret` và `private_key`; không bao giờ log token/secret ở mọi mức log.

---

## Kiến trúc Client

SDK sử dụng kiến trúc **modular** gồm 4 client chuyên biệt:

| Client | Async | Mô tả | Yêu cầu |
|--------|-------|-------|---------|
| `Auth` | `AsyncAuth` | Xác thực & quản lý token | `Config` |
| `Data` | `AsyncData` | Dữ liệu thị trường (OHLC, chỉ số, chứng khoán) | `Auth` (không cần OTP) |
| `Trading` | `AsyncTrading` | Giao dịch + danh mục + tài khoản | `Auth` (cần OTP) |
| `Stream` | `AsyncStream` | Streaming realtime qua WebSocket | `Auth` (cần OTP) |

**Luồng khởi tạo:**

```
Config → Auth → authenticate(otp=...) → Data / Trading / Stream
```

`Auth` là client gốc — quản lý REST client và token. Các client `Data`, `Trading`, `Stream` đều nhận `Auth` làm tham số và chia sẻ chung HTTP connection.

**Services được cung cấp bởi mỗi client:**

| Client | Service | Truy cập | Mô tả |
|--------|---------|---------|-------|
| `Auth` | `TokenManager` | `auth.token_manager` | Xác thực, OTP, refresh token |
| `Data` | `MarketDataService` | `data.market_data` | OHLC, chỉ số, chứng khoán, securities summary |
| `Trading` | `TradingService` | `trading.trading` | Đặt/sửa/huỷ lệnh, sức mua/bán |
| `Trading` | `AccountService` | `trading.account` | Thông tin tài khoản |
| `Trading` | `PortfolioService` | `trading.portfolio` | Số dư, vị thế, sổ lệnh, PPMMR |
| `Stream` | `StreamingService` | `stream.streaming` | Subscribe/unsubscribe realtime data |

### Async (khuyến nghị)

```python
import asyncio
from ssi_sdk import AsyncAuth, AsyncData, AsyncTrading, AsyncStream, Config

async def main():
    config = Config(
        client_id="YOUR_CLIENT_ID",
        api_key="YOUR_API_KEY",
        api_secret="YOUR_API_SECRET",
        private_key="YOUR_PRIVATE_KEY",
    )

    async with AsyncAuth(config) as auth:
        # Xác thực
        await auth.authenticate(otp="222222")

        # Dữ liệu thị trường
        async with AsyncData(auth) as data:
            ohlc = await data.market_data.get_ohlc_1minute("SSI")
            print(ohlc)

        # Giao dịch & danh mục
        async with AsyncTrading(auth) as trading:
            accounts = await trading.account.get_account_info()
            print(accounts)

        # Streaming
        async with AsyncStream(auth) as stream:
            await stream.streaming.connect()
            stream.streaming.on_data = lambda msg: print(msg)
            await stream.streaming.subscribe_symbol_trade(["SSI"])
            await stream.streaming.wait()

asyncio.run(main())
```

### Sync

```python
from ssi_sdk import Auth, Data, Trading, Config

config = Config(
    client_id="YOUR_CLIENT_ID",
    api_key="YOUR_API_KEY",
    api_secret="YOUR_API_SECRET",
    private_key="YOUR_PRIVATE_KEY",
)

with Auth(config) as auth:
    auth.authenticate(otp="222222")

    with Trading(auth) as trading:
        accounts = trading.account.get_account_info()
        print(accounts)
```

### Chỉ dùng dữ liệu thị trường (không cần OTP)

```python
from ssi_sdk import Auth, Data, Config

with Auth(config) as auth:
    auth.authenticate()  # Không cần OTP cho market data

    with Data(auth) as data:
        ohlc = data.market_data.get_ohlc_1minute("SSI")
```

### Truyền config bằng keyword arguments

```python
from ssi_sdk import Auth

auth = Auth(
    client_id="YOUR_CLIENT_ID",
    api_key="YOUR_API_KEY",
    api_secret="YOUR_API_SECRET",
    private_key="YOUR_PRIVATE_KEY",
    timeout=60,
    log_level="DEBUG",
)
```

---

## 1. Xác thực

Dùng `Auth` / `AsyncAuth`. Các method của `token_manager` được delegate trực tiếp lên client.

### 1.1. Xác thực với OTP

```python
# Dùng trực tiếp trên auth (delegate từ token_manager)
token = auth.authenticate(otp="222222")
print(f"Access token: {token.access_token}")
print(f"Expires at: {token.expires_at}")

# Hoặc truy cập token_manager
token = auth.token_manager.authenticate(otp="222222")

# Smart OTP: truyền transaction_id (lấy từ request_otp) thay vì otp —
# chỉ gọi được sau khi user đã bấm approve trên thiết bị, nếu chưa approve
# API sẽ báo lỗi. Muốn tự chờ approve, dùng ensure_authenticated (mục 1.4).
token = auth.authenticate(transaction_id="...")
```

`otp` và `transaction_id` loại trừ lẫn nhau — chỉ truyền một trong hai.

### 1.2. Yêu cầu gửi OTP

Cùng một endpoint cho cả 2 loại tài khoản (SMS/email hoặc Smart OTP) — server
tự quyết định cách gửi OTP dựa trên cách tài khoản đã đăng ký (đăng ký từ đầu,
không đổi được runtime):

```python
otp = auth.request_otp_typed()     # OTPResponse: message, transaction_id
print(otp.message)

# transaction_id CHỈ có với Smart OTP (push-approval). OTP SMS/email không có
# trường này (otp.transaction_id là None) — chỉ cần nhập mã nhận được vào otp=...
if otp.transaction_id:
    ...  # tiếp tục với ensure_authenticated(transaction_id=...) (mục 1.4)
```

`auth.request_otp()` vẫn trả về dict thô của server (không đổi).

**Tài khoản đã kích hoạt Smart OTP có 2 cách để xác thực:**

1. **Approve trên app** — gọi `request_otp()` để bắn yêu cầu lên thiết bị,
   lấy `transaction_id`, rồi dùng `ensure_authenticated(transaction_id=...)` để
   SDK tự poll cho đến khi user bấm approve (xem mục 1.4, case 3).
2. **Lấy mã trực tiếp trên app** — mở app Smart OTP, đọc mã hiển thị sẵn, rồi
   điền thẳng mã đó vào `ensure_authenticated(otp=...)` (hoặc `authenticate(otp=...)`)
   — **không cần** gọi `request_otp()` trước, vì mã đã được app sinh sẵn tại
   chỗ chứ không phải mã do server gửi.

```python
# Cách 2: khách tự lấy mã Smart OTP trên app rồi điền thẳng vào — giống hệt
# flow OTP thường, không cần request trước
access_token = auth.ensure_authenticated(otp="123456")
```

### 1.3. Làm mới token

```python
token = auth.refresh()
```

### 1.4. Tự động đảm bảo xác thực

`ensure_authenticated` tự refresh nếu token còn refresh token hợp lệ; nếu chưa
có token thì xác thực theo tham số truyền vào. Không truyền `otp`/`transaction_id`
và không có refresh token → báo lỗi (giữ nguyên hành vi cũ).

```python
# 1) Refresh nếu có refresh token còn dùng được — không cần otp/transaction_id
access_token = auth.ensure_authenticated()

# 2) OTP thường (SMS/email), hoặc mã Smart OTP lấy trực tiếp trên app — cả
# hai đều dùng tham số otp, xác thực 1 lần, không chờ đợi
access_token = auth.ensure_authenticated(otp="222222")

# 3) Smart OTP dạng push-approval — truyền transaction_id lấy từ
# request_otp_typed(). Việc approve trên thiết bị là bất đồng bộ nên SDK tự
# poll mỗi Config.otp_poll_interval giây (mặc định 5s), tổng tối đa
# Config.otp_poll_max_wait giây (mặc định 60s).
otp = auth.request_otp_typed()
access_token = auth.ensure_authenticated(transaction_id=otp.transaction_id)
# Có thể ghi đè từng lần gọi: poll_interval=..., poll_max_retries=...
```

Kết quả poll Smart OTP:

| Tình huống | Exception |
|------------|-----------|
| Hết thời gian mà user chưa approve | `SmartOTPPendingError` — transaction còn hiệu lực thì gọi lại `ensure_authenticated(transaction_id=...)` với cùng `transaction_id` |
| User từ chối / transaction hết hạn / không tồn tại (401113, 401115, 401116) | `SmartOTPRejectedError` — dừng ngay, không poll tiếp |

Khi token **không refresh được** (refresh token hết hạn, hoặc server từ chối 401101/401103),
SDK xoá token và ném `ReauthenticationRequired` (là con của `AuthenticationError`) —
cần OTP mới, **không retry**. Server coi việc dùng lại refresh token là rò rỉ và thu hồi
**toàn bộ** session của `apiKey`.

> **Cảnh báo — chỉ 1 session active cho mỗi `apiKey`:** đăng nhập hoặc refresh ở
> process/máy khác sẽ làm token của process này mất hiệu lực. Lock trong SDK chỉ
> chống refresh trùng *trong cùng một process*; nhiều process dùng chung một `apiKey`
> sẽ đá nhau và có thể dẫn tới `ReauthenticationRequired`.

### 1.4b. Gán token thủ công

```python
from ssi_sdk.models import Token
auth.set_token(Token(access_token="...", expires_at=..., refresh_token="...", refresh_token_expires_at=...))
```

Dùng khi token do nơi khác cấp (vd cache). Token **không có hạn** (`expires_at <= 0`) bị coi là đã hết hạn.

### 1.5. Kiểm tra trạng thái token

```python
print(auth.token)              # Token object hoặc None
print(auth.access_token)       # Access token string hoặc None
print(auth.is_token_expired)   # True/False
print(auth.has_refresh_token)  # True/False
print(auth.can_refresh)        # refresh token còn hạn?
print(auth.token.effective_expires_at)  # min(access, refresh) — mốc phải đăng nhập lại
```

`expiresAt`/`refreshExpiresAt` do server trả bằng **giây** (giá trị >= 1e10 được hiểu là mili-giây
và tự đổi). Token được coi là hết hạn sớm 30 giây; token không rõ hạn (`expires_at <= 0`) coi là đã hết hạn.

---

## 2. Tài khoản

Truy cập qua `trading.account` (client `Trading` / `AsyncTrading`).

### 2.1. Lấy danh sách tài khoản

```python
accounts = trading.account.get_account_info()

for acc in accounts:
    print(f"{acc.account_no} - {acc.account_type}")
```

**Trả về:** `list[Account]` — mỗi `Account` có:
- `account_no: str` — Số tài khoản
- `account_type: AccountType | str | None` — Loại tài khoản (`EQUITY`, `EQUITY_MARGIN`, `DERIVATIVE`);
  giá trị server gửi mà SDK chưa biết được giữ nguyên dạng chuỗi, thiếu thì là `None`
  (không còn mặc định `Cash`). Khi không có tài khoản server trả `{"code": 204}` → danh sách rỗng.

---

## 3. Dữ liệu thị trường

Truy cập qua `data.market_data` (client `Data` / `AsyncData`).

> **Lưu ý:** `Data` chỉ cần `auth.authenticate()` (không cần OTP).

### Tổng quan method

| Nhóm | Method | Mô tả |
|------|--------|-------|
| **OHLC trong ngày** | `get_ohlc_1minute(symbol)` | Nến 1 phút |
| | `get_ohlc_3minute(symbol)` | Nến 3 phút |
| | `get_ohlc_5minute(symbol)` | Nến 5 phút |
| | `get_ohlc_15minute(symbol)` | Nến 15 phút |
| | `get_ohlc_1hour(symbol)` | Nến 1 giờ |
| **OHLC lịch sử** | `get_ohlc_1minute_historical(symbol, from_date, to_date, page, size)` | 1 phút |
| | `get_ohlc_3minute_historical(...)` | 3 phút |
| | `get_ohlc_5minute_historical(...)` | 5 phút |
| | `get_ohlc_15minute_historical(...)` | 15 phút |
| | `get_ohlc_1hour_historical(...)` | 1 giờ |
| | `get_ohlc_1day_historical(...)` | 1 ngày |
| | `get_ohlc_1week_historical(...)` | 1 tuần |
| | `get_ohlc_1month_historical(...)` | 1 tháng |
| **Chỉ số** | `get_indexes()` | Tất cả chỉ số |
| | `get_indexes_by_board(board)` | Chỉ số theo sàn |
| **Index Summary** | `get_index_summary(index)` | Summary chỉ số hiện tại |
| | `get_index_summary_historical(index, trading_date)` | Summary chỉ số lịch sử |
| | `get_board_summary(board)` | Summary sàn hiện tại |
| | `get_board_summary_historical(board, trading_date)` | Summary sàn lịch sử |
| **Chứng khoán** | `get_securities_info(symbol)` | Thông tin 1 mã |
| | `get_securities_info_by_index(index)` | Theo chỉ số |
| | `get_securities_info_by_board(board)` | Theo sàn |
| **Securities Summary** | `get_securities_summary(symbol)` | Summary mã hiện tại |
| | `get_securities_summary_historical(symbol, from_date, to_date)` | Summary mã lịch sử |
| | `get_securities_summary_by_index(index)` | Summary theo chỉ số |
| | `get_securities_summary_by_index_historical(index, from_date, to_date)` | Summary chỉ số lịch sử |
| **Master Data** | `get_master_data()` | Giá trần/sàn/tham chiếu tất cả mã hôm nay |
| | `get_master_data_historical(from_date, to_date)` | Giá trần/sàn/tham chiếu tất cả mã trong khoảng ngày |

### 3.1. Dữ liệu OHLC (nến)

SDK cung cấp các method OHLC theo từng timeframe:

**Lấy dữ liệu trong ngày (không cần truyền ngày):**

| Method | Timeframe |
|--------|-----------|
| `get_ohlc_1minute(symbol)` | 1 phút |
| `get_ohlc_3minute(symbol)` | 3 phút |
| `get_ohlc_5minute(symbol)` | 5 phút |
| `get_ohlc_15minute(symbol)` | 15 phút |
| `get_ohlc_1hour(symbol)` | 1 giờ |

```python
# OHLC 1 phút trong ngày
ohlc = data.market_data.get_ohlc_1minute("SSI")
for candle in ohlc:
    print(f"{candle.trading_date}: O={candle.open_price} H={candle.high_price} L={candle.low_price} C={candle.close_price} V={candle.volume}")
```

**Lấy dữ liệu lịch sử (truyền khoảng ngày + phân trang):**

| Method | Timeframe |
|--------|-----------|
| `get_ohlc_1minute_historical(symbol, from_date, to_date, page, size)` | 1 phút |
| `get_ohlc_3minute_historical(symbol, from_date, to_date, page, size)` | 3 phút |
| `get_ohlc_5minute_historical(symbol, from_date, to_date, page, size)` | 5 phút |
| `get_ohlc_15minute_historical(symbol, from_date, to_date, page, size)` | 15 phút |
| `get_ohlc_1hour_historical(symbol, from_date, to_date, page, size)` | 1 giờ |
| `get_ohlc_1day_historical(symbol, from_date, to_date, page, size)` | 1 ngày |
| ~~`get_ohlc_1week_historical`~~ | **Không còn hỗ trợ** — server từ chối (400210); luôn ném `ValidationError`. Dùng nến ngày rồi tự gộp |
| ~~`get_ohlc_1month_historical`~~ | **Không còn hỗ trợ** (như trên) |

```python
# OHLC 1 ngày lịch sử
ohlc = data.market_data.get_ohlc_1day_historical(
    symbol="SSI",
    from_date="2026/03/27 00:00:00",
    to_date="2026/03/27 00:00:00",
    page=1,
    size=100,
)
```

**Trả về:** `list[OHLCData]` — mỗi `OHLCData` có:
- `symbol`, `trading_date`, `open_price`, `high_price`, `low_price`, `close_price`, `volume`, `value`

**Lấy toàn bộ các trang:** endpoint OHLC không trả số trang, và trả **mới nhất trước**.

```python
from ssi_sdk.enums import Timeframe

# Tất cả nến trong khoảng — tự lặp trang cho tới khi gặp trang rỗng/ngắn
bars = data.market_data.get_ohlc_all(
    "SSI", Timeframe.DAY_1, "2026/01/01", "2026/03/27", size=1000, ascending=True
)

# Hoặc duyệt từng nến mà không giữ hết trong bộ nhớ
for bar in data.market_data.iter_ohlc("SSI", Timeframe.MINUTE_5, "2026/03/27", "2026/03/27"):
    ...
# AsyncMarketDataService: `async for bar in market_data.iter_ohlc(...)`
```

Mỗi lần gọi chỉ nhận **một mã** (chữ+số), timeframe hợp lệ: `1d, 1m, 3m, 5m, 15m, 1h`;
`from <= to`, định dạng `YYYY/MM/DD` hoặc `YYYY/MM/DD HH:MM:SS`. Endpoint trả `{"code": 204}`
khi rỗng — SDK trả danh sách rỗng. `securitiesSummary`/`masterdata` tự lặp theo `pagesCount`.

> **Lưu ý theo hành vi server:** nến phút/giờ mà `to_date` ở tương lai sẽ được SDK cắt về cuối ngày hôm nay (server trả
> rỗng nếu `to` sau hôm nay); `page`/`size` phải >= 1; dữ liệu "hôm nay" của `securities_summary`/`master_data` có thể bị
> cache phía server tới 1 giờ; subscribe nhiều mã được SDK tự chia thành nhiều frame < 4096 byte.

**Tham số historical:**

| Tham số | Kiểu | Mặc định | Mô tả |
|---------|------|----------|-------|
| `symbol` | `str` | *(bắt buộc)* | Mã chứng khoán |
| `from_date` | `str` | *(bắt buộc)* | Ngày bắt đầu |
| `to_date` | `str` | *(bắt buộc)* | Ngày kết thúc |
| `page` | `int` | `1` | Trang |
| `size` | `int` | `1000` | Số bản ghi/trang |

### 3.2. Danh sách chỉ số thị trường

```python
# Lấy tất cả chỉ số
indices = data.market_data.get_indexes()

# Lấy theo sàn
from ssi_sdk.enums import Board
indices = data.market_data.get_indexes_by_board(Board.HOSE)

for idx in indices:
    print(f"{idx.index} - {idx.index_name}")
```

**Trả về:** `list[MarketIndexes]` — mỗi item có: `index`, `index_name`, `board`

### 3.3. Tổng hợp chỉ số (Index Summary)

```python
# Summary hiện tại
summary = data.market_data.get_index_summary("VNINDEX")
print(f"{summary.index_value} ({summary.index_change:+.2f})")

# Summary lịch sử
summary = data.market_data.get_index_summary_historical("VNINDEX", "2025/01/15")

# Summary theo sàn
summary = data.market_data.get_board_summary(Board.HOSE)

# Summary sàn lịch sử
summary = data.market_data.get_board_summary_historical(Board.HOSE, "2025/01/15")
```

**Trả về:** `MarketIndexSummary` — có các trường: `index`, `board`, `trading_date`, `index_value`, `index_change`, `index_change_percent`, `total_trade`, `total_trade_value`, `total_advance_stock`, `total_decline_stock`, `total_steady_stock`, ...

### 3.4. Thông tin chứng khoán

```python
# Lấy thông tin 1 mã
info = data.market_data.get_securities_info("SSI")
print(f"{info.symbol} ({info.board})")

# Lấy theo chỉ số
securities = data.market_data.get_securities_info_by_index("VN30")

# Lấy theo sàn
securities = data.market_data.get_securities_info_by_board(Board.HOSE)
```

**Trả về:** `SecuritiesInfo` — có các trường: `symbol`, `board`, `index`, `symbol_name_vi`, `symbol_name_en`, `lot_size`, `listed_shares`, `icb_code`, `icb_name`, ...

### 3.5. Tổng hợp chứng khoán (Securities Summary)

```python
# Summary hiện tại
summary = data.market_data.get_securities_summary("SSI")

# Summary lịch sử
summary = data.market_data.get_securities_summary_historical(
    symbol="SSI",
    from_date="2025/01/01",
    to_date="2025/01/31",
)

# Summary theo chỉ số
summary = data.market_data.get_securities_summary_by_index("VN30")

# Summary theo chỉ số lịch sử
summary = data.market_data.get_securities_summary_by_index_historical(
    index="VN30",
    from_date="2025/01/01",
    to_date="2025/01/31",
)
```

**Trả về:** `list[SecuritiesSummary]` — có các trường: `symbol`, `trading_date`, `open_price`, `high_price`, `low_price`, `close_price`, `price_change`, `price_change_percent`, `total_match`, `total_match_value`, ...

### 3.6. Master Data (giá trần/sàn/tham chiếu)

SDK tự động gọi hết các trang (API endpoint này phân trang), không cần tự truyền page/size.

```python
# Hôm nay
result = data.market_data.get_master_data()

# Khoảng ngày tự chọn
result = data.market_data.get_master_data_historical(
    from_date="2026/08/05",
    to_date="2026/08/06",
)

for item in result:
    print(f"{item.board} {item.symbol}: trần={item.ceiling} sàn={item.floor} TC={item.ref_price}")
```

**Trả về:** `list[MasterData]` — mỗi `MasterData` có: `board`, `symbol`, `trading_date`, `ceiling`, `floor`, `ref_price`.

---

## 4. Danh mục đầu tư

Truy cập qua `trading.portfolio` (client `Trading` / `AsyncTrading`).

### Tổng quan method

| Nhóm | Method | Trả về |
|------|--------|--------|
| **Số dư** | `get_equity_balance(account_no)` | `EquityAccountBalance` |
| | `get_derivative_balance(account_no)` | `DerivativeAccountBalance` |
| **Vị thế** | `get_equity_positions(account_no)` | `list[EquityPosition]` |
| | `get_derivative_positions(account_no)` | `list[AllDerivativePosition]` |
| | `get_open_derivative_positions(account_no)` | `list[DerivativePosition]` |
| | `get_closed_derivative_positions(account_no)` | `list[DerivativePosition]` |
| **Sổ lệnh** | `get_today_orders(account_no)` | `list[Order]` |
| | `get_historical_orders(account_no, from_date, to_date)` | `list[Order]` |
| **PPMMR** | `get_equity_ppmmr(account_no)` | `EquityPPMMR` |
| | `get_derivative_ppmmr(account_no)` | `DerivativePPMMR` |

### 4.1. Số dư tài khoản

```python
# Số dư tài khoản cơ sở
equity_balance = trading.portfolio.get_equity_balance("1234561")
print(f"Account balance: {equity_balance.account_balance}")
print(f"Withdrawable: {equity_balance.withdrawable}")

# Số dư tài khoản phái sinh
derivative_balance = trading.portfolio.get_derivative_balance("1234568")
print(f"Account balance: {derivative_balance.account_balance}")
print(f"Withdrawable: {derivative_balance.withdrawable}")
```

### 4.2. Vị thế (Positions)

```python
# Vị thế cơ sở
positions = trading.portfolio.get_equity_positions("1234561")
for pos in positions:
    print(f"{pos.symbol}: {pos.quantity} cp | Giá vốn: {pos.cost_price} | Bán được: {pos.sellable_quantity}")

# Vị thế phái sinh (tất cả)
derivative_positions = trading.portfolio.get_derivative_positions("1234568")

# Chỉ vị thế mở phái sinh
open_pos = trading.portfolio.get_open_derivative_positions("1234568")

# Chỉ vị thế đóng phái sinh
closed_pos = trading.portfolio.get_closed_derivative_positions("1234568")
```

**`EquityPosition`** có các trường: `account_no`, `symbol`, `quantity`, `sellable_quantity`, `cost_price`, `buying_quantity`, `selling_quantity`, `mortgage_quantity`, ...

**`DerivativePosition`** có các trường: `account_no`, `symbol`, `long`, `short`, `net`, `bid_avg_price`, `ask_avg_price`, `floating_pl`, `trading_pl`, ...

### 4.3. Sổ lệnh (Order Book)

```python
# Lệnh trong ngày
today_orders = trading.portfolio.get_today_orders("1234561")
for order in today_orders:
    print(f"{order.order_id}: {order.symbol} {order.side} {order.quantity}@{order.price} - {order.status}")

# Lệnh lịch sử
historical_orders = trading.portfolio.get_historical_orders(
    "1234561",
    from_date="2025/01/01",
    to_date="2025/01/31",
)
```

**`Order`** có các trường: `account_no`, `client_request_id`, `order_id`, `symbol`, `side`, `order_type`, `price`, `avg_price`, `quantity`, `os_quantity`, `filled_quantity`, `cancel_quantity`, `status`, `input_time`, `modify_time`, `message`

### 4.4. PPMMR (Purchasing Power / Margin Maintenance Ratio)

```python
# PPMMR cơ sở
equity_ppmmr = trading.portfolio.get_equity_ppmmr("1234561")
print(f"Purchasing power: {equity_ppmmr.purchasing_power}")
print(f"Margin ratio: {equity_ppmmr.margin_ratio}")

# PPMMR phái sinh
derivative_ppmmr = trading.portfolio.get_derivative_ppmmr("1234568")
```

---

## 5. Giao dịch

Truy cập qua `trading.trading` (client `Trading` / `AsyncTrading`).

### Tổng quan method

| Nhóm | Method | Trả về |
|------|--------|--------|
| **Đặt lệnh** | `place_order(account_no, symbol, side, quantity, price, order_type)` | `PlaceOrderResponse` |
| | `place_limit_order(account_no, symbol, side, quantity, price)` | `PlaceOrderResponse` |
| | `place_market_order(account_no, symbol, side, quantity)` | `PlaceOrderResponse` |
| | `place_ato_order(account_no, symbol, side, quantity)` | `PlaceOrderResponse` |
| | `place_atc_order(account_no, symbol, side, quantity)` | `PlaceOrderResponse` |
| **Sửa lệnh** | `modify_order_price(account_no, client_request_id, price)` | `ModifyOrderResponse` |
| | `modify_order_price_by_order_id(account_no, order_id, price)` | `ModifyOrderResponse` |
| | `modify_order_quantity(account_no, client_request_id, quantity)` | `ModifyOrderResponse` |
| | `modify_order_quantity_by_order_id(account_no, order_id, quantity)` | `ModifyOrderResponse` |
| **Huỷ lệnh** | `cancel_order(account_no, client_request_id)` | `CancelOrderResponse` |
| | `cancel_order_by_order_id(account_no, order_id)` | `CancelOrderResponse` |
| **Sức mua/bán** | `get_max_buy_sell(account_no, symbol, price)` | `MaxBuySellResponse` |
| | `get_max_buy_sell_at_market_price(account_no, symbol)` | `MaxBuySellResponse` |
| **Lệnh điều kiện** | `place_fco_gtd(account_no, symbol, side, quantity, price, price_slip, from_date, to_date)` | `FCOPlaceResponse` |
| | `place_fco_stop(account_no, symbol, side, quantity, stop_price, operator, from_date, to_date)` | `FCOPlaceResponse` |
| | `place_fco_stop_limit(account_no, symbol, side, quantity, price, price_slip, stop_price, operator, from_date, to_date)` | `FCOPlaceResponse` |
| | `place_fco_trailing_stop(account_no, symbol, side, quantity, active_price, trailing_amount, from_date, to_date)` | `FCOPlaceResponse` |
| | `place_fco_trailing_stop_limit(account_no, symbol, side, quantity, active_price, trailing_amount, price_slip, from_date, to_date)` | `FCOPlaceResponse` |
| | `place_fco_oco(account_no, symbol, side, quantity, tp_active_price, sl_active_price, tp_price, sl_price, tp_slip, sl_slip, from_date, to_date)` | `FCOPlaceResponse` |
| | `place_fco_bull_bear(account_no, symbol, side, quantity, price, price_slip, tp_active_price, sl_active_price, tp_price, sl_price, tp_slip, sl_slip, from_date, to_date)` | `FCOPlaceResponse` |
| | `cancel_fco(fco_id)` | `FCOCancelResponse` |
| | `get_fco_by_account_no(account_no, page_index, page_size)` | `FCOListResponse` |
| | `get_fco_by_symbol(account_no, symbol, page_index, page_size)` | `FCOListResponse` |
| | `get_fco_by_status(account_no, process_status, page_index, page_size)` | `FCOListResponse` |
| | `get_fco_by_date(account_no, from_date, to_date, page_index, page_size)` | `FCOListResponse` |
| | `get_fco_by_id(account_no, fco_id)` | `FCOInfo \| None` |
| | `get_fco_order_book(fco_id, page_index, page_size)` | `FCOOrderBookResponse` |
| | `get_fco_status_history(fco_id)` | `list[FCOStatusHistoryItem]` |

### 5.1. Đặt lệnh

> **`device_id` luôn tự lấy theo máy** và không cấu hình được. Server gắn lệnh với thiết bị, nên mọi lệnh/FCO đều mang `deviceId`
> của máy đang chạy: **machine id gốc của hệ điều hành**, không băm (macOS `IOPlatformUUID`, Linux `/etc/machine-id`,
> Windows `MachineGuid`; không có thì địa chỉ MAC), lấy bằng `ssi_sdk.utils.get_device_id()`. Id này đi nguyên văn tới server.
> `Config(device_id=...)` không còn tồn tại (truyền vào sẽ báo `TypeError`).
>
> Giá gửi dạng chuỗi thập phân (không dùng ký hiệu mũ), số lượng là số nguyên dương.
>
> **Idempotency:** truyền `client_request_id="..."` (tối đa 20 ký tự) để có thể đối soát khi lệnh bị timeout;
> không truyền thì SDK sinh ngẫu nhiên. Lệnh **không bao giờ được tự retry** khi timeout. Gửi lại cùng
> id trong ngày bị từ chối `409` → `DuplicateRequestError`.

```python
from ssi_sdk.enums import OrderSide, OrderType

# Lệnh giới hạn (LO)
result = trading.trading.place_limit_order(
    account_no="1234561",
    symbol="SSI",
    side=OrderSide.BUY,
    quantity=100,
    price=66000,
)
print(f"Order ID: {result.order_id}, Status: {result.status}")

# Lệnh thị trường (MTL)
result = trading.trading.place_market_order(
    account_no="1234561",
    symbol="SSI",
    side=OrderSide.BUY,
    quantity=100,
)

# Lệnh ATO (mở cửa)
result = trading.trading.place_ato_order(
    account_no="1234561",
    symbol="SSI",
    side=OrderSide.BUY,
    quantity=100,
)

# Lệnh ATC (đóng cửa)
result = trading.trading.place_atc_order(
    account_no="1234561",
    symbol="SSI",
    side=OrderSide.SELL,
    quantity=100,
)

# Lệnh tuỳ chỉnh (chọn order_type)
result = trading.trading.place_order(
    account_no="1234561",
    symbol="SSI",
    side=OrderSide.BUY,
    quantity=100,
    price=66000,
    order_type=OrderType.LO,
)
```

**Trả về:** `PlaceOrderResponse` — có: `order_id`, `client_request_id`, `status`

**Loại lệnh (`OrderType`):**

| Giá trị | Mô tả |
|---------|-------|
| `OrderType.LO` | Lệnh giới hạn (Limit Order) |
| `OrderType.MTL` | Lệnh thị trường (Market To Limit) |
| `OrderType.MP` | Lệnh thị trường (Market Price) |
| `OrderType.ATO` | Lệnh mở cửa (At The Open) |
| `OrderType.ATC` | Lệnh đóng cửa (At The Close) |
| `OrderType.MOK` | Match Or Kill |
| `OrderType.MAK` | Match And Kill |
| `OrderType.PLO` | Post Lunch Order |

### 5.2. Sửa lệnh

Chỉ có thể sửa **giá** hoặc **số lượng** (không đồng thời).

```python
# Sửa giá theo client_request_id
result = trading.trading.modify_order_price(
    account_no="1234561",
    client_request_id="REQ123",
    price=68000,
)

# Sửa giá theo order_id
result = trading.trading.modify_order_price_by_order_id(
    account_no="1234561",
    order_id="ORD123",
    price=68000,
)

# Sửa số lượng theo client_request_id
result = trading.trading.modify_order_quantity(
    account_no="1234561",
    client_request_id="REQ123",
    quantity=200,
)

# Sửa số lượng theo order_id
result = trading.trading.modify_order_quantity_by_order_id(
    account_no="1234561",
    order_id="ORD123",
    quantity=200,
)
```

**Trả về:** `ModifyOrderResponse` — có: `client_modify_id`, `order_id`, `client_request_id`, `status`

### 5.3. Huỷ lệnh

```python
# Huỷ theo client_request_id
result = trading.trading.cancel_order(
    account_no="1234561",
    client_request_id="REQ123",
)

# Huỷ theo order_id
result = trading.trading.cancel_order_by_order_id(
    account_no="1234561",
    order_id="ORD123",
)
```

**Trả về:** `CancelOrderResponse` — có: `client_cancel_id`, `order_id`, `client_request_id`, `status`

### 5.3b. Đặt / huỷ nhiều lệnh một lượt (batch)

```python
res = trading.trading.place_batch_orders([
    dict(account_no="1234561", symbol="SSI", side=OrderSide.BUY, quantity=100,
         price=66000, order_type=OrderType.LO),
    dict(account_no="1234561", symbol="VNM", side=OrderSide.BUY, quantity=50,
         price=70500, order_type=OrderType.LO, client_request_id="my-key-2"),
])
for r in res.results:                       # mỗi lệnh một kết quả
    print(r.client_request_id, r.order_id, r.status, r.success, r.error_code)

trading.trading.cancel_batch_orders([
    {"account_no": "1234561", "order_id": "ORDER_ID"},
    {"account_no": "1234561", "client_request_id": "my-key-2"},
])
```

Tối đa **20 lệnh**/batch (mặc định của server; đổi bằng `Config(max_batch_orders=...)` nếu server nâng giới hạn); SDK kiểm tra toàn bộ trước, một lệnh sai thì cả batch bị từ chối (server cũng vậy).
`batchRequestId` (ngẫu nhiên, trùng trong ngày → `409` `DuplicateRequestError`) và `batchRequestTime` (thời điểm hiện tại,
lệch cửa sổ → `400111`) do SDK sinh; chữ ký tính trên toàn body; không bao giờ tự retry.

### 5.4. Sức mua/bán tối đa

```python
# Với giá cụ thể
max_bs = trading.trading.get_max_buy_sell(
    account_no="1234561",
    symbol="SSI",
    price=66000,
)
print(f"Max buy: {max_bs.max_buy_quantity}")
print(f"Max sell: {max_bs.max_sell_quantity}")

# Với giá thị trường
max_bs = trading.trading.get_max_buy_sell_at_market_price(
    account_no="1234561",
    symbol="SSI",
)
```

**Trả về:** `MaxBuySellResponse` — có: `account_no`, `symbol`, `max_buy_quantity`, `max_sell_quantity`, `margin_ratio`, `purchase_power`

### 5.5. Giao dịch điều kiện (FCO)

Hỗ trợ các loại lệnh điều kiện linh hoạt (Flexible Conditional Order) bao gồm GTD, Stop, Stop Limit, Trailing Stop, Trailing Stop Limit, OCO, và Bull Bear. Cả hai client đồng bộ (`Trading`) và bất đồng bộ (`AsyncTrading`) đều được hỗ trợ.

#### 5.5.1 Đặt lệnh điều kiện (Đồng bộ - Sync)
```python
from ssi_sdk.enums import OrderSide, OrderType, FCOOperator

# 1. Đặt lệnh GTD (Good Till Date)
gtd_res = trading.trading.place_fco_gtd(
    account_no="1234561",
    symbol="SSI",
    side=OrderSide.BUY,
    quantity=100,
    price=OrderType.MTL,        # Hoặc giá số cụ thể
    price_slip=0.5,
    from_date="2026/07/21 00:00:00",
    to_date="2026/07/28 23:00:00"
)

# 2. Đặt lệnh Stop (Dừng thị trường)
stop_res = trading.trading.place_fco_stop(
    account_no="1234561",
    symbol="SSI",
    side=OrderSide.BUY,
    quantity=100,
    stop_price=20000,
    operator=FCOOperator.GREATER_OR_EQUAL,
    from_date="2026/07/21 00:00:00",
    to_date="2026/07/28 23:00:00"
)

# 3. Đặt lệnh Stop Limit (Dừng giới hạn)
stop_limit_res = trading.trading.place_fco_stop_limit(
    account_no="1234561",
    symbol="SSI",
    side=OrderSide.BUY,
    quantity=100,
    stop_price=20000,
    price=20500,
    price_slip=0.5,
    operator=FCOOperator.GREATER_OR_EQUAL,
    from_date="2026/07/21 00:00:00",
    to_date="2026/07/28 23:00:00"
)

# 4. Đặt lệnh Trailing Stop (Xu hướng thị trường)
ts_res = trading.trading.place_fco_trailing_stop(
    account_no="1234561",
    symbol="SSI",
    side=OrderSide.BUY,
    quantity=100,
    active_price=20000,
    trailing_amount=1000,
    from_date="2026/07/21 00:00:00",
    to_date="2026/07/28 23:00:00"
)

# 5. Đặt lệnh Trailing Stop Limit (Xu hướng giới hạn)
tsl_res = trading.trading.place_fco_trailing_stop_limit(
    account_no="1234561",
    symbol="SSI",
    side=OrderSide.BUY,
    quantity=100,
    active_price=20000,
    trailing_amount=1000,
    price_slip=500,
    from_date="2026/07/21 00:00:00",
    to_date="2026/07/28 23:00:00"
)

# 6. Đặt lệnh OCO (Lệnh huỷ lệnh kia)
oco_res = trading.trading.place_fco_oco(
    account_no="1234561",
    symbol="SSI",
    side=OrderSide.BUY,
    quantity=100,
    tp_active_price=30000,      # Giá kích hoạt chốt lời
    sl_active_price=20000,      # Giá kích hoạt cắt lỗ
    tp_price=OrderType.MP,
    sl_price=OrderType.MP,
    tp_slip=0.1,
    sl_slip=0,
    from_date="2026/07/21 00:00:00",
    to_date="2026/07/28 23:00:00"
)

# 7. Đặt lệnh Bull Bear
bb_res = trading.trading.place_fco_bull_bear(
    account_no="1234561",
    symbol="SSI",
    side=OrderSide.BUY,
    quantity=100,
    price=25000,
    price_slip=10,
    tp_active_price=30000,
    sl_active_price=20000,
    tp_price=30000,
    sl_price=20000,
    tp_slip=0.1,
    sl_slip=0,
    from_date="2026/07/21 00:00:00",
    to_date="2026/07/28 23:00:00"
)
```

**Trả về:** `FCOPlaceResponse` — có: `fco_id`

#### 5.5.2 Đặt lệnh điều kiện (Bất đồng bộ - Async)
Sử dụng cú pháp `async/await` tương tự với `trading` từ `AsyncTrading`:
```python
# Ví dụ đặt lệnh GTD bất đồng bộ
gtd_res = await trading.trading.place_fco_gtd(
    account_no="1234561",
    symbol="SSI",
    side=OrderSide.BUY,
    quantity=100,
    price=OrderType.MTL,
    price_slip=0.5,
    from_date="2026/07/21 00:00:00",
    to_date="2026/07/28 23:00:00"
)
```

#### 5.5.3 Huỷ lệnh điều kiện
```python
# Huỷ FCO theo fco_id (Đồng bộ)
cancel_res = trading.trading.cancel_fco(fco_id="d346f2be-e33b-42f4-afb8-270a70db8216")

# Huỷ FCO theo fco_id (Bất đồng bộ)
cancel_res = await trading.trading.cancel_fco(fco_id="d346f2be-e33b-42f4-afb8-270a70db8216")
```

**Trả về:** `FCOCancelResponse` — có: `fco_id`

#### 5.5.4 Lấy danh sách và thông tin lệnh điều kiện
```python
# Lấy toàn bộ lệnh FCO theo tài khoản (Đồng bộ)
fcos = trading.trading.get_fco_by_account_no(account_no="1234561")

# Lấy FCO theo mã chứng khoán (Đồng bộ)
fcos_symbol = trading.trading.get_fco_by_symbol(account_no="1234561", symbol="SSI")

# Lấy FCO theo trạng thái xử lý (Đồng bộ)
fcos_status = trading.trading.get_fco_by_status(account_no="1234561", process_status="TRIT")

# Lấy FCO theo khoảng thời gian (Đồng bộ)
fcos_date = trading.trading.get_fco_by_date(account_no="1234561", from_date="2026/07/01", to_date="2026/07/21")

# Lấy một lệnh FCO cụ thể bằng ID (Đồng bộ)
fco_info = trading.trading.get_fco_by_id(account_no="1234561", fco_id="fco-id-here")

# Lấy nhật ký khớp lệnh (order book) của lệnh FCO (Đồng bộ)
order_book = trading.trading.get_fco_order_book(fco_id="fco-id-here")
```

> **Lưu ý:** Tất cả các method truy vấn danh sách trên đều hỗ trợ gọi bất đồng bộ với cú pháp `await` tương tự. Các method hỗ trợ thêm tham số tuỳ chọn `page_index` và `page_size` để phân trang.

---

## 6. Streaming realtime

Truy cập qua `stream.streaming` (client `Stream` / `AsyncStream`). Cần gọi `stream.streaming.connect()` trước.

### Tổng quan method

| Nhóm | Method | Mô tả |
|------|--------|-------|
| **Kết nối** | `connect()` | Kết nối WebSocket |
| | `disconnect()` | Ngắt kết nối |
| | `wait(timeout=None)` | Chờ nhận dữ liệu (block) |
| **Heartbeat** | `ping(on_response=None, interval=None)` | Ping server |
| **Subscribe mã** | `subscribe_symbol(symbols)` | Trade + Quote + Room |
| | `subscribe_symbol_trade(symbols)` | Chỉ trade |
| | `subscribe_symbol_quote(symbols)` | Chỉ quote (bid/ask) |
| | `subscribe_symbol_room(symbols)` | Chỉ foreign room |
| | `subscribe_symbol_put_through(symbols)` | Chỉ thoả thuận |
| | `subscribe_symbol_odd_lot(symbols)` | Chỉ lô lẻ |
| | `subscribe_symbol_ohlcv(symbols, interval)` | OHLCV theo timeframe |
| **Subscribe sàn/chỉ số** | `subscribe_board(boards)` | Theo sàn |
| | `subscribe_index(indices)` | Theo chỉ số |
| **Subscribe giao dịch** | `subscribe_order_status(account_no="*")` | Trạng thái lệnh |
| | `subscribe_portfolio(account_no="*")` | Portfolio changes |
| **Unsubscribe** | `unsubscribe_symbol(symbols)` | Huỷ tất cả kênh cho mã |
| | `unsubscribe_symbol_trade(symbols)` | Huỷ trade |
| | `unsubscribe_symbol_quote(symbols)` | Huỷ quote |
| | `unsubscribe_symbol_room(symbols)` | Huỷ foreign room |
| | `unsubscribe_symbol_put_through(symbols)` | Huỷ thoả thuận |
| | `unsubscribe_symbol_odd_lot(symbols)` | Huỷ lô lẻ |
| | `unsubscribe_board(boards)` | Huỷ sàn |
| | `unsubscribe_index(indices)` | Huỷ chỉ số |

**Callbacks:**

| Property | Kiểu | Mô tả |
|----------|------|-------|
| `on_data` | `Callable[[message], Any]` | Nhận market data (tự parse thành typed message) |
| `on_trading` | `Callable[[OrderStatusMessage \| FCOOrderUpdateMessage \| PortfolioMessage], Any]` | Nhận trading events |
| `on_heartbeat` | `Callable[[HeartbeatMessage], Any]` | Nhận heartbeat |

> **Lưu ý:** Tất cả subscribe/unsubscribe methods đều hỗ trợ tham số `on_response` — callback cho
> **ack** của server (`{"method","channel","status","message"}`). Nó **không** thay thế `on_data`/`on_trading`.

**Bổ sung:**

| Method | Mô tả |
|--------|-------|
| `subscribe_market(symbols)` | Master data (trần/sàn/tham chiếu) → `MarketDataMessage` |
| `subscribe_market_flag()` / `unsubscribe_market_flag()` | Cờ phiên (ATO/LO/ATC…) toàn bộ sàn → `MarketFlagMessage(board, trading_time, flag)`; `flag` giữ nguyên chuỗi server gửi, `board` có cả `DERIVATIVES` |
| `subscribe_index_trade(indices, interval=None)` | Tick của **chính chỉ số** (`trade.index.<mã>`), khác `subscribe_index` (trade của các mã thành phần) |
| `subscribe_index_summary(indices)` | `indexsummary.<mã>` (`IndexSummaryMessage`; `data` giữ nguyên field server gửi) |
| `list_subscription()` | Hỏi server đang subscribe những topic nào → `{"trading": [...], "data": [...]}` |

`interval` của `subscribe_symbol_ohlcv` / `subscribe_index_trade` chỉ nhận **`tick`, `1m`, `5m`**
(không có 3m); `trade.index` cần mã cụ thể (không dùng `*`/danh sách/khoảng khi có interval).
Topic được kiểm tra trước khi gửi — mã chứa ký tự lạ, hoặc loại topic chưa hỗ trợ (`asset.*`, `margin.*`), bị `ValidationError`.

**Tự kết nối lại:** khi socket rớt, SDK mở lại với backoff luỹ thừa + jitter (tối đa 60s), **lấy token mới**
mỗi lần kết nối (`Authorization: Bearer`, không đưa token lên URL), tự **subscribe lại** mọi topic đã đăng ký, và chủ động
mở lại socket trước khi token hết hạn (server chỉ kiểm tra JWT lúc connect, không đóng socket khi token hết hạn).
Server từ chối kết nối bằng frame `{"code","msg"}`: `401/403` → refresh token đúng 1 lần rồi thử lại, vẫn lỗi thì
`AuthenticationError`; `429` (quá 10 kết nối/client) → chờ tối thiểu 30s; `5xx` → backoff thường.
Tắt bằng `Config(auto_reconnect=False)`. `disconnect()` đóng hẳn socket và dừng tác vụ nền.

**Message theo `eventType`:** `orderEvent` → `OrderStatusMessage`, `orderMatchEvent` → `OrderMatchMessage`
(khớp lệnh), `clientPortfolioEvent` → `PortfolioMessage` (chỉ tài khoản phái sinh); loại lạ trả về dict thô.

### 6.0. Muốn nhận gì thì dùng method nào

| Muốn nhận | Subscribe / Unsubscribe | Message | Callback có kiểu |
|-----------|-------------------------|---------|------------------|
| Khớp lệnh thị trường của mã | `subscribe_symbol_trade` / `unsubscribe_symbol_trade` (= `subscribe_trades` / `unsubscribe_trades`) | `TradeMessage` | `on_data` |
| Nến `tick`/`1m`/`5m` của mã | `subscribe_symbol_ohlcv` / `unsubscribe_symbol_ohlcv` (= `subscribe_candles` / `unsubscribe_candles`) | `TradeMessage` (tick) / `IntervalMessage` | `on_data` |
| Giá mua/bán (bid/ask) | `subscribe_symbol_quote` / `unsubscribe_symbol_quote` (= `subscribe_quotes` / `unsubscribe_quotes`) | `QuoteMessage` | `on_data` |
| Room khối ngoại | `subscribe_symbol_room` / `unsubscribe_symbol_room` (= `subscribe_foreign_room` / `unsubscribe_foreign_room`) | `ForeignRoomMessage` | `on_data` |
| Thoả thuận | `subscribe_symbol_put_through` / `unsubscribe_symbol_put_through` (= `subscribe_put_through` / `unsubscribe_put_through`) | `PutMessage` | `on_data` |
| Lô lẻ | `subscribe_symbol_odd_lot` / `unsubscribe_symbol_odd_lot` (= `subscribe_odd_lot` / `unsubscribe_odd_lot`) | `OddLotMessage` | `on_data` |
| Trade+quote+room của **các mã thành phần** một sàn | `subscribe_board` / `unsubscribe_board` (= `subscribe_exchange_trades` / `unsubscribe_exchange_trades`) | như trên | `on_data` |
| Trade+quote+room của **các mã thành phần** một chỉ số | `subscribe_index` / `unsubscribe_index` (= `subscribe_index_constituents` / `unsubscribe_index_constituents`) | như trên | `on_data` |
| **Tick của chính chỉ số** | `subscribe_index_trade` / `unsubscribe_index_trade` (= `subscribe_index_ticks` / `unsubscribe_index_ticks`) | `IndexTickMessage` (tick) / `IntervalMessage` (nến 1m/5m) | `on_data` |
| Tổng hợp chỉ số (`indexsummary.VN30`) | `subscribe_index_summary` / `unsubscribe_index_summary` | `IndexSummaryMessage` (`index`, `data`, `get(...)`) | `on_index_summary` |
| Giá trần/sàn/tham chiếu | `subscribe_market` / `unsubscribe_market` (= `subscribe_master_data` / `unsubscribe_master_data`) | `MarketDataMessage` | `on_data` |
| **Cờ phiên** (ATO/LO/ATC…) | `subscribe_market_flag` / `unsubscribe_market_flag` (= `subscribe_session_flag` / `unsubscribe_session_flag`) | `MarketFlagMessage` | `on_market_flag` |
| Trạng thái lệnh **và** khớp lệnh | `subscribe_order_status` / `unsubscribe_order_status` (= `subscribe_orders` / `unsubscribe_orders`) | `OrderStatusMessage`, `OrderMatchMessage` | `on_order`, `on_order_match` |
| Vị thế phái sinh | `subscribe_portfolio` / `unsubscribe_portfolio` (= `subscribe_positions` / `unsubscribe_positions`) | `PortfolioMessage` | `on_portfolio` |
| Danh sách đang subscribe | `list_subscription()` | `{"data": [...], "trading": [...]}` | — |
| Huỷ **tất cả** | `unsubscribe_all()` | — | — |

Mã chỉ số/mã chứng khoán được SDK tự viết hoa (`vn30` → `trade.index.VN30`, `indexsummary.VN30`); tick của chính chỉ số là
`subscribe_index_trade`, dữ liệu đầy đủ của chỉ số là `subscribe_index_summary`. Tài liệu public không liệt kê field của
`indexsummary`, nên `IndexSummaryMessage.data` giữ nguyên payload (đọc bằng `m.get("key1", "key2")`).

`on_data` / `on_trading` vẫn nhận **mọi** message của kênh; các callback có kiểu (`on_market_flag`, `on_index_summary`, `on_order`,
`on_order_match`, `on_portfolio`) chỉ nhận đúng loại của chúng, dùng cùng lúc cũng được. Đặt callback **không** tự
subscribe — vẫn phải gọi method `subscribe_*` tương ứng.

```python
stream.streaming.on_market_flag = lambda m: print(m.board, m.flag, m.trading_time)
stream.streaming.on_order_match = lambda m: print("khớp", m.symbol, m.match_qty, m.match_price)
stream.streaming.subscribe_session_flag()
stream.streaming.subscribe_orders("1234561")
```

**Trạng thái kết nối:** `stream.streaming.is_connected`, `.reconnect_count`, `.last_error`, và
`on_connection = lambda e: ...` nhận `ConnectionEvent(state, reconnect_count, error)` với `state` là `connected`,
`reconnected` (đã subscribe lại), `disconnected` (rớt, sẽ tự nối lại) hoặc `failed` (không phục hồi được, vd cần OTP mới).
Callback chạy trên thread/task của SDK nên giữ ngắn.

### 6.1. Thiết lập callback

```python
# Callback nhận dữ liệu thị trường (tự động parse thành typed message)
def on_market_data(msg):
    print(f"Market data: {msg}")

# Callback nhận dữ liệu giao dịch (OrderStatusMessage | FCOOrderUpdateMessage | PortfolioMessage)
def on_trading_data(msg):
    print(f"Trading: {msg}")

# Callback nhận heartbeat
def on_heartbeat(msg):
    print(f"Heartbeat: {msg.status}")

stream.streaming.on_data = on_market_data
stream.streaming.on_trading = on_trading_data
stream.streaming.on_heartbeat = on_heartbeat
```

**Các message type nhận được qua `on_data`:**

| Topic | Message Type | Mô tả |
|-------|-------------|-------|
| `trade.*` | `TradeMessage` | Dữ liệu khớp lệnh |
| `trade.*.<timeframe>` | `IntervalMessage` | Dữ liệu OHLCV theo interval |
| `quote.*` | `QuoteMessage` | Dữ liệu giá (bid/ask) |
| `room.*` | `ForeignRoomMessage` | Room nước ngoài |
| `market.*` | `MarketStatusMessage` | Trạng thái thị trường |
| `put.*` | `PutMessage` | Thoả thuận |
| `oddlot.*` | `OddLotMessage` | Lô lẻ |

**Các message type nhận được qua `on_trading`:**

| Topic | Message Type | Mô tả |
|-------|-------------|-------|
| `order.*` | `OrderStatusMessage` | Trạng thái lệnh thường |
| | `FCOOrderUpdateMessage` | Trạng thái lệnh điều kiện (khi `eventType == "fcoEvent"`) |
| `portfolio.*` | `PortfolioMessage` | Thay đổi danh mục |

### 6.2. Subscribe dữ liệu thị trường

```python
# Subscribe tất cả kênh (trade + quote + room) cho mã
stream.streaming.subscribe_symbol(["SSI", "HPG", "VIC"])

# Subscribe từng kênh riêng
stream.streaming.subscribe_symbol_trade(["SSI", "HPG"])
stream.streaming.subscribe_symbol_quote(["SSI", "HPG"])
stream.streaming.subscribe_symbol_room(["SSI", "HPG"])
stream.streaming.subscribe_symbol_put_through(["SSI"])
stream.streaming.subscribe_symbol_odd_lot(["SSI"])

# Subscribe OHLCV theo interval
from ssi_sdk.enums import Timeframe
stream.streaming.subscribe_symbol_ohlcv(["SSI"], interval=Timeframe.MINUTE_1)

# Subscribe theo sàn
from ssi_sdk.enums import Board
stream.streaming.subscribe_board([Board.HOSE, Board.HNX])

# Subscribe theo chỉ số
stream.streaming.subscribe_index(["VNINDEX", "VN30"])
```

### 6.3. Unsubscribe

```python
stream.streaming.unsubscribe_symbol(["SSI", "HPG"])
stream.streaming.unsubscribe_symbol_trade(["SSI"])
stream.streaming.unsubscribe_symbol_quote(["SSI"])
stream.streaming.unsubscribe_symbol_room(["SSI"])
stream.streaming.unsubscribe_symbol_put_through(["SSI"])
stream.streaming.unsubscribe_symbol_odd_lot(["SSI"])
stream.streaming.unsubscribe_board([Board.HOSE])
stream.streaming.unsubscribe_index(["VNINDEX"])
```

### 6.4. Subscribe giao dịch (order status & portfolio)

```python
# Subscribe trạng thái lệnh (tất cả tài khoản)
stream.streaming.subscribe_order_status()

# Subscribe cho tài khoản cụ thể
stream.streaming.subscribe_order_status(account_no="1234561")

# Subscribe portfolio
stream.streaming.subscribe_portfolio()
stream.streaming.subscribe_portfolio(account_no="1234561")
```

### 6.5. Heartbeat

```python
# Ping một lần
stream.streaming.ping()

# Ping tự động theo interval (giây)
stream.streaming.ping(interval=30)
```

### 6.7. Đặt lệnh qua WebSocket (thử nghiệm)

> **Thử nghiệm.** Server (`FastConnect.Trading.StreamApi`, `/ws/v3/trading`) chưa được công bố
> release, nên tính năng này **không** nằm trong `Trading`/`Stream` và không export từ `ssi_sdk`.
> Chỉ dùng với môi trường đã được xác nhận hỗ trợ. URL lấy từ `Config.trading_ws_url` (domain: `Config.trading_ws_domain`).

```python
from ssi_sdk.experimental import trading_ws          # async: async_trading_ws

ws = trading_ws(auth)                                # kết nối wss, token ở header
ack = ws.place_order("1234561", "SSI", OrderSide.BUY, 100, 66000, OrderType.LO,
                     client_request_id="my-key-1")   # ack orderStatus "PD"
ws.client.on_event = print                           # frame không có id (vd lỗi định dạng)
ws.close()
```

- Mỗi lệnh là một frame `{id, method, params, signature?, timestamp}`. `params` được serialize **một lần**,
  ký (RSA-SHA256) rồi chèn nguyên văn; ký trên chuỗi khác sẽ bị server trả `401013`.
- Method ghi trạng thái (`order.place/amend/cancel/batchNew/batchCancel`, `fco.place/cancel`) cần
  `Config.private_key`; thiếu thì **không gửi**. Query (`query.*`, `fco.list/orderbook/statusHistory`) không ký.
- `place_order` trả **ack** (`PD`); kết quả thật đến qua topic `order.<account>` (mục 6.4). Một `id` có thể nhận
  nhiều frame: dùng `ws.client.stream(method, params)` để đọc cả frame thứ hai.
- Lỗi: `TradingWSError` (`status`, `error_code`, `server_message`), ví dụ `RATE_LIMIT_EXCEEDED` (429),
  `METHOD_NOT_FOUND` (404), `401013`. `ws.client.rate_limit` giữ `limit/remaining/resetMs` của phản hồi gần nhất.
- **Không bao giờ tự retry** khi timeout (lệnh có thể đã được nhận): đối soát qua event hoặc `query_order_book`.
  Batch tối đa `Config.max_batch_orders` lệnh (mặc định 20); `batchRequestId`/`batchRequestTime` do SDK sinh. Chỉ `wss://`.
- Tên tham số của `query_*` lấy theo tham số REST tương ứng (tài liệu server không liệt kê riêng).
- Nhận event lệnh trên chính socket này: `ws.subscribe_order_events(account_no)` rồi đọc ở `ws.client.on_event` (frame `{channel, topic, data}`); `*` chỉ hợp lệ khi token sở hữu mọi tài khoản, nếu không ack báo `Denied (account)`.

### 6.6. Ví dụ streaming hoàn chỉnh (async)

```python
import asyncio
from ssi_sdk import AsyncAuth, AsyncStream, Config
from ssi_sdk.enums import Board

async def main():
    config = Config(
        client_id="YOUR_CLIENT_ID",
        api_key="YOUR_API_KEY",
        api_secret="YOUR_API_SECRET",
        private_key="YOUR_PRIVATE_KEY",
    )

    async with AsyncAuth(config) as auth:
        await auth.authenticate(otp="222222")

        async with AsyncStream(auth) as stream:
            await stream.streaming.connect()

            # Đăng ký callback
            stream.streaming.on_data = lambda msg: print(f"Data: {msg}")
            stream.streaming.on_trading = lambda msg: print(f"Trading: {msg}")

            # Subscribe
            await stream.streaming.subscribe_symbol(["SSI", "HPG"])
            await stream.streaming.subscribe_order_status()

            # Chờ nhận dữ liệu
            await stream.streaming.wait()

asyncio.run(main())
```

---

## 7. Xử lý lỗi

SDK sử dụng hệ thống exception phân cấp:

```python
from ssi_sdk import SSIError

try:
    auth.authenticate(otp="wrong_otp")
except SSIError as e:
    print(f"Lỗi: {e.message} (code: {e.code})")
```

**Các exception:**

| Exception | Mô tả |
|-----------|-------|
| `SSIError` | Base exception — có `message`, `code`, `status_code`, `response_body`, `headers` |
| `AuthenticationError` | Xác thực thất bại (sai credentials, token hết hạn) |
| `APIError` | API trả về lỗi — `code` là **mã lỗi của server** (vd `400107`; nếu server không gửi thì là HTTP status dạng chuỗi), `status_code` là HTTP status, `response_body` đã che dữ liệu nhạy cảm |
| `DuplicateRequestError` | (con của `APIError`) HTTP 409 — `clientRequestId`/`batchRequestId` đã dùng trong ngày |
| `SmartOTPPendingError`, `SmartOTPRejectedError` | (con của `AuthenticationError`) Smart OTP chưa approve kịp / bị từ chối hoặc hết hạn |
| `ReauthenticationRequired` | (con của `AuthenticationError`) Không refresh được; cần OTP mới |
| `WebSocketError` | Lỗi kết nối hoặc giao tiếp WebSocket |
| `ValidationError` | Lỗi validate input |
| `RateLimitError` | Vượt quá giới hạn request — có `status_code`, `retry_after`, `limit`, `remaining` (server không gửi thời điểm reset nên `reset` thường là `None`) |

```python
from ssi_sdk.exceptions import APIError, AuthenticationError, RateLimitError

try:
    result = trading.trading.place_limit_order(
        account_no="1234561",
        symbol="SSI",
        side=OrderSide.BUY,
        quantity=100,
        price=68000,
    )
except AuthenticationError:
    print("Cần xác thực lại")
except RateLimitError as e:
    print(f"Rate limited, retry sau {e.retry_after}s")
except APIError as e:
    print(f"API error {e.status_code}: {e.message}")
```

---

## 8. Cấu hình nâng cao

### Debug logging

```python
config = Config(
    client_id="YOUR_CLIENT_ID",
    api_key="YOUR_API_KEY",
    api_secret="YOUR_API_SECRET",
    log_level="DEBUG",
)
```

### Tuỳ chỉnh retry & rate limit

```python
config = Config(
    client_id="YOUR_CLIENT_ID",
    api_key="YOUR_API_KEY",
    api_secret="YOUR_API_SECRET",
    max_retries=3,
    retry_delay=1.0,
    rate_limit_per_second=5,
)
```

---

## 9. Gợi ý trong IDE và kiểu dữ liệu

SDK có `py.typed` (PEP 561), nên VS Code/Pylance/PyCharm/mypy dùng được kiểu của nó:

- **Mọi method public** có docstring đủ `Args` / `Returns` / `Raises` (rê chuột hoặc `Ctrl+Space`/`Shift+Tab`).
  Các method chuyển tiếp của `Auth` (`authenticate`, `ensure_authenticated`, `refresh`, ...) được khai báo tường minh,
  không còn đi qua `__getattr__`.
- **Giá**: tham số giá nhận `PriceLike` = `Decimal | int | float | str`; trường số của FCO nhận `NumberLike`.
- **Giá trị cố định** được gợi ý bằng `Literal`: `interval="tick" | "1m" | "5m"`; trạng thái/loại/toán tử FCO nhận enum **hoặc**
  chuỗi hợp lệ (`FCOStatusLike`, `FCOTypeLike`, `FCOOperatorLike`).
- **Batch**: `place_batch_orders` nhận `list[BatchPlaceOrderItem]`, `cancel_batch_orders` nhận `list[BatchCancelOrderItem]`
  (`TypedDict` — IDE gợi ý từng khoá và báo khoá thiếu/sai).
- **Callback streaming** có chữ ký theo kiểu message: `s.on_market_flag = lambda m: m.flag` (IDE biết `m` là
  `MarketFlagMessage`); `on_data` nhận `DataMessage`, `on_trading` nhận `TradingMessage`.
- **Enum** giải thích từng giá trị trong docstring của lớp (`OrderType`, `OrderStatus`, `FCOType`, `Board`, ...); các model
  phản hồi có mục `Attributes`.

```python
from ssi_sdk.models import BatchPlaceOrderItem

orders: list[BatchPlaceOrderItem] = [
    {"account_no": "1234561", "symbol": "SSI", "side": OrderSide.BUY, "quantity": 100,
     "price": Decimal("27000"), "order_type": OrderType.LO},   # thiếu khoá bắt buộc -> IDE báo lỗi
]
```

---

## 10. Nâng cấp & deprecation

**Thay đổi hành vi (có thể ảnh hưởng code hiện có):**

| Khu vực | Thay đổi |
|---------|----------|
| Đặt/sửa/huỷ lệnh, FCO | `deviceId` luôn là id của máy đang chạy (`get_device_id()`), không cấu hình được |
| FCO | `from`/`to` khi đặt lệnh bắt buộc dạng `YYYY/MM/DD HH:MM:SS`, `from <= to`, cửa sổ tối đa 31 ngày (server không kiểm, SDK kiểm) |
| Retry | Chỉ `GET` được retry khi timeout; `POST/PUT/DELETE` (auth, lệnh, FCO) không bao giờ |
| Lỗi | `APIError.code` = mã lỗi server (giữ `status_code` cho HTTP status); HTTP 200 + `code` khác 200/204 → `APIError` |
| Token | `expires_at <= 0` coi là hết hạn; refresh có lock (single-flight); không refresh được → `ReauthenticationRequired` |
| Account | `account_type` không còn mặc định `Cash` (thiếu → `None`; lạ → chuỗi gốc) |
| Order book | `filled_quantity`/`cancel_quantity` đọc `filledQty`/`cancelQty`; `os_quantity` là `None` (server không trả) |
| Giá | Giá lệnh/FCO gửi dạng chuỗi thập phân; `PlaceOrderRequest.price` giữ nội bộ là `Decimal` |
| Streaming | `on_response` không ghi đè `on_data`; interval chỉ `tick/1m/5m`; `OrderStatusMessage.price`/`avg_price` là `Decimal` (hoặc chuỗi cho ATO/ATC/MP) |
| `require_non_empty` | `0`/`False` không còn bị coi là "thiếu" (kiểm tra khoảng giá trị dùng `require_positive`…) |

**Deprecated (còn dùng được, phát `DeprecationWarning`):**

| Cũ | Mới |
|----|-----|
| `MaxBuySellResponse.purchase_power` (str) | `purchasing_power` (`int \| None`) |
| `DerivativeAccountBalance.cash_withdrawable_ssi` / `_vsdc` | `withdrawable_ssi` / `withdrawable_vsdc` |
| `OrderStatusMessage.modify_time` | `modified_time` |
| `PortfolioMessage.total_asset` / `cash_balance` / `stock_value` | server không gửi — luôn `None` |
| `get_ohlc_1week_historical` / `get_ohlc_1month_historical` | server không hỗ trợ — ném `ValidationError` |

**Chưa hỗ trợ:** tải OHLC hàng loạt (`download_ohlc_1minute`, `download_ohlc_1day`: luôn ném `NotImplementedError`, server chưa có endpoint `data/file`).
Trading WebSocket (`/ws/v3/trading`) có ở dạng thử nghiệm: mục 6.7.

---

## API Reference

### Enums

Tất cả enum import từ `ssi_sdk.enums`:

```python
from ssi_sdk.enums import OrderSide, OrderType, OrderStatus, Board, AccountType, Timeframe
```

#### `OrderSide`

| Giá trị | Value | Mô tả |
|---------|-------|-------|
| `BUY` | `"B"` | Mua |
| `SELL` | `"S"` | Bán |

#### `OrderType`

| Giá trị | Value | Mô tả |
|---------|-------|-------|
| `LO` | `"LO"` | Lệnh giới hạn (Limit Order) |
| `MTL` | `"MTL"` | Market To Limit |
| `MP` | `"MP"` | Market Price |
| `ATO` | `"ATO"` | At The Open |
| `ATC` | `"ATC"` | At The Close |
| `MOK` | `"MOK"` | Match Or Kill |
| `MAK` | `"MAK"` | Match And Kill |
| `PLO` | `"PLO"` | Post Lunch Order |

#### `OrderStatus`

| Giá trị | Value | Mô tả |
|---------|-------|-------|
| `PENDING` | `"PD"` | Đang chờ |
| `PENDING_APPROVAL` | `"WA"` | Chờ duyệt |
| `READY` | `"RS"` | Sẵn sàng |
| `SENT` | `"SD"` | Đã gửi |
| `QUEUED` | `"QU"` | Đã xếp hàng |
| `FILLED` | `"FF"` | Khớp toàn bộ |
| `PARTIAL_FILLED` | `"PF"` | Khớp một phần |
| `PARTIAL_CANCELLED` | `"FFPC"` | Khớp một phần + huỷ phần còn lại |
| `PENDING_MODIFY` | `"WM"` | Chờ sửa |
| `PENDING_CANCEL` | `"WC"` | Chờ huỷ |
| `CANCELLED` | `"CL"` | Đã huỷ |
| `REJECTED` | `"RJ"` | Bị từ chối |
| `EXPIRED` | `"EX"` | Hết hạn |
| `PRE_SESSION` | `"IAV"` | Phiên trước |

#### `Board`

| Giá trị | Value | Mô tả |
|---------|-------|-------|
| `HOSE` | `"HOSE"` | Sàn HOSE |
| `HNX` | `"HNX"` | Sàn HNX |
| `UPCOM` | `"UPCOM"` | Sàn UPCOM |

#### `AccountType`

| Giá trị | Value | Mô tả |
|---------|-------|-------|
| `EQUITY` | `"Cash"` | Tài khoản cơ sở |
| `EQUITY_MARGIN` | `"Margin"` | Tài khoản ký quỹ |
| `DERIVATIVE` | `"Derivative"` | Tài khoản phái sinh |

#### `Timeframe`

| Giá trị | Value | Mô tả |
|---------|-------|-------|
| `MINUTE_1` | `"1m"` | 1 phút |
| `MINUTE_3` | `"3m"` | 3 phút |
| `MINUTE_5` | `"5m"` | 5 phút |
| `MINUTE_15` | `"15m"` | 15 phút |
| `HOUR_1` | `"1h"` | 1 giờ |
| `DAY_1` | `"1d"` | 1 ngày |
| `WEEK_1` | `"1w"` | 1 tuần |
| `MONTH_1` | `"1M"` | 1 tháng |

#### `FCOType`

| Giá trị | Value | Mô tả |
|---------|-------|-------|
| `GTD` | `"gtd"` | Lệnh có hiệu lực đến ngày (Good Till Date) |
| `STOP` | `"stop"` | Lệnh dừng thị trường (Stop Market) |
| `STOP_LIMIT` | `"stop_limit"` | Lệnh dừng giới hạn (Stop Limit) |
| `TRAILING_STOP` | `"trailing_stop"` | Lệnh xu hướng (Trailing Stop Market) |
| `TRAILING_STOP_LIMIT` | `"trailing_stop_limit"` | Lệnh xu hướng giới hạn (Trailing Stop Limit) |
| `OCO` | `"oco"` | Lệnh huỷ lệnh còn lại (One Cancels the Other) |
| `BULL_BEAR` | `"bullbear"` | Lệnh Bull Bear |

#### `FCOOperator`

| Giá trị | Value | Mô tả |
|---------|-------|-------|
| `GREATER` | `"greater"` | Lớn hơn (`>`) |
| `GREATER_OR_EQUAL` | `"greater_or_equal"` | Lớn hơn hoặc bằng (`>=`) |
| `LESSER` | `"lesser"` | Nhỏ hơn (`<`) |
| `LESSER_OR_EQUAL` | `"lesser_or_equal"` | Nhỏ hơn hoặc bằng (`<=`) |
| `EQUAL` | `"equal"` | Bằng (`=`) |

#### `FCOStatus`

| Giá trị | Value | Mô tả |
|---------|-------|-------|
| `INIT` | `"INIT"` | Mới khởi tạo |
| `WAIT` | `"WAIT"` | Chờ kích hoạt |
| `TRI` | `"TRI"` | Đã kích hoạt |
| `TRIT` | `"TRIT"` | Đã kích hoạt thành công |
| `TER` | `"TER"` | Đã kết thúc |
| `FIS` | `"FIS"` | Hoàn tất |
| `WC` | `"WC"` | Chờ huỷ |
| `EXP` | `"EXP"` | Hết hạn |
| `ERR` | `"ERR"` | Lỗi |

---

### Models

Tất cả model import từ `ssi_sdk.models`:

```python
from ssi_sdk.models import Account, OHLCData, PlaceOrderResponse, TradeMessage, ...
```

#### Authentication

**`Token`** — Kết quả xác thực

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `access_token` | `str` | Token truy cập |
| `token_type` | `str` | Loại token (mặc định `"Bearer"`) |
| `expires_at` | `int` | Thời điểm hết hạn (timestamp) |
| `refresh_token` | `str` | Token làm mới |
| `refresh_token_expires_at` | `int` | Thời điểm refresh token hết hạn |

#### Account

**`Account`** — Thông tin tài khoản

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `account_no` | `str` | Số tài khoản |
| `account_type` | `AccountType` | Loại tài khoản |

#### Market Data

**`OHLCData`** — Dữ liệu nến OHLC

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `symbol` | `str` | Mã chứng khoán |
| `trading_date` | `str` | Ngày giao dịch |
| `open_price` | `float \| int` | Giá mở cửa |
| `high_price` | `float \| int` | Giá cao nhất |
| `low_price` | `float \| int` | Giá thấp nhất |
| `close_price` | `float \| int` | Giá đóng cửa |
| `volume` | `int` | Khối lượng |
| `value` | `float \| int` | Giá trị giao dịch |

**`MarketIndexes`** — Thông tin chỉ số

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `index` | `str` | Mã chỉ số |
| `index_name` | `str` | Tên chỉ số |
| `board` | `Board \| None` | Sàn |

**`MarketIndexSummary`** — Tổng hợp chỉ số

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `index` | `str` | Mã chỉ số |
| `board` | `str` | Sàn |
| `trading_date` | `str` | Ngày giao dịch |
| `index_value` | `float` | Giá trị chỉ số |
| `index_change` | `float` | Thay đổi |
| `index_change_percent` | `float` | Thay đổi (%) |
| `total_trade` | `int` | Tổng KL giao dịch |
| `total_trade_value` | `float` | Tổng giá trị giao dịch |
| `total_match` | `int` | Tổng KL khớp lệnh |
| `total_match_value` | `float` | Tổng giá trị khớp lệnh |
| `total_deal` | `int` | Tổng KL thoả thuận |
| `total_deal_value` | `float` | Tổng giá trị thoả thuận |
| `total_advance_stock` | `int` | Số mã tăng |
| `total_decline_stock` | `int` | Số mã giảm |
| `total_steady_stock` | `int` | Số mã đứng |
| `total_ceiling_stock` | `int` | Số mã trần |
| `total_floor_stock` | `int` | Số mã sàn |
| `total_prop_buy` | `int` | KL mua tự doanh |
| `total_prop_buy_value` | `float` | Giá trị mua tự doanh |
| `total_prop_sell` | `int` | KL bán tự doanh |
| `total_prop_sell_value` | `float` | Giá trị bán tự doanh |

**`SecuritiesInfo`** — Thông tin chứng khoán

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `symbol` | `str` | Mã chứng khoán |
| `board` | `Board \| None` | Sàn |
| `index` | `str \| None` | Chỉ số |
| `symbol_name_vi` | `str \| None` | Tên tiếng Việt |
| `symbol_name_en` | `str \| None` | Tên tiếng Anh |
| `lot_size` | `int \| None` | Lô giao dịch |
| `maturity_date` | `str \| None` | Ngày đáo hạn |
| `first_trading_date` | `str \| None` | Ngày giao dịch đầu tiên |
| `last_trading_date` | `str \| None` | Ngày giao dịch cuối cùng |
| `cw_underlying_symbol` | `str \| None` | Mã CK cơ sở (CW) |
| `cw_exercise_price` | `float \| None` | Giá thực hiện (CW) |
| `cw_execution_ratio` | `float \| None` | Tỷ lệ chuyển đổi (CW) |
| `listed_shares` | `int \| None` | Số CP niêm yết |
| `icb_code` | `str \| None` | Mã ngành ICB |
| `icb_name` | `str \| None` | Tên ngành ICB |
| `i_index` | `float \| None` | Chỉ số I |
| `i_nav` | `float \| None` | NAV (ETF) |
| `open_interest` | `float \| None` | Khối lượng mở (phái sinh) |
| `settlement_price` | `float \| None` | Giá thanh toán (phái sinh) |

**`SecuritiesSummary`** — Tổng hợp chứng khoán

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `symbol` | `str` | Mã chứng khoán |
| `trading_date` | `str` | Ngày giao dịch |
| `price_change` | `float` | Thay đổi giá |
| `price_change_percent` | `float` | Thay đổi giá (%) |
| `open_price` | `float` | Giá mở cửa |
| `high_price` | `float` | Giá cao nhất |
| `low_price` | `float` | Giá thấp nhất |
| `close_price` | `float` | Giá đóng cửa |
| `average_price` | `float` | Giá trung bình |
| `total_match` | `int` | Tổng KL khớp |
| `total_match_value` | `float` | Tổng giá trị khớp |
| `total_buy` | `int` | Tổng KL mua |
| `total_trade_buy` | `float` | Giá trị mua |
| `total_sell` | `int` | Tổng KL bán |
| `total_trade_sell` | `float` | Giá trị bán |
| `total_foreign_buy` | `int` | KL mua khối ngoại |
| `total_foreign_buy_value` | `float` | GT mua khối ngoại |
| `total_foreign_sell` | `int` | KL bán khối ngoại |
| `total_foreign_sell_value` | `float` | GT bán khối ngoại |
| `remain_foreign_room` | `int` | Room ngoại còn lại |
| `total_foreign_room` | `int` | Tổng room ngoại |
| `total_deal` | `int` | KL giao dịch thỏa thuận |
| `total_deal_value` | `float` | GT giao dịch thỏa thuận |
| `open_interest` | `float` | Khối lượng mở (phái sinh) |
| `settlement_price` | `float` | Giá thanh toán (phái sinh) |

**`MasterData`** — Giá trần/sàn/tham chiếu

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `board` | `Board \| None` | Sàn giao dịch (`HOSE`, `HNX`, `UPCOM`, `DERIVATIVES`) |
| `symbol` | `str` | Mã chứng khoán |
| `trading_date` | `str` | Ngày giao dịch |
| `ceiling` | `float` | Giá trần |
| `floor` | `float` | Giá sàn |
| `ref_price` | `float` | Giá tham chiếu |

#### Portfolio

**`EquityAccountBalance`** — Số dư tài khoản cơ sở

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `account_no` | `str` | Số tài khoản |
| `account_balance` | `float` | Số dư tài khoản |
| `total_debt` | `float` | Tổng nợ |
| `interest_loan` | `float` | Lãi vay |
| `overdue_fee_loan` | `float` | Phí vay quá hạn |
| `withdrawable` | `float` | Tiền rút được |
| `on_hold_cash` | `float` | Tiền tạm giữ |
| `sell_unmatched` | `float` | Bán chưa khớp |
| `sell_t0` / `sell_t1` / `sell_t2` | `float` | Bán T+0/1/2 |
| `buy_unmatched` | `float` | Mua chưa khớp |
| `buy_t0` / `buy_t1` / `buy_t2` | `float` | Mua T+0/1/2 |
| `advance_cash_t0` / `advance_cash_t1` | `float` | Ứng trước T+0/1 |
| `hold_subscription` | `float` | Giữ đăng ký |
| `dividend` | `float` | Cổ tức chờ về/đã ghi nhận |

**`DerivativeAccountBalance`** — Số dư tài khoản phái sinh

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `account_no` | `str` | Số tài khoản |
| `account_balance` | `float` | Số dư tài khoản |
| `fee` / `commission` / `interest` | `float` | Phí / Hoa hồng / Lãi |
| `ext_interest` | `float` | Lãi ngoài |
| `loan` | `float` | Khoản vay |
| `delivery_amount` | `float` | Giá trị chuyển giao |
| `floating_pl` / `trading_pl` / `total_pl` | `float` | Lãi/lỗ |
| `withdrawable` | `float` | Rút được |
| `cash_ssi` / `cash_vsdc` | `float` | Tiền tại SSI / VSDC |
| `valid_non_cash_ssi` / `valid_non_cash_vsdc` | `float` | Tài sản phi tiền mặt |
| `cash_withdrawable_ssi` / `cash_withdrawable_vsdc` | `float` | Tiền rút được |

**`EquityPosition`** — Vị thế cơ sở

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `account_no` | `str` | Số tài khoản |
| `symbol` | `str` | Mã chứng khoán |
| `quantity` | `int` | Tổng số lượng |
| `sellable_quantity` | `int` | Số lượng bán được |
| `cost_price` | `float` | Giá vốn |
| `block_quantity` | `int` | SL phong toả |
| `dividend_quantity` | `int` | SL cổ tức |
| `buying_quantity` / `bought_quantity` | `int` | SL đang mua / đã mua |
| `selling_quantity` / `sold_quantity` | `int` | SL đang bán / đã bán |
| `t1_sell_quantity` / `t2_sell_quantity` | `int` | SL bán T+1/2 |
| `mortgage_quantity` | `int` | SL cầm cố |
| `restricted_quantity` | `int` | SL hạn chế |

**`DerivativePosition`** — Vị thế phái sinh

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `account_no` | `str` | Số tài khoản |
| `symbol` | `str` | Mã hợp đồng |
| `long` / `short` / `net` | `int` | Vị thế mua / bán / ròng |
| `bid_avg_price` / `ask_avg_price` | `float` | Giá TB mua / bán |
| `trade_price` | `float` | Giá giao dịch |
| `floating_pl` / `trading_pl` | `float` | Lãi/lỗ |

**`Order`** — Thông tin lệnh

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `account_no` | `str` | Số tài khoản |
| `client_request_id` | `str` | ID yêu cầu client |
| `order_id` | `str` | ID lệnh |
| `symbol` | `str` | Mã chứng khoán |
| `side` | `OrderSide` | Mua/Bán |
| `order_type` | `OrderType` | Loại lệnh |
| `price` / `avg_price` | `float` | Giá đặt / Giá TB khớp |
| `quantity` | `int` | SL đặt |
| `os_quantity` | `int` | SL chờ |
| `filled_quantity` | `int` | SL đã khớp |
| `cancel_quantity` | `int` | SL đã huỷ |
| `status` | `OrderStatus` | Trạng thái lệnh |
| `input_time` / `modify_time` | `str` | Thời gian đặt / sửa |
| `message` | `str` | Thông báo |

#### Trading

**`PlaceOrderResponse`** — Kết quả đặt lệnh

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `order_id` | `str` | ID lệnh |
| `client_request_id` | `str` | ID yêu cầu client |
| `status` | `OrderStatus` | Trạng thái |

**`ModifyOrderResponse`** — Kết quả sửa lệnh

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `client_modify_id` | `str` | ID yêu cầu sửa |
| `order_id` | `str` | ID lệnh |
| `client_request_id` | `str` | ID yêu cầu gốc |
| `status` | `OrderStatus` | Trạng thái |

**`CancelOrderResponse`** — Kết quả huỷ lệnh

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `client_cancel_id` | `str` | ID yêu cầu huỷ |
| `order_id` | `str` | ID lệnh |
| `client_request_id` | `str` | ID yêu cầu gốc |
| `status` | `OrderStatus` | Trạng thái |

**`MaxBuySellResponse`** — Sức mua/bán tối đa

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `account_no` | `str` | Số tài khoản |
| `symbol` | `str` | Mã chứng khoán |
| `max_buy_quantity` | `int` | SL mua tối đa |
| `max_sell_quantity` | `int` | SL bán tối đa |
| `margin_ratio` | `str` | Tỷ lệ ký quỹ |
| `purchase_power` | `str` | Sức mua |

#### Conditional Orders (FCO)

**`FCOPlaceResponse`** — Kết quả đặt lệnh điều kiện

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `fco_id` | `str` | Mã định danh lệnh điều kiện |

**`FCOCancelResponse`** — Kết quả huỷ lệnh điều kiện

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `fco_id` | `str` | Mã định danh lệnh điều kiện đã huỷ |

**`FCOListResponse`** — Danh sách lệnh điều kiện (Phân trang)

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `page_index` | `int` | Trang hiện tại |
| `page_size` | `int` | Kích thước trang |
| `items_count` | `int` | Tổng số lượng bản ghi |
| `pages_count` | `int` | Tổng số trang |
| `fco_list` | `list[FCOInfo]` | Danh sách lệnh FCO |

**`FCOInfo`** — Thông tin chi tiết một lệnh điều kiện

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `fco_id` | `str` | Mã lệnh FCO |
| `client_id` | `str` | Username / Client ID |
| `account_no` | `str` | Số tài khoản |
| `quantity` | `int` | Khối lượng đặt |
| `price` | `str` | Giá đặt |
| `price_slip` | `str` | Độ trượt giá |
| `symbol` | `str` | Mã chứng khoán |
| `type` | `FCOType \| None` | Loại lệnh điều kiện |
| `from_date` | `str` | Ngày bắt đầu hiệu lực |
| `to_date` | `str` | Ngày kết thúc hiệu lực |
| `matched_quantity` | `int` | Khối lượng đã khớp |
| `is_place_order` | `bool` | Đã đẩy lệnh vào sổ hay chưa |
| `status` | `FCOStatus \| None` | Trạng thái lệnh FCO |
| `detail` | `str` | Chi tiết trạng thái |
| `params` | `FCOParams \| None` | Tham số kích hoạt lệnh FCO |

**`FCOParams`** — Tham số kích hoạt của lệnh điều kiện

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `stop_price` | `float \| None` | Giá dừng / giá kích hoạt |
| `side` | `OrderSide \| None` | Chiều lệnh (Mua/Bán) |
| `active_price` | `float \| None` | Giá kích hoạt (Trailing Stop) |
| `trailing_amount` | `float \| None` | Khoảng bám sát (Trailing Amount) |
| `tp_active_price` | `float \| None` | Giá kích hoạt chốt lời (Take Profit) |
| `sl_active_price` | `float \| None` | Giá kích hoạt cắt lỗ (Stop Loss) |
| `tp_price` | `str \| None` | Giá chốt lời |
| `sl_price` | `str \| None` | Giá cắt lỗ |
| `tp_slip` | `float \| None` | Trượt giá chốt lời |
| `sl_slip` | `float \| None` | Trượt giá cắt lỗ |
| `operator` | `FCOOperator \| None` | Toán tử so sánh kích hoạt |

**`FCOOrderBookResponse`** — Nhật ký khớp lệnh FCO (Phân trang)

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `page_index` | `int` | Trang hiện tại |
| `page_size` | `int` | Kích thước trang |
| `items_count` | `int` | Tổng số lượng bản ghi |
| `pages_count` | `int` | Tổng số trang |
| `order_book` | `list[FCOOrder]` | Danh sách nhật ký lệnh FCO |

**`FCOOrder`** — Nhật ký giao dịch / thực thi của lệnh FCO

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `fco_id` | `str` | Mã lệnh FCO gốc |
| `account_no` | `str` | Số tài khoản |
| `quantity` | `float` | Khối lượng |
| `price` | `str` | Giá đặt |
| `symbol` | `str` | Mã chứng khoán |
| `side` | `OrderSide \| None` | Chiều lệnh |
| `order_type` | `OrderType \| None` | Loại lệnh con |
| `is_main_order` | `bool` | Là lệnh chính |
| `is_attached_order` | `bool` | Là lệnh kèm theo |
| `created_time` | `str` | Thời gian tạo |
| `updated_time` | `str` | Thời gian cập nhật |
| `unique_id` | `str` | ID duy nhất |
| `order_id` | `str` | Mã lệnh trên sàn |
| `matched_quantity` | `float` | Khối lượng đã khớp |
| `os_quantity` | `float` | Khối lượng chờ khớp |
| `avg_price` | `float` | Giá khớp trung bình |
| `status` | `OrderStatus \| None` | Trạng thái lệnh con |
| `detail` | `str` | Chi tiết |

#### Streaming Messages

**`TradeMessage`** — Dữ liệu khớp lệnh

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `type` | `DataType` | `DataType.TRADE` |
| `trading_time` | `str` | Thời gian |
| `symbol` | `str` | Mã CK |
| `price` | `float \| int` | Giá khớp |
| `quantity` | `int` | KL khớp |
| `side` | `str` | Bên mua/bán (`"B"`, `"S"`, `"U"`) |
| `total_volume` | `int` | Tổng KL |

**`IntervalMessage`** — Dữ liệu OHLCV theo interval

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `type` | `DataType` | `DataType.TRADE` |
| `interval_time` | `str` | Thời gian interval |
| `trading_time` | `str` | Thời gian giao dịch |
| `symbol` | `str` | Mã CK |
| `open` / `high` / `low` / `close` | `float \| int` | Giá OHLC |
| `volume` | `int` | Khối lượng |

**`QuoteMessage`** — Dữ liệu giá bid/ask

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `type` | `DataType` | `DataType.QUOTE` |
| `trading_time` | `str` | Thời gian |
| `symbol` | `str` | Mã CK |
| `bid_prices` / `bid_volumes` | `list[float]` / `list[int]` | Giá/KL bid |
| `ask_prices` / `ask_volumes` | `list[float]` / `list[int]` | Giá/KL ask |

**`ForeignRoomMessage`** — Room nước ngoài

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `type` | `DataType` | `DataType.ROOM` |
| `trading_time` | `str` | Thời gian |
| `symbol` | `str` | Mã CK |
| `total_room` / `current_room` | `int` | Tổng room / Room còn lại |
| `buy_quantity` / `buy_value` | `int` | KL/Giá trị mua NN |
| `sell_quantity` / `sell_value` | `int` | KL/Giá trị bán NN |

**`PutMessage`** — Thoả thuận

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `type` | `DataType` | `DataType.PUT` |
| `trading_time` | `str` | Thời gian |
| `symbol` | `str` | Mã CK |
| `price` | `float` | Giá |
| `quantity` | `int` | Khối lượng |
| `total_quantity` / `total_value` | `int` | Tổng KL / Tổng giá trị |

**`OddLotMessage`** — Lô lẻ

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `type` | `DataType` | `DataType.ODD_LOT` |
| `trading_time` | `str` | Thời gian |
| `symbol` | `str` | Mã CK |
| `price` | `float \| int` | Giá |
| `quantity` | `int` | Khối lượng |
| `bid_prices` / `bid_volumes` | `list[float]` / `list[int]` | Giá/KL bid |
| `ask_prices` / `ask_volumes` | `list[float]` / `list[int]` | Giá/KL ask |

**`MarketStatusMessage`** — Trạng thái thị trường

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `market` | `str` | Thị trường |
| `status` | `str` | Trạng thái |
| `trading_date` | `str` | Ngày giao dịch |

**`OrderStatusMessage`** — Trạng thái lệnh (streaming)

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `type` | `StreamingType` | `StreamingType.ORDER` |
| `account_no` | `str` | Số tài khoản |
| `client_request_id` / `order_id` | `str` | ID yêu cầu / ID lệnh |
| `symbol` | `str` | Mã CK |
| `side` | `OrderSide \| None` | Mua/Bán |
| `order_type` | `OrderType \| None` | Loại lệnh |
| `price` | `float \| int` | Giá |
| `quantity` / `os_quantity` / `filled_quantity` / `cancel_quantity` | `int` | SL đặt / chờ / khớp / huỷ |
| `status` | `OrderStatus \| None` | Trạng thái |
| `input_time` / `modify_time` | `str` | Thời gian đặt / sửa |
| `message` | `str` | Thông báo |

**`FCOOrderUpdateMessage`** — Cập nhật trạng thái lệnh điều kiện FCO (streaming)

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `fco_id` | `str` | Mã lệnh FCO |
| `process_status` | `FCOStatus \| None` | Trạng thái xử lý lệnh FCO (`INIT`, `WAIT`, `WC`, `TER`, ...) |
| `matched_quantity` | `int` | Khối lượng đã khớp |
| `is_place_order` | `bool` | Đã đẩy lệnh vào sổ hay chưa |
| `symbol` | `str` | Mã chứng khoán |
| `quantity` | `int` | Khối lượng đặt |
| `price` | `str` | Giá đặt |
| `account_no` | `str` | Số tài khoản |
| `updated_time` | `str` | Thời gian cập nhật (`YYYY/MM/DD HH:MM:SS`) |
| `status` | `str` | Mã trạng thái |
| `message` | `str` | Thông báo chi tiết / lý do kích hoạt, ngắt kết nối |
| `username` | `str` | Username đặt lệnh |
| `event_type` | `str` | Loại sự kiện (`"fcoEvent"`) |
| `type` | `FCOType \| None` | Loại lệnh điều kiện (`GTD`, `STOP`, ...) |

**`PortfolioMessage`** — Thay đổi danh mục (streaming)

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `type` | `StreamingType` | `StreamingType.PORTFOLIO` |
| `account_no` | `str` | Số tài khoản |
| `total_asset` | `float` | Tổng tài sản |
| `cash_balance` | `float` | Số dư tiền |
| `stock_value` | `float` | Giá trị chứng khoán |

**`HeartbeatMessage`** — Heartbeat

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `method` | `StreamingMethod` | Method |
| `channel` | `StreamingChannel` | Channel |
| `status` | `str` | Trạng thái |
| `message` | `str` | Thông báo |

### Clients & Services

> **Hướng dẫn cho dev/AI agent**: [`AGENT.md`](AGENT.md). **Integration test với API thật**: [`tests/integration/README.md`](tests/integration/README.md).
>
> **Danh mục đầy đủ mọi method public** (chữ ký + mô tả, sinh tự động từ code): [`API_METHODS.md`](API_METHODS.md).

| Client | Service | Truy cập | Mô tả |
|--------|---------|---------|-------|
| `Auth` | `token_manager` | `auth.token_manager` | Xác thực, OTP, refresh token |
| `Data` | `market_data` | `data.market_data` | OHLC, chỉ số, chứng khoán |
| `Trading` | `account` | `trading.account` | Thông tin tài khoản |
| `Trading` | `portfolio` | `trading.portfolio` | Số dư, vị thế, sổ lệnh, PPMMR |
| `Trading` | `trading` | `trading.trading` | Đặt/sửa/huỷ lệnh, sức mua/bán |
| `Stream` | `streaming` | `stream.streaming` | Streaming realtime qua WebSocket |

---
