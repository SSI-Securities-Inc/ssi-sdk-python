# AGENT.md — guide for any developer or AI agent working with `ssi-sdk`

Everything needed to **use** this SDK and to **change** it safely, in one place. If you read only one
section, read **§3 (hard rules)** — they exist because each one was a real bug or a real risk.

Companion files:

| File | What it is |
|------|------------|
| `API_METHODS.md` | **Complete, generated list of every public method** (signature + one line). Source of truth for "does X exist?" |
| `README.md` | Narrative usage guide (Vietnamese): auth, data, trading, streaming, errors, migration |
| `CHANGELOG.md` | What changed, which changes are breaking, what is deprecated |
| `tests/integration/README.md` | How to run the real-API test suite safely |
| `CLAUDE.md` | Repo conventions for Claude Code (commits, workflow) |

---

## 1. What this is

`ssi-sdk` (package `ssi_sdk`, Python >= 3.10) wraps SSI's **FastConnect v3** API: REST (auth, market data,
account, portfolio, orders, conditional orders) and WebSocket (market data + trading events). It is a
**library** (no server, no database). Runtime dependencies are only `httpx`, `websockets`, `websocket-client`.
Every service exists in a **sync** and an **async** flavour with identical method names and arguments.

```
Facade clients   Auth / Data / Trading / Stream          (+ Async* twins)    ssi_sdk/client.py
   └── Services  token_manager, market_data, account, portfolio, trading, streaming   ssi_sdk/services/
        └── Transport   rest_client (httpx) · websocket_client · dispatch · reconnect · trading_ws
             └── Leaves  models/ · enums/ · utils/ · constant.py · config.py · exceptions.py
```

Dependencies point **one way** (client → services → transport → leaves). Never import upward.

---

## 2. Setup and commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # install from the package index set in PIP_INDEX_URL
.venv/bin/pytest tests/unit -q                 # offline unit tests (fast, no network, no secrets)
.venv/bin/ruff check ssi_sdk                   # lint   (baseline: ~16 pre-existing findings in untouched lines)
.venv/bin/ruff format --check ssi_sdk
python tools/gen_api_methods.py                # regenerate API_METHODS.md after adding/renaming a method
python -m build                                # wheel + sdist
SSI_IT=1 .venv/bin/pytest tests/integration -rs   # real API, read-only (see tests/integration/README.md)
```

Version lives in `ssi_sdk/_version.py`. Do not bump it without the SDK owner's decision.

Repo quirks you **will** trip on:

- **Line endings are CRLF** for everything under `ssi_sdk/`, `README.md`, `AGENT.md`, `CHANGELOG.md`,
  `API_METHODS.md`. A tool that rewrites a file with LF turns the whole file into a diff. Preserve CRLF
  (new files under `ssi_sdk/` too). Files under `tests/` are LF.
- **`tests/` is in `.gitignore`**, so tests are not tracked unless that is changed.
- `ruff --fix` re-sorts imports and can explode `ssi_sdk/models/__init__.py` into a huge diff: don't run it there.
- Docs for users are bilingual by history: README is Vietnamese, this file and docstrings are English.

---

## 3. Hard rules

**Money path (orders, FCO, batch)**
1. Every order/FCO carries a `deviceId` (the server binds orders to a device). It is always this machine's own id
   (`ssi_sdk.utils.get_device_id()`: the raw OS machine id, unhashed and stable) and is **not configurable** (`Config` has no `device_id`).
   No placeholder is ever sent; a missing id raises `ValidationError` before any request.
2. Orders carry an **idempotency key** (`client_request_id`, <= 20 chars; generated if omitted). A reused key
   is HTTP 409 → `DuplicateRequestError`. **Never resend an order under a new id** after a timeout.
3. **Never auto-retry** `POST`/`PUT`/`DELETE` (orders, auth, OTP). Only `GET` retries on timeout.
   Reconcile an uncertain order with its `client_request_id`, the order book, or `order.<account>` events.
4. Prices go out as **plain decimal strings** (`format_price`, no exponent); quantities are positive **integers**.
   Never format a price with `f"{float}"`.
5. Signed requests (`X-Signature`, WebSocket `signature`) sign **exactly the bytes sent**. Never re-serialize a
   body/params after signing. A missing or malformed `private_key` raises `ValidationError` (fail closed).
6. Writing tests that place orders? They must be gated (see §8) and must clean up after themselves.

**Security**
7. **Never log or put in an exception**: tokens, `api_secret`, `private_key`, OTP, `transactionId`, signatures,
   account numbers. Use `ssi_sdk.utils.redact` (`redact`, `mask`, `mask_bearer`, `safe_url`). `repr()` of
   `Config`, `Token`, and request models already hides secrets — keep it that way (`field(repr=False)`).
8. TLS always on; WebSocket URLs must be `wss://` (the clients refuse anything else). The bearer token goes in
   the `Authorization` header, never in the URL.
