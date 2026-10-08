# Changelog

All notable changes to `ssi-sdk`. The version in `ssi_sdk/_version.py` is unchanged: the bump
(minor, per the plan) is the SDK owner's call, so everything below is **Unreleased**.

Items marked **BREAKING** change behaviour callers may depend on; the rest are additive or fixes.
Renamed members keep their old name as a read-only alias that emits `DeprecationWarning`.

## 3.3.0 - 2026-10-08

### Security
- Secrets no longer reach logs, reprs or exception text: `Config`, `Token`, `TokenRequest`,
  `OTPRequest`, `RefreshTokenRequest` and `OTPResponse` hide `api_secret`, `private_key`, tokens,
  OTP and `transaction_id` from `repr`; the REST client logs only method and path; the WebSocket
  client no longer logs the `Authorization` header, raw frames or URL query strings; a stray
  `print(request)` is gone; exception `response_body` is masked (`ssi_sdk.utils.redact`).
- `Auth(config, **kwargs)` / `Data(...)` etc. no longer mutate the caller's `Config` and raise
  `TypeError` on an unknown option instead of silently ignoring it.
- **Action for the owner:** a Bearer token used to be written to the log by the WebSocket client;
  revoke/rotate any token that was logged with an older version.

### Added
- IDE experience: full `Args`/`Returns`/`Raises` docstrings on every public method; explicit `Auth`/`AsyncAuth` token
  methods (no more `__getattr__`-only delegation); typed streaming callbacks (`on_market_flag`, `on_order`, ... as real
  typed properties) and `DataMessage`/`TradingMessage`; `PriceLike`, `NumberLike`, `StreamInterval`, `FCOStatusLike`,
  `FCOTypeLike`, `FCOOperatorLike` (enum or valid string); `BatchPlaceOrderItem`/`BatchCancelOrderItem` `TypedDict`s;
  enum members explained in class docstrings; `Attributes:` on response models; explicit `list_fco(...)` filters and
  `TradingWSService.client` / `close()`. `mypy` findings went from 107 to 55.
- `tests/integration`: a real-API suite covering every public method (sync and async from one test body), with three
  explicit safety levels (read-only / resting orders / orders that can fill). See `tests/integration/README.md`.
- `API_METHODS.md` (generated list of every public method) and `tools/gen_api_methods.py`; `AGENT.md` rewritten as a
  full guide for developers and AI agents.
- `OTPResponse` and `request_otp_typed()` (`transaction_id` exists only for Smart OTP).
- Exceptions: `SmartOTPPendingError`, `SmartOTPRejectedError`, `ReauthenticationRequired`,
  `DuplicateRequestError`; `RateLimitError` gained `status_code`, `retry_after`, `limit`,
  `remaining`, `reset`; `APIError` accepts `headers`; all of them are exported from `ssi_sdk`. Enum `ServerErrorCode` covers every
  auth/OTP/refresh/signature/trading/data-validator code documented by the server (aliases for reused numbers);
  any refresh-token-unusable code (401101-401104, 401106-401108) now forces re-authentication.
- `Config`: `trading_api_domain` (URL of the trading REST API: `/api/v3/trading/*` and
  `/api/v3/account/*`; default `https://api.ssi.com.vn`, which follows `api_url`; `trading_api_url` property; the REST client shares the token and
  rate limiter), `trading_ws_domain` (order-entry WebSocket URL, default `wss://api.ssi.com.vn/ws/v3/trading`; `trading_ws_url` property builds `wss://<domain>/ws/v3/trading`), `device_id`, `user_agent`, `auto_reconnect`, `otp_poll_interval`, `otp_poll_max_wait`.
- Market data: `iter_ohlc()` / `get_ohlc_all()`; `securitiesSummary` and `masterdata` follow
  `pagesCount`; foreign-trade fields on `MarketIndexSummary`; `stock_type` on `SecuritiesInfo`;
  optional `ceiling`/`floor`/`ref_price` on `SecuritiesSummary`; `ALLOWED_TIMEFRAMES`.
- Trading: `place_batch_orders()` / `cancel_batch_orders()` (`POST`/`DELETE /order/batch`, <= `Config.max_batch_orders` orders (server default 20), signed over the whole body,
  `BatchOrderRequest`/`BatchOrderResponse`/`BatchOrderResult`); trading WebSocket `subscribe_order_events()`; `sign()` uses RSA
  blinding and verifies its result; one shared FCO field parser for REST and stream models; optional `client_request_id` (idempotency key) on every `place_*` method;
  `get_fco_status_history()`; `OrderStatus` lists every status the servers emit.
