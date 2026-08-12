# AGENT.md — AI Agent Integration Guide for ssi-sdk

This guide provides AI coding assistants (Claude, Gemini, Cursor, Copilot, etc.) with instructions, code patterns, architectural conventions, and an API cheatsheet for integrating and interacting with the `ssi-sdk` Python package.

---

## 1. Overview & Architecture

`ssi-sdk` is a lightweight, pure-Python wrapper for SSI's **FastConnect v3 API**. It provides both **synchronous** and **asynchronous (async/await)** clients for:
- Authentication & Token Management (OTP, Refresh Token, File Caching)
- Market Data (OHLC, Index, Securities Information & Summary)
- Trading & Portfolio (Order placement/modification/cancellation, FCO conditional orders, Account balances, Positions, PPMMR)
- Realtime Streaming (WebSocket market data & trading events)

### Layering & Structure
```
Facade Client (Auth/Data/Trading/Stream)
   └── Services (MarketData, Account, Portfolio, Trading, Streaming)
        └── Transport (REST / WebSocket Clients)
             └── Leaf Modules (models, enums, utils, constant, config)
```

### Key Architectural Constraints for AI Agents
1. **Dual Sync/Async Parity**: Every service (`DataService`, `TradingService`, `PortfolioService`, etc.) has a corresponding `Async*` counterpart (`AsyncDataService`, `AsyncTradingService`, etc.) with identical method signatures and return types.
2. **Dataclass Models (No Pydantic)**: Request/Response models are implemented with stdlib `@dataclass` using manual `to_dict()` and `from_dict()` serialization.
3. **Type Safety with Enums**: All protocol constants (OrderSide, OrderType, OrderStatus, Board, AccountType, FCOType, FCOOperator, FCOStatus, Timeframe) are defined as Enums in `ssi_sdk.enums`.
4. **Context Manager Lifecycle**: Always use context managers (`with` / `async with`) to ensure transport connections and HTTP sessions are cleanly initialized and closed.

---

## 2. Authentication & Setup Pattern

### Configuration Initialization
```python
from ssi_sdk import Config

config = Config(
    client_id="YOUR_CLIENT_ID",
    api_key="YOUR_API_KEY",
    api_secret="YOUR_API_SECRET",
    private_key="YOUR_PRIVATE_KEY",
)
```

### Sync Authentication Flow with Token Cache
```python
from ssi_sdk import Auth, Trading, Config
from tests.auth_helper import ensure_auth # or custom token management

config = Config(...)
with Auth(config) as auth:
    ensure_auth(auth) # Handles OTP prompt or refreshes token from cache
    with Trading(auth) as trading:
        accounts = trading.account.get_account_info()
```