9. There is **one active session per `apiKey`**: a login/refresh anywhere invalidates other holders of that
   key. Reusing a refresh token revokes the whole session (→ `ReauthenticationRequired`).

**Code conventions**
10. **Sync/async parity**: change `Foo` and `AsyncFoo` together, same signature. `API_METHODS.md` reports a
    "Parity warning" if they drift, and a test fails.
11. **Models**: stdlib `@dataclass`, manual `to_dict`/`from_dict` (no Pydantic, no new dependencies without
    team approval). Optional fields are `T | None = None`. Add new fields at the **end**.
12. **`from_dict` must never raise on unfamiliar server data.** Use `pick` (several keys), `to_enum` (unknown
    value stays a raw string), `to_opt_int`/`to_opt_float` (missing ≠ 0), `to_decimal`. Validation lives in
    `utils/validator.py` and the services, not in `from_dict`.
13. **Protocol values are enums** (`OrderSide`, `OrderType`, `OrderStatus`, `Board`, `Timeframe`, `FCOType`,
    `FCOOperator`, `FCOStatus`, `ServerErrorCode`, …), never raw strings, in your own code.
14. Server data oddities are handled once, in helpers: `{"code": 204}` means "empty result" (`is_no_content`);
    all numbers arrive as strings (`to_int("1,234.0")` works); token `expiresAt` is **seconds**.
15. Raise only `SSIError` subclasses; wrap `httpx`/websocket errors you handle. Renamed public members keep the
    old name as a read-only alias that emits `DeprecationWarning`.
16. Changing behaviour? Update `README.md`, `CHANGELOG.md` (mark **BREAKING**), regenerate `API_METHODS.md`,
    and add tests.

---

## 4. Using the SDK

### 4.1 Configuration

```python
from ssi_sdk import Config
config = Config(client_id="...", api_key="...", api_secret="...",
                private_key="<base64 of the XML RSA key>")
```

| Option | Default | Meaning |
|--------|---------|---------|
| `api_url` / `streaming_url` / `trading_api_domain` / `trading_ws_domain` | `https://api.ssi.com.vn` / `wss://stream.ssi.com.vn/ws/v3` / `https://api.ssi.com.vn` / `wss://api.ssi.com.vn/ws/v3/trading` | the four endpoints, all written as full URLs. `Config.trading_api_url` = host of `/api/v3/trading/*` and `/api/v3/account/*` (follows `api_url` while `trading_api_domain` is left at the default; auth and data always use `api_url`). `Config.trading_ws_url` = the trading WS URL (experimental). A bare `host[:port]` is accepted for both and gets `https://` / `wss://` |
| `api_key`, `api_secret`, `private_key`, `client_id` | `""` | credentials; `private_key` signs orders |
| `user_agent` | `None` | HTTP + order payload User-Agent (a browser-like default is kept for WAF reasons) |
| `timeout` / `max_retries` / `retry_delay` | 60 / 5 / 2.0 | HTTP timeout, GET retries, backoff base |
| `rate_limit_per_second` | 10 | client-side throttle (0 = off) |
| `auto_reconnect` | `True` | re-open a dropped streaming socket |
| `otp_poll_interval` / `otp_poll_max_wait` | 5.0 / 60.0 | Smart OTP approval polling |
| `proxy`, `log_level` | `None`, `INFO` | |