- Streaming usability: `unsubscribe_order_status()` / `unsubscribe_portfolio()` / `unsubscribe_all()`; typed callbacks
  `on_market_flag`, `on_order`, `on_order_match`, `on_portfolio` (alongside `on_data`/`on_trading`, which still receive
  everything); `is_connected`, `reconnect_count`, `last_error` and `on_connection` (`ConnectionEvent`: connected /
  reconnected / disconnected / failed); clearer aliases `subscribe_orders`, `subscribe_index_ticks`,
  `subscribe_master_data`, `subscribe_session_flag`; README section 6.0 maps every topic to its method, message and callback.
- Streaming: `list_subscription()`, `subscribe_market()`, `subscribe_index_trade()`,
  `subscribe_index_summary()`, `OrderMatchMessage`, `MarketDataMessage`, position fields on
  `PortfolioMessage`, `avg_price`/`reject_reason`/`error_code`/... on `OrderStatusMessage`,
  open/high/low/average on `TradeMessage`, `ssi_sdk.utils.topic` (validated topic builder).
- Helpers in `ssi_sdk.utils`: `pick`, `is_no_content`, `to_opt_int`, `to_opt_float`, `to_decimal`,
  `to_enum`, `to_price_decimal`, `format_price`, `parse_date`, `require_symbol`,
  `require_date_range`, `require_exactly_one`, `ssi_sdk.utils.redact` (module) and `ssi_sdk.utils.topic` (module).
- EXPERIMENTAL Trading WebSocket (`ssi_sdk.experimental`: `trading_ws`, `async_trading_ws`, `TradingWSClient`,
  `AsyncTradingWSClient`, `TradingWSError`): signed order/FCO commands over `Config.trading_ws_url`.
  Not exported from `ssi_sdk` and not used by `Trading`/`Stream`.
  Aligned with the public Trading WS documentation: the only config is `Config.trading_ws_domain`
  (everything else is the shared `Config`); optional client keywords `signature_encoding`
  (`"base64"` per the documentation, `"hex"` as REST uses; a 401013 error message hints at the
  switch), `handshake_grace` (the refusal frame `{"code","msg"}` sent after HTTP 101 now raises
  `TradingWSError` from `connect()` / the pending request), `respect_rate_limit` /
  `max_rate_limit_wait` (waits for `resetMs` when `remaining == 0`) and `ping_interval`.
  `subscribe_order_events(account_no)` now needs one explicit account; added
  `subscribe_portfolio_events`, `unsubscribe_portfolio_events`, `unsubscribe_all_events`;
  `query_position` sends a boolean `querySummary` (and no empty `clientId`), `query_max_buy_sell`
  a numeric `price`, `fco_status_history` the key `fcoId`, `query_order_book` optional
  `symbol`/`order_status`/`page_index`/`page_size`; `list_fco` takes a single `process_status`.
- Optional OTP `code` for conditional orders: every `place_fco_*`, `cancel_fco`, the FCO params
  classes, `FCOCancelRequest` and the Trading WS `cancel_fco`.
- Streaming: `IndexSummaryMessage` + `on_index_summary` for `indexsummary.<code>` (payload kept raw: the
  public docs list no fields); topic codes are upper-cased (`vn30` -> `VN30`; accounts untouched).
  `FCOOrder` now uses the shared `parse_fco_common` like `FCOInfo` and the stream FCO message.
- `Config`: `api_url`, `streaming_url`, `trading_api_domain` and `trading_ws_domain` fall back to their defaults
  (`ssi_sdk.constant`) when not passed, `None` or blank (before, a blank `trading_ws_domain` built `wss:///...`).
- Tests: the integration suite prints every response/streamed message live (`SSI_IT_PRINT`, `SSI_IT_PRINT_LIMIT`).
- Tests: no OTP in config files; with no usable token the suites ask how to log in (type OTP / approve on the device /
  data only) via `tests/otp_login.py`; `SSI_OTP` (environment) skips the prompt; the legacy manual scripts are no longer collected
  by a plain `pytest`.
