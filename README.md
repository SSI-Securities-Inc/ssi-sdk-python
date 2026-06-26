# SSI Python SDK

Python SDK cho nền tảng giao dịch chứng khoán SSI. Hỗ trợ REST API và WebSocket streaming, cả đồng bộ (sync) và bất đồng bộ (async).

**Yêu cầu:** Python 3.10+

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
| `streaming_url` | `str` | `"wss://api.ssi.com.vn/ws/v3"` | URL WebSocket streaming |
| `timeout` | `int` | `60` | Timeout request (giây) |
| `max_retries` | `int` | `5` | Số lần retry tối đa |
| `retry_delay` | `float` | `2.0` | Delay cơ sở giữa các lần retry (exponential backoff, giây) |
| `rate_limit_per_second` | `int` | `10` | Giới hạn request/giây (0 = không giới hạn) |
| `log_level` | `str` | `"INFO"` | Mức log: DEBUG, INFO, WARNING, ERROR, CRITICAL |

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
```

### 1.2. Yêu cầu gửi OTP

```python
result = auth.request_otp()
print(result)
```

### 1.3. Làm mới token

```python
token = auth.refresh()
```

### 1.4. Tự động đảm bảo xác thực

```python
# Tự động refresh nếu token hết hạn, hoặc yêu cầu OTP nếu cần
access_token = auth.ensure_authenticated(otp="222222")
```

### 1.5. Kiểm tra trạng thái token

```python
print(auth.token)              # Token object hoặc None
print(auth.access_token)       # Access token string hoặc None
print(auth.is_token_expired)   # True/False
print(auth.has_refresh_token)  # True/False
```

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
- `account_type: AccountType` — Loại tài khoản (`EQUITY`, `EQUITY_MARGIN`, `DERIVATIVE`)

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
| `get_ohlc_1week_historical(symbol, from_date, to_date, page, size)` | 1 tuần |
| `get_ohlc_1month_historical(symbol, from_date, to_date, page, size)` | 1 tháng |

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
print(f"Available cash: {equity_balance.available_cash}")
print(f"Withdrawal: {equity_balance.withdrawal}")

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

### 5.1. Đặt lệnh

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
| `on_trading` | `Callable[[OrderStatusMessage \| PortfolioMessage], Any]` | Nhận trading events |
| `on_heartbeat` | `Callable[[HeartbeatMessage], Any]` | Nhận heartbeat |

> **Lưu ý:** Tất cả subscribe/unsubscribe methods đều hỗ trợ tham số `on_response` (callback cho response message).

### 6.1. Thiết lập callback

```python
# Callback nhận dữ liệu thị trường (tự động parse thành typed message)
def on_market_data(msg):
    print(f"Market data: {msg}")

# Callback nhận dữ liệu giao dịch (OrderStatusMessage | PortfolioMessage)
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
| `order.*` | `OrderStatusMessage` | Trạng thái lệnh |
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
| `APIError` | API trả về lỗi — có thêm `status_code`, `response_body` |
| `WebSocketError` | Lỗi kết nối hoặc giao tiếp WebSocket |
| `ValidationError` | Lỗi validate input |
| `RateLimitError` | Vượt quá giới hạn request — có thêm `retry_after` |

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

#### Portfolio

**`EquityAccountBalance`** — Số dư tài khoản cơ sở

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `account_no` | `str` | Số tài khoản |
| `available_cash` | `float` | Tiền mặt khả dụng |
| `total_debt` | `float` | Tổng nợ |
| `interest_loan` | `float` | Lãi vay |
| `overdue_fee_loan` | `float` | Phí vay quá hạn |
| `withdrawal` | `float` | Rút tiền |
| `on_hold_cash` | `float` | Tiền tạm giữ |
| `sell_unmatched` | `float` | Bán chưa khớp |
| `sell_t0` / `sell_t1` / `sell_t2` | `float` | Bán T+0/1/2 |
| `buy_unmatched` | `float` | Mua chưa khớp |
| `buy_t0` / `buy_t1` / `buy_t2` | `float` | Mua T+0/1/2 |
| `advance_cash_t0` / `advance_cash_t1` | `float` | Ứng trước T+0/1 |
| `hold_subscription` | `float` | Giữ đăng ký |
| `bank_balance` | `float` | Số dư ngân hàng |
| `dividend` / `dividend_margin` | `float` | Cổ tức |
| `block_cash` | `float` | Tiền phong toả |
| `interest_cash` | `float` | Lãi tiền gửi |
| `limit_t0` | `float` | Hạn mức T+0 |
| `term_deposit` | `float` | Tiền gửi kỳ hạn |

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

| Client | Service | Truy cập | Mô tả |
|--------|---------|---------|-------|
| `Auth` | `token_manager` | `auth.token_manager` | Xác thực, OTP, refresh token |
| `Data` | `market_data` | `data.market_data` | OHLC, chỉ số, chứng khoán |
| `Trading` | `account` | `trading.account` | Thông tin tài khoản |
| `Trading` | `portfolio` | `trading.portfolio` | Số dư, vị thế, sổ lệnh, PPMMR |
| `Trading` | `trading` | `trading.trading` | Đặt/sửa/huỷ lệnh, sức mua/bán |
| `Stream` | `streaming` | `stream.streaming` | Streaming realtime qua WebSocket |

---