### 4.2 Authentication

```python
from ssi_sdk import Auth, Data, Trading, Stream
with Auth(config) as auth:
    auth.ensure_authenticated(otp="123456")     # login (or reuse/refresh a live token)
    data, trading, stream = Data(auth), Trading(auth), Stream(auth)   # share the token
```

| Situation | Call |
|-----------|------|
| SMS/e-mail OTP, or the code shown in the Smart OTP app | `auth.ensure_authenticated(otp="…")` |
| Smart OTP push-approval | `o = auth.request_otp_typed()` then `auth.ensure_authenticated(transaction_id=o.transaction_id)` (polls) |
| Token from elsewhere (cache) | `auth.set_token(Token(...))` then `auth.ensure_authenticated()` |
| Market data only | `auth.authenticate()` without OTP (no trading rights; do not mix with an OTP session of the same apiKey) |

Tokens expire early by 30 s; unknown expiry counts as expired. Refresh is single-flight per process.
Async twins: `AsyncAuth`, `AsyncData`, `AsyncTrading`, `AsyncStream` (use `async with` / `await`).

### 4.3 Which method for which job

Full signatures: **`API_METHODS.md`**. Reach services through the facades:
`data.market_data`, `trading.account`, `trading.portfolio`, `trading.trading`, `stream.streaming`.

| I want to… | Use |
|------------|-----|
| today's / historical candles | `get_ohlc_<1minute\|3minute\|5minute\|15minute\|1hour>(symbol)`, `…_historical(symbol, from, to, page, size)`, `get_ohlc_1day_historical` (1w/1M are **not** supported by the server → `ValidationError`) |
| *all* candles of a range | `get_ohlc_all(symbol, Timeframe.DAY_1, from, to)` / lazily `iter_ohlc(...)` (server sends newest first) |
| indexes, index/board summary | `get_indexes`, `get_indexes_by_board`, `get_index_summary[_historical]`, `get_board_summary[_historical]` |
| security info / summary / ceiling-floor | `get_securities_info[_by_index\|_by_board]`, `get_securities_summary[_historical\|_by_index…]`, `get_master_data[_historical]` |
| accounts, balances, positions, orders, margin | `get_account_info`, `get_equity_balance`, `get_derivative_balance`, `get_equity_positions`, `get_derivative_positions` (+ `open`/`closed`), `get_today_orders`, `get_historical_orders`, `get_equity_ppmmr`, `get_derivative_ppmmr` |
| max buy/sell | `get_max_buy_sell(account, symbol, price)`, `get_max_buy_sell_at_market_price` |
| place a limit order | `place_limit_order(account, symbol, side, qty, price, client_request_id=None)` |
| market / ATO / ATC | `place_market_order`, `place_ato_order`, `place_atc_order` (**can fill immediately**) |
| any order type | `place_order(account, symbol, side, qty, price, order_type, client_request_id=None)` |
| modify / cancel | `modify_order_price[_by_order_id]`, `modify_order_quantity[_by_order_id]`, `cancel_order`, `cancel_order_by_order_id` (exactly one id; price **or** quantity per call) |
| many orders at once | `place_batch_orders([...])`, `cancel_batch_orders([...])` (<= 50, all-or-nothing) |
| conditional orders | `place_fco_gtd/stop/stop_limit/trailing_stop/trailing_stop_limit/oco/bull_bear`, `cancel_fco`, `get_fco_by_*`, `get_fco_order_book`, `get_fco_status_history` |
| live data / events | see §5 |

FCO dates must be `"YYYY/MM/DD HH:MM:SS"`, `from <= to`, window <= 31 days.