- **Breaking:** `Config.device_id` is removed. The `deviceId` of every order/FCO is this machine's id, read from the OS
  (`ssi_sdk.utils.get_device_id()`: the raw, unhashed machine id: macOS `IOPlatformUUID`, Linux machine-id, Windows
  `MachineGuid`, else the MAC address / host name; stable per machine); passing
  `device_id=` to `Config` or a client now raises `TypeError`. A missing device id can no longer fail an order.
- The REST client follows the server's rate-limit headers: `X-RateLimit-Limit` caps the request rate (never above
  `Config.rate_limit_per_second`; 0 stays unlimited), `X-RateLimit-Remaining: 0` rests one second, and a `429` on a `GET` is
  waited out (`Retry-After`, else 1s doubling; at most 3 retries, never a wait over 30s) before `RateLimitError` is raised.
  Orders/`POST`/`PUT`/`DELETE` are never replayed. The last numbers are on `rest_client.rate_limit`.
- `Config.max_batch_orders` (default **20**, the server's default; it was hard-coded to 50): the largest batch for
  `place_batch_orders` / `cancel_batch_orders` (REST and Trading WS).
- Streaming: clearer aliases for the classic topics too (same methods, both services): `subscribe_trades`/`quotes`/`foreign_room`/
  `put_through`/`odd_lot`/`candles`/`exchange_trades`/`index_constituents`/`positions` and their `unsubscribe_…`.
- Fixed (first real Trading WS run): the async client was refused with HTTP 403 by the gateway (the default `websockets`
  User-Agent); both clients now send a browser-like `User-Agent` (`Config.user_agent` wins). The base64 signature was refused
  (401006), so `signature_encoding` defaults to `"auto"`: base64 first, and a refused signature (command not executed) is re-sent
  once as hex and remembered; refused both ways raises one clear error.
- Fixed (real stream): the server sends `market.FLAG` (tail upper-cased), which was not recognised as the session flag and
  came out as an empty `MarketStatusMessage`. Topic types are now matched without regard to case. The flag's board code is
  the server's own (`HOSE`/`HNX`/`UPCOM`/`DER`).
- Streaming: `trade.index.<code>` ticks are now `IndexTickMessage` (the server's `IndexData`: value, change, advances/declines,
  ceilings/floors, totals), not a symbol `TradeMessage`; `Order.from_dict` also reads the order history's `instrumentId`/`buySell`.
  A test checks that the SDK reads every key of the server DTOs listed in `SERVER_MODELS_REFERENCE.md`.
- Fixed (found by the first real-API run): `/data/ohlc` answers 400213 "Invalid Date/Timestamp Format" to a bare `YYYY/MM/DD`;
  OHLC methods now complete a date-only `from`/`to` to `00:00:00` / `23:59:59`. The integration suite defaults to
  `rate_limit_per_second=3` (the server answered 429 to bursts).
- `parse_date` also reads `DD/MM/YYYY HH:MM:SS` (FCO status history times).
- Streaming connections are supervised: reconnect with capped exponential backoff and jitter, a
  fresh token on every connect, a proactive reconnect before the token expires, honouring the
  server's `{"code","msg"}` refusal frames (401/403: refresh once; 429: wait >= 30s), automatic
  resubscribe, and the old socket always closed before a new one opens.

### Changed
- The made-up placeholder MAC `A1:B2:C3:D4:E5:F6` is gone: every order/FCO sends this machine's real id
  (see the `device_id` entry under Added).
- **BREAKING** Only `GET` is retried on timeout. `POST`/`PUT`/`DELETE` (auth, OTP, orders, FCO)
  are sent exactly once.
- **BREAKING** `APIError.code` is the server's error code when the body has one (the HTTP status
  stays in `status_code`; the old string-of-status is the fallback). HTTP 200 carrying `code`
  other than 200/204 now raises `APIError`; the empty-result marker `{"code": 204}` yields empty
  results instead of parse errors.
- **BREAKING** `ensure_authenticated` treats a token with unknown expiry (`expires_at <= 0`) as
  expired, expires tokens 30s early, and raises `ReauthenticationRequired` when the session cannot
  be refreshed (401101/401103 clear the stored token). Concurrent refreshes make one server call.
- **BREAKING** `Account.account_type` is `None` when the server omits it (no default `Cash`) and
  the raw string for an unknown type.
- **BREAKING** `require_non_empty` treats `0`/`False` as present (it still rejects `None`, blank
  strings and empty collections).