### Async Authentication Flow with Token Cache
```python
import asyncio
from ssi_sdk import AsyncAuth, AsyncTrading, Config
from tests.auth_helper import ensure_auth_async

async def main():
    async with AsyncAuth(config) as auth:
        await ensure_auth_async(auth)
        async with AsyncTrading(auth) as trading:
            accounts = await trading.account.get_account_info()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 3. Public API Cheatsheet for AI Agents

### 3.1 Market Data (`data.market_data` / `async_data.market_data`)

| Method | Parameters | Return Type | Description |
|--------|------------|-------------|-------------|
| `get_ohlc` | `symbol`, `from_date`, `to_date`, `resolution`, `page_index`, `page_size` | `OHLCData` | Query candle OHLCV data |
| `get_market_indexes` | `index_id` | `MarketIndexes` | Get list of market indexes |
| `get_market_index_summary` | `index_id`, `from_date`, `to_date`, `page_index`, `page_size` | `MarketIndexSummary` | Summary metrics for an index |
| `get_securities_info` | `symbol`, `market`, `page_index`, `page_size` | `SecuritiesInfo` | Security details (listed shares, lot size, etc.) |
| `get_securities_summary` | `symbol`, `market`, `page_index`, `page_size` | `SecuritiesSummary` | Summary of stock transactions |

### 3.2 Account & Portfolio (`trading.account` & `trading.portfolio`)

| Service | Method | Return Type | Description |
|---------|--------|-------------|-------------|
| `account` | `get_account_info()` | `list[Account]` | Query list of sub-accounts |
| `portfolio` | `get_equity_balance(account_no)` | `EquityAccountBalance` | Cash balance & debt for cash/margin account |
| `portfolio` | `get_derivative_balance(account_no)` | `DerivativeAccountBalance` | Balance & margin for derivative account |
| `portfolio` | `get_equity_positions(account_no)` | `list[EquityPosition]` | Equity stock holdings |
| `portfolio` | `get_derivative_positions(account_no)` | `list[DerivativePosition]` | Derivative contract positions |
| `portfolio` | `get_today_orders(account_no)` | `list[Order]` | Intraday orders |
| `portfolio` | `get_historical_orders(account_no, from_date, to_date)` | `list[Order]` | Historical order book entries |
| `portfolio` | `get_equity_ppmmr(account_no)` | `EquityPPMMR` | Purchasing power & margin ratio (Equity) |
| `portfolio` | `get_derivative_ppmmr(account_no)` | `DerivativePPMMR` | Purchasing power & margin ratio (Derivative) |

### 3.3 Standard Trading (`trading.trading`)

| Method | Parameters | Return Type | Description |
|--------|------------|-------------|-------------|
| `place_limit_order` | `account_no`, `symbol`, `side`, `quantity`, `price` | `PlaceOrderResponse` | Place LO order |
| `place_market_order` | `account_no`, `symbol`, `side`, `quantity` | `PlaceOrderResponse` | Place MTL market order |
| `place_ato_order` | `account_no`, `symbol`, `side`, `quantity` | `PlaceOrderResponse` | Place ATO opening order |
| `place_atc_order` | `account_no`, `symbol`, `side`, `quantity` | `PlaceOrderResponse` | Place ATC closing order |
| `place_order` | `account_no`, `symbol`, `side`, `quantity`, `price`, `order_type` | `PlaceOrderResponse` | Place order with custom OrderType |
| `modify_order_price` | `account_no`, `client_request_id`, `price` | `ModifyOrderResponse` | Modify order price by request ID |
| `modify_order_quantity` | `account_no`, `client_request_id`, `quantity` | `ModifyOrderResponse` | Modify order quantity by request ID |
| `cancel_order` | `account_no`, `client_request_id` | `CancelOrderResponse` | Cancel order by request ID |
| `cancel_order_by_order_id` | `account_no`, `order_id` | `CancelOrderResponse` | Cancel order by server order ID |
| `get_max_buy_sell` | `account_no`, `symbol`, `price` | `MaxBuySellResponse` | Max buy/sell qty at given price |

### 3.4 Flexible Conditional Orders - FCO (`trading.trading`)

| Method | Key Parameters | Return Type | Description |
|--------|----------------|-------------|-------------|
| `place_fco_gtd` | `account_no`, `symbol`, `side`, `quantity`, `price`, `price_slip`, `from_date`, `to_date` | `FCOPlaceResponse` | Good Till Date order |
| `place_fco_stop` | `account_no`, `symbol`, `side`, `quantity`, `stop_price`, `operator`, `from_date`, `to_date` | `FCOPlaceResponse` | Stop Market order |
| `place_fco_stop_limit` | `account_no`, `symbol`, `side`, `quantity`, `price`, `price_slip`, `stop_price`, `operator`, `from_date`, `to_date` | `FCOPlaceResponse` | Stop Limit order |
| `place_fco_trailing_stop` | `account_no`, `symbol`, `side`, `quantity`, `active_price`, `trailing_amount`, `from_date`, `to_date` | `FCOPlaceResponse` | Trailing Stop Market |
| `place_fco_trailing_stop_limit` | `account_no`, `symbol`, `side`, `quantity`, `active_price`, `trailing_amount`, `price_slip`, `from_date`, `to_date` | `FCOPlaceResponse` | Trailing Stop Limit |
| `place_fco_oco` | `account_no`, `symbol`, `side`, `quantity`, `tp_active_price`, `sl_active_price`, `tp_price`, `sl_price`, `tp_slip`, `sl_slip`, `from_date`, `to_date` | `FCOPlaceResponse` | One-Cancels-the-Other |
| `place_fco_bull_bear` | `account_no`, `symbol`, `side`, `quantity`, `price`, `price_slip`, `tp_active_price`, `sl_active_price`, `tp_price`, `sl_price`, `tp_slip`, `sl_slip`, `from_date`, `to_date` | `FCOPlaceResponse` | Bull Bear order |
| `cancel_fco` | `fco_id` | `FCOCancelResponse` | Cancel FCO by ID |
| `get_fco_by_account_no` | `account_no`, `page_index`, `page_size` | `FCOListResponse` | List account's FCO orders |
| `get_fco_by_symbol` | `account_no`, `symbol`, `page_index`, `page_size` | `FCOListResponse` | Filter FCO orders by symbol |
| `get_fco_by_status` | `account_no`, `process_status`, `page_index`, `page_size` | `FCOListResponse` | Filter FCO by status (`TRIT`, `WAIT`, etc.) |
| `get_fco_by_date` | `account_no`, `from_date`, `to_date`, `page_index`, `page_size` | `FCOListResponse` | Filter FCO by date range |
| `get_fco_by_id` | `account_no`, `fco_id` | `FCOInfo \| None` | Single FCO order details |
| `get_fco_order_book` | `fco_id`, `page_index`, `page_size` | `FCOOrderBookResponse` | Execution logs of FCO |

---

## 4. Code Examples for Common AI Tasks

### Example 1: Placing & Instantly Cancelling a GTD Order (Safe Integration Pattern)
```python
from datetime import datetime, timedelta
from ssi_sdk.enums import OrderSide, OrderType