---

## 5. Streaming

```python
stream.streaming.on_market_flag = lambda m: print(m.board, m.flag)     # typed callbacks…
stream.streaming.on_data = lambda m: ...                               # …or everything on a channel
stream.streaming.connect()                      # reconnects by itself, re-sending subscriptions
stream.streaming.subscribe_symbol_trade(["SSI"])
stream.streaming.subscribe_session_flag()
stream.streaming.wait()
```

| Want | Subscribe / Unsubscribe | Message | Typed callback |
|------|--------------------------|---------|----------------|
| trades of a symbol | `subscribe_symbol_trade` / `unsubscribe_symbol_trade` | `TradeMessage` | `on_data` |
| `tick`/`1m`/`5m` candles | `subscribe_symbol_ohlcv(symbols, "1m")` | `IntervalMessage` | `on_data` |
| quotes, room, put-through, odd lot | `subscribe_symbol_quote\|room\|put_through\|odd_lot` | `QuoteMessage`… | `on_data` |
| members of an index / board | `subscribe_index`, `subscribe_board` | trade+quote+room | `on_data` |
| classic topics, clearer names | `subscribe_trades` `quotes` `foreign_room` `put_through` `odd_lot` `candles` `exchange_trades` `index_constituents` `positions` (each with `unsubscribe_…`) | same as the original methods | same |
| **ticks of the index itself** | `subscribe_index_trade` (= `subscribe_index_ticks`) | `IndexTickMessage`/`IntervalMessage` | `on_data` |
| ceiling/floor/reference | `subscribe_market` (= `subscribe_master_data`) | `MarketDataMessage` | `on_data` |
| **session flags (ATO/LO/ATC…)** | `subscribe_market_flag` (= `subscribe_session_flag`) | `MarketFlagMessage` | `on_market_flag` |
| **index summary (`indexsummary.VN30`)** | `subscribe_index_summary` | `IndexSummaryMessage` (`index`, raw `data`, `get()`) | `on_index_summary` |
| order status **and** fills | `subscribe_order_status` (= `subscribe_orders`) | `OrderStatusMessage`, `OrderMatchMessage` | `on_order`, `on_order_match` |
| derivative positions | `subscribe_portfolio` | `PortfolioMessage` | `on_portfolio` |
| what is subscribed / drop all | `list_subscription()` / `unsubscribe_all()` | | |

Notes: setting a callback does **not** subscribe; `on_response` receives the server **ack** and never replaces
`on_data`; intervals other than `tick/1m/5m` and `asset.*`/`margin.*` topics raise `ValidationError`;
`order.*` needs a token that owns the account (else the ack says `Denied (account)`, which is logged).
Connection state: `is_connected`, `reconnect_count`, `last_error`, `on_connection(ConnectionEvent)` with state
`connected | reconnected | disconnected | failed`.

**Trading WebSocket (EXPERIMENTAL)**: `from ssi_sdk.experimental import trading_ws, async_trading_ws` — signed
order/FCO/batch/query commands over `/ws/v3/trading`, plus `subscribe_order_events`. Not part of the facades;
the server side is not announced as released. Order calls return the `PD` ack; outcomes come as events.
The URL is `Config.trading_ws_domain` (normalised by `Config.trading_ws_url`); tunables are keyword arguments:
`trading_ws(auth, signature_encoding="auto", ping_interval=None, ...)`. `"auto"` (default) signs as base64 (the public documentation) and, when
the server refuses a signature (401006/401008/401013: the command was not executed), re-sends that command once as hex and remembers
the one that works; pass `"base64"` or `"hex"` to fix it. The upgrade request carries a browser-like `User-Agent` (the gateway's
firewall answered 403 to the bare `websockets` one). The server may
refuse *after* HTTP 101 with `{"code","msg"}`: `connect()` raises `TradingWSError` (401 token, 403 scope,
429 limit). Subscriptions need one explicit account (`subscribe_order_events` / `subscribe_portfolio_events`).