- **BREAKING** Streaming `on_response` callbacks receive acks and no longer replace the
  `on_data`/`on_trading`/`on_heartbeat` handler; interval topics accept only `tick`/`1m`/`5m`;
  topics are validated before sending; `OrderStatusMessage.price` is a `Decimal` (or a string for
  ATO/ATC/MP) and `modify_time` is now `modified_time`.
- **BREAKING** `Order.os_quantity` is `None` (the server never sends it); `filled_quantity` and
  `cancel_quantity` read the server's `filledQty`/`cancelQty`.
- FCO: when placing, dates must be `YYYY/MM/DD HH:MM:SS` with `from <= to` and a window of at most 31 days (the contract says so, the server does not check);
  `fco/cancel` sends `deviceId`; `FCOParams.to_dict()` keeps a legitimate `0`; operators given as
  `0..4` in responses are parsed; response models tolerate unknown enum values.
- Prices are sent as plain decimal strings (no exponent notation); `quantity` must be a positive
  integer; `price=None` on a limit order is rejected instead of being sent as `"None"`. Market-priced
  helpers (ATO/ATC/MTL) keep sending `"0"`.
- `maxBuySell` reads `purchasingPower`; derivative responses no longer invent `0` for fields the
  server leaves out. Balance reads `advancedCashT0/T1`, `withdrawableSSI/VSDC`; PPMMR accepts the
  server's key casing; positions send `querySummary` explicitly and parse the derivative object.
- Numeric parsing accepts `"1234.0"`, `"2,493,089"` and rejects inf/nan; `to_price("ATO")` returns
  `OrderType.ATO` instead of `0`.
- Streaming heartbeat parsing no longer raises on the `PING_PONG` ack.

### Deprecated
- `MaxBuySellResponse.purchase_power` -> `purchasing_power`;
  `DerivativeAccountBalance.cash_withdrawable_ssi/_vsdc` -> `withdrawable_ssi/_vsdc`;
  `OrderStatusMessage.modify_time` -> `modified_time`;
  `PortfolioMessage.total_asset/cash_balance/stock_value` (the server never sends them).
- `get_ohlc_1week_historical` / `get_ohlc_1month_historical` now raise `ValidationError`: the
  server rejects those timeframes (400210).

### Fixed
- Server quirks the SDK now shields callers from: minute/hour OHLC with a ``to`` after today (the server then returns
  nothing) is cut to the end of today; ``page``/``size`` < 1 are refused locally (the server validates neither);
  subscribe/unsubscribe requests (and the resubscribe after a reconnect) are split into frames under the server's
  4096-byte ``MaxMessageSize`` (a 600-symbol subscribe was ~9.6 KB in one frame).
- `place_fco_stop`/`place_fco_stop_limit` accept the operator as a string (``"greater_or_equal"``) as the type hint
  promises; anything else raises `ValidationError`.
- The sync `ping(interval=...)` loop kept running after `disconnect()` and raised `WebSocketError` inside its
  background thread; `disconnect()` now stops the ping loop (sync and async) and the loop ends quietly when the
  connection is gone. (Found by the new integration suite.)
- `sign()` raised raw XML/base64 errors for a missing or malformed `private_key`; it now raises `ValidationError`
  (fail closed, no key material in the message).
- FCO and trading-WebSocket params accept `Decimal` numbers (they raised `TypeError` in `json.dumps`).
- `FCOOrderUpdateMessage` no longer raises on an unknown `processStatus`/`type`; FCO responses also read the
  the spec's casing (`price_operator`, `Username`, `IsPlaceOrder`, `matchedQuality`, `uniquedId`) as a fallback.
- A server refusal of a subscription (`Denied (account)`, `Denied (scope)`, `Invalid`) is logged as a warning
  (category only, never the topic/account); a failing user handler is logged with a masked message.
- `MarketIndexes.board_raw`; `DownloadData`/`DownloadDataRequest` documented as deprecated.
- `retry_*` raised `UnboundLocalError` for a negative `max_retries`.
- `_parse_token` marked malformed responses with HTTP 202, which made the Smart OTP poll loop
  treat them as "pending".
- A WebSocket frame that was not a JSON object crashed the receive loop.
- `GTDParams.from_dict` read `side` from the wrong key; `FCOCancelResponse.from_dict` was
  annotated as returning `FCOPlaceResponse`; `_build_fco_params` was a no-op.

### Not implemented (by design, pending decisions)
- Bulk OHLC download (`download_ohlc_*`: the server has no `data/file` endpoint yet).
- Batch order REST and `fcoEvent` streaming.