now = datetime.now()
from_date = now.strftime("%Y/%m/%d 00:00:00")
to_date = (now + timedelta(days=7)).strftime("%Y/%m/%d 23:00:00")

# 1. Place GTD order
gtd_res = trading.trading.place_fco_gtd(
    account_no="1234561",
    symbol="SSI",
    side=OrderSide.BUY,
    quantity=100,
    price=OrderType.MTL,
    price_slip=0.5,
    from_date=from_date,
    to_date=to_date,
)
print(f"Placed FCO ID: {gtd_res.fco_id}")

# 2. Immediately cancel FCO order
cancel_res = trading.trading.cancel_fco(fco_id=gtd_res.fco_id)
print(f"Cancelled FCO ID: {cancel_res.fco_id}")
```

### Example 2: Realtime Streaming Callbacks (Market Data & Trading Events)
```python
from ssi_sdk import Stream, AsyncStream

def on_market_data(msg):
    # msg can be TradeMessage, QuoteMessage, IntervalMessage, etc.
    print(f"[Market Data] {msg.symbol}: {msg}")

def on_trading_event(msg):
    # msg can be OrderStatusMessage, FCOOrderUpdateMessage, or PortfolioMessage
    print(f"[Trading Event] Account {msg.account_no}: {msg}")

def on_heartbeat(msg):
    print(f"[Heartbeat] Status: {msg.status}")

# Attach callbacks before connecting
stream.streaming.on_data = on_market_data
stream.streaming.on_trading = on_trading_event
stream.streaming.on_heartbeat = on_heartbeat

stream.streaming.connect()
stream.streaming.subscribe_symbol(["SSI", "VN30F2608"])
stream.streaming.subscribe_order_status(account_no="1234561")
```

---

## 5. Rules & Guidelines for AI Code Generators

1. **Date Format for FCO**: FCO date arguments (`from_date`, `to_date`) **must** be formatted as `"YYYY/MM/DD HH:MM:SS"` (e.g. `"2026/07/21 00:00:00"`).
2. **Never hardcode secrets**: Access tokens, private keys, consumer secrets, and OTPs should never be committed to git. Use `token_cache.json` or environment variables.
3. **Use Enum constants**: Do not pass raw strings like `"B"` or `"LO"` when calling API methods—always pass `OrderSide.BUY`, `OrderType.LO`, `FCOOperator.GREATER_OR_EQUAL`.
4. **Maintain Parity**: If you add or modify a service method in `TradingService`, update `AsyncTradingService` with the exact same signature.
5. **No Pydantic Dependencies**: Keep the minimal dependency design intact. Use `@dataclass` with `to_dict()` and `from_dict()`.