---

## 6. Errors

```
SSIError
├── AuthenticationError ── SmartOTPPendingError · SmartOTPRejectedError · ReauthenticationRequired
├── APIError ───────────── DuplicateRequestError (HTTP 409)
├── RateLimitError         (429; retry_after, limit, remaining; no reset time from the server)
├── ValidationError        (input rejected locally, nothing was sent)
└── WebSocketError ─────── TradingWSError (status, error_code, server_message)
```

`APIError.code` is the **server's** code (e.g. `400107`) when the body has one, else the HTTP status as a string;
`status_code` is always HTTP. `ServerErrorCode.from_value(code)` names it (unknown → `None`, never raises).
HTTP 200 with a `{code, msg}` body whose code is not 200/204 is an `APIError` too.

| You get | Do |
|---------|----|
| `ReauthenticationRequired` | stop; a new OTP is needed (do not retry) |
| `SmartOTPPendingError` | the user has not approved yet; call again with the same `transaction_id` |
| `DuplicateRequestError` | the order/batch id was already used: look the order up, don't resend |
| `RateLimitError` | wait `retry_after` |
| `ValidationError` | fix the input; nothing reached the server |
| `httpx.TimeoutException` on an order | **unknown outcome**: reconcile before doing anything |

---

## 7. Where things live

| Task | Files |
|------|-------|
| new REST method | `services/<area>.py` (sync **and** `Async*`), models in `models/<area>.py`, endpoint in `constant.py` |
| response parsing | `models/*.from_dict` + helpers in `utils/converter.py` |
| input validation | `utils/validator.py`, service `_build_*` functions |
| streaming topic / message | `utils/topic.py`, `models/streaming.py`, `services/streaming.py` (`_parse_data_message`, `_parse_trading_message`) |
| reconnect / frame routing | `transport/reconnect.py`, `transport/dispatch.py`, `transport/websocket_client.py` |
| error mapping | `transport/rest_client.py::_handle_response`, `exceptions.py`, `enums/error.py` |
| signing | `utils/crypto.py` (RSA PKCS#1 v1.5 / SHA-256, hex; key = base64 of XML) |

---

## 8. Testing

**Unit tests** (`tests/unit`, offline): `httpx.MockTransport` for REST, fake sockets for WebSocket,
`tests/unit/rsa_keys.py` generates a throw-away RSA key at run time (no secrets in the repo). Use
server-shaped payloads (strings for numbers, `{"code": 204}` for empty). A change to the money path needs a test
that verifies the signature against the exact bytes sent.

**Guards that fail when you forget something**: `test_api_methods_doc.py` (regenerate `API_METHODS.md`),
`test_user_facing_api.py` (every public method documented in README; every `subscribe_*` has an `unsubscribe_*`),
`tests/integration/test_method_coverage.py` (every method has an integration test).

**Integration tests** (`tests/integration`, real API): off by default; three safety levels — `SSI_IT=1` (read-only),
`+ SSI_IT_WRITE=yes-place-real-orders` (resting orders at the floor price, always cancelled),
`+ SSI_IT_MARKET_ORDERS=yes-fill-real-orders` (can fill). One test body runs in sync **and** async mode through the
`api` fixture (`await api.call(service, "method", ...)`). Read `tests/integration/README.md` before running.
Integration runs print every response live (`SSI_IT_PRINT=0` to silence, `SSI_IT_PRINT_LIMIT` to cap; secrets masked, account
numbers not).
The OTP is never read from `tests/config.json`: with no usable cached token the suite asks in the terminal how to log in
(type the OTP / approve the Smart OTP push on the device / data only); `SSI_OTP` in the environment skips the question for one run.
The older manual scripts (`tests/data`, `tests/trading`, `tests/async_*`, `tests/test_*.py`) are skipped by a plain `pytest`
(`tests/conftest.py`); run them directly, e.g. `python tests/trading/test_account.py`.
Do **not** run write levels unattended or on an account you do not want real orders on.

When you add a method: implement sync+async → add a unit test → add an integration test → regenerate
`API_METHODS.md` → mention it in `README.md` → add a `CHANGELOG.md` line.

---

## 8b. Keeping IDE suggestions good (this is an SDK: the signatures *are* the product)

Guards in `tests/unit/test_ide_experience.py` fail when you forget one of these:

- Every public method: full Google-style docstring — **every** parameter under `Args:`, a `Returns:` when it returns
  something, `Raises:` for the errors a caller must handle. Match the style of the neighbours.
- Never expose behaviour through `__getattr__`, `setattr`, `property` factories or `**kwargs`: IDEs cannot see it.
  Write the method/property out (as `Auth` and the streaming callbacks do). Explicit keyword arguments beat `**filters`.
- Annotate what the code *accepts*: `PriceLike` for prices, `NumberLike` for numeric request fields, `Literal` aliases
  (`StreamInterval`, `FCOStatusLike`, ...) for fixed strings, `TypedDict` for dict-shaped arguments
  (`BatchPlaceOrderItem`), message classes in callback signatures. If an annotation promises strings, convert them
  at runtime (see `_operator`).
- New enum member → explain it in the enum's class docstring (``Members:`` list). New response model → `Attributes:`.
- Run `mypy ssi_sdk --ignore-missing-imports` (dev tool; not a project dependency): do not add errors.

---

## 9. Common confusions (read before guessing)

- `subscribe_index(["VN30"])` = trades of the **members**; `subscribe_index_trade(["VN30"])` = ticks of the **index**.
- `subscribe_market` = master data (ceiling/floor/ref); `subscribe_market_flag` = session phase flags.
- `subscribe_order_status` also delivers **fills** (`OrderMatchMessage`); use `on_order_match` for those.
- OHLC historical calls return **one page, newest first**; use `get_ohlc_all`/`iter_ohlc` for everything.
- Empty server results are `{"code": 204}`, not `[]`: helpers already map them to empty lists.
- `expiresAt` is **seconds**; `ATO/ATC/MP` prices come back as words (`"ATO"`), not numbers (`OrderType` member).
- `account_type` may be an `AccountType`, a raw string (unknown type) or `None`.
- `os_quantity` on orders is always `None` (the server does not send it); fills are `filled_quantity`.
- Placing many FCO types: the server currently insists on `price > 0` for OCO/MP/MOK/MTL; the SDK pads those
  fields as before, so a rejection there is a **server** issue.

---

## 10. Minimal end-to-end examples

```python
# Sync: read data, place a limit order, cancel it
from ssi_sdk import Auth, Config, Data, Trading
from ssi_sdk.enums import OrderSide

config = Config(api_key="...", api_secret="...", private_key="...")
with Auth(config) as auth:
    auth.ensure_authenticated(otp="123456")
    bars = Data(auth).market_data.get_ohlc_1day_historical("SSI", "2026/03/01", "2026/03/27")
    t = Trading(auth).trading
    placed = t.place_limit_order("1234561", "SSI", OrderSide.BUY, 100, 27_000, client_request_id="my-key-1")
    t.cancel_order_by_order_id("1234561", placed.order_id)
```

```python
# Async: stream order events and session flags
import asyncio
from ssi_sdk import AsyncAuth, AsyncStream, Config

async def main():
    async with AsyncAuth(Config(api_key="...", api_secret="...")) as auth:
        await auth.ensure_authenticated(otp="123456")
        s = AsyncStream(auth).streaming
        s.on_order_match = lambda m: print("fill", m.symbol, m.match_qty, m.match_price)
        s.on_market_flag = lambda m: print(m.board, m.flag)
        s.on_connection = lambda e: print("connection:", e.state)
        await s.connect()
        await s.subscribe_orders("1234561")
        await s.subscribe_session_flag()
        await s.wait()

asyncio.run(main())
```
