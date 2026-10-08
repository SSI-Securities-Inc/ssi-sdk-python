"""Protocol constants for SSI SDK (fixed by server/spec, not user-configurable)."""

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
# Page size SDK requests are sent with. The server defaults to 10 and has no upper bound, so
# a large explicit size is chosen on purpose to cut round trips (and, for the order book,
# because the server pages it unreliably, see server issue S-06); it is always sent explicitly.
DEFAULT_SIZE = 1000
DEFAULT_PAGE = 1
# ---------------------------------------------------------------------------
# Rate Limiting & Retries
# ---------------------------------------------------------------------------
DEFAULT_TIMEOUT = 60  # seconds
DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_DELAY = 2  # seconds (base for exponential backoff)
DEFAULT_RATE_LIMIT_PER_SECOND = 10
# The server states its quota in ``X-RateLimit-Limit`` and, on 429, ``Retry-After``; the REST client
# follows them. A 429 on a GET is waited out and retried this many times, never longer than this.
RATE_LIMIT_MAX_RETRIES = 3
RATE_LIMIT_DEFAULT_WAIT = 1.0  # seconds when the 429 carries no Retry-After (doubles per retry)
RATE_LIMIT_MAX_WAIT = 30.0  # a longer wait is not taken silently: the RateLimitError is raised
WS_THREAD_JOIN_TIMEOUT = 5  # seconds

# ---------------------------------------------------------------------------
# HTTP Headers & Auth
# ---------------------------------------------------------------------------
HEADER_CONTENT_TYPE = "Content-Type"
HEADER_ACCEPT = "Accept"
HEADER_AUTHORIZATION = "Authorization"
HEADER_RETRY_AFTER = "Retry-After"
HEADER_RATE_LIMIT_LIMIT = "X-RateLimit-Limit"
HEADER_RATE_LIMIT_REMAINING = "X-RateLimit-Remaining"
HEADER_SIGNATURE = "X-Signature"
HEADER_USER_AGENT = "User-Agent"
CONTENT_TYPE_JSON = "application/json"
AUTH_SCHEME_BEARER = "Bearer "
DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# ---------------------------------------------------------------------------
# API Endpoints — Base URLs
# (HTTP status codes are defined in ssi_sdk.enums.HTTPStatus)
# ---------------------------------------------------------------------------
DEFAULT_API_URL = "https://api.ssi.com.vn"
DEFAULT_STREAMING_URL = "wss://stream.ssi.com.vn/ws/v3"
# Paths served by the trading API (orders, FCO, account, portfolio). They go to
# ``Config.trading_api_url``, which is ``api_url`` unless ``trading_api_domain`` is set.
TRADING_API_PATH_PREFIXES = ("/api/v3/trading", "/api/v3/account")
# Trading WebSocket (order entry over a socket). Experimental; nothing in the facade clients
# connects to it. Its domain differs from the market-data stream (SSI developer portal,
# "Kết nối WebSocket API": wss://api.ssi.com.vn/ws/v3/trading), so it has its own setting.
TRADING_WS_PATH = "/ws/v3/trading"
DEFAULT_TRADING_WS_DOMAIN = "wss://api.ssi.com.vn" + TRADING_WS_PATH
# Trading REST host. While ``Config.trading_api_domain`` is left at this default it follows
# ``api_url``, so changing only ``api_url`` (another environment) moves trading with it.
DEFAULT_TRADING_API_DOMAIN = DEFAULT_API_URL

# ---------------------------------------------------------------------------
# API Endpoints — Authentication
# ---------------------------------------------------------------------------
EP_ACCESS_TOKEN = "/api/v3/auth/token"
EP_REFRESH_TOKEN = "/api/v3/auth/refresh"
EP_REQUEST_OTP = "/api/v3/auth/requestOtp"

# Returned while a Smart OTP push-approval hasn't been confirmed on the
# device yet: HTTP 202 with body {"code": 401114, "msg": "Push-approval is
# pending"}. Confirmed against SSI FastConnect.
SMART_OTP_PENDING_STATUS = 202
SMART_OTP_PENDING_CODE = 401114

# Treat a token as expired this many seconds early so it never expires mid-request.
TOKEN_EXPIRY_SKEW_SECONDS = 30

# Smart OTP codes after which polling can never succeed (rejected / expired / unknown
# transaction): stop immediately instead of polling on.
SMART_OTP_TERMINAL_CODES = frozenset({401113, 401115, 401116})

# Refresh failures meaning the refresh token is unusable (wrong/broken 401101/401106-8, client
# or apiKey gone 401102/401104, revoked/reused/expired 401103). The server revokes the whole
# apiKey session on a reused refresh token, so retrying cannot help.
REFRESH_REAUTH_CODES = frozenset({401101, 401102, 401103, 401104, 401106, 401107, 401108})

# HTTP 409 on an order/FCO/batch request: the client/batch request id was already used.
HTTP_STATUS_CONFLICT = 409

# Smart OTP approval polling — max number of authenticate() attempts and the
# delay between them.
SMART_OTP_POLL_MAX_RETRIES = 5
SMART_OTP_POLL_INTERVAL = 5  # seconds

# Config defaults: poll every 5s for up to 60s in total.
DEFAULT_OTP_POLL_INTERVAL = 5.0
DEFAULT_OTP_POLL_MAX_WAIT = 60.0

# ---------------------------------------------------------------------------
# API Endpoints — Market Data
# ---------------------------------------------------------------------------
EP_DATA_OHLC = "/api/v3/data/ohlc"
EP_DATA_OHLC_DOWNLOAD = "/api/v3/data/ohlc/download"
EP_DATA_MASTER_DATA = "/api/v3/data/masterdata"
EP_DATA_INDEX_LIST = "/api/v3/data/indexList"
EP_DATA_INDEX_SUMMARY = "/api/v3/data/indexSummary"
EP_DATA_SECURITIES_BY_BOARD = "/api/v3/data/securitiesByBoard"
EP_DATA_SECURITIES_SUMMARY = "/api/v3/data/securitiesSummary"

# ---------------------------------------------------------------------------
# API Endpoints — Trading
# ---------------------------------------------------------------------------
EP_TRADING_ORDER = "/api/v3/trading/order"
EP_TRADING_ORDER_BATCH = "/api/v3/trading/order/batch"
EP_TRADING_MAX_BUY_SELL = "/api/v3/trading/maxBuySell"
EP_TRADING_FCO_ORDER = "/api/v3/trading/fco/order"
EP_TRADING_FCO_LIST = "/api/v3/trading/fco/list"
EP_TRADING_FCO_ORDER_BOOK = "/api/v3/trading/fco/orderbook"
EP_TRADING_FCO_STATUS_HISTORY = "/api/v3/trading/fco/statusHistory"

# ---------------------------------------------------------------------------
# API Endpoints — Portfolio & Account
# ---------------------------------------------------------------------------
EP_ACCOUNT_INFO = "/api/v3/account/info"
EP_ACCOUNT_BALANCE = "/api/v3/trading/accountBalance"
EP_ACCOUNT_PPMMR = "/api/v3/trading/ppmmrAccount"
EP_POSITIONS = "/api/v3/trading/position"
EP_ORDER_HISTORY = "/api/v3/trading/orderBook"

# ---------------------------------------------------------------------------
# WebSocket Constants
# ---------------------------------------------------------------------------
WS_THREAD_NAME = "SSIWebSocketThread"
WS_KEY_CHANNEL = "channel"

# Synthetic dispatch routes for frames that carry no ``channel``. Real channels (DATA,
# TRADING, HEARTBEAT) keep their own names as routes.
WS_ROUTE_ACK = "@ack"  # {"method", "channel", "status", "message"} replies to a request
WS_ROUTE_ERROR = "@error"  # {"code", "msg"} the server sends before closing a socket
WS_ROUTE_LIST_SUBSCRIPTION = "@list_subscription"  # {"trading": "a;b", "data": "x;y"}
WS_ROUTE_ID = "@id"  # frames answering a request that carried an ``id`` (trading socket)

# DATA-channel topic carrying market session flags (ATO, LO, ATC, ...) for all boards.
TOPIC_MARKET_FLAG = "market.flag"

# Order request ids: the server rejects anything longer than 20 characters.
MAX_CLIENT_REQUEST_ID_LENGTH = 20

# Server MaxBatchOrderCount (its default, configurable on the server): a batch holds at most this
# many orders. ``Config.max_batch_orders`` overrides it if SSI changes the server setting.
MAX_BATCH_ORDERS = 20

# ---------------------------------------------------------------------------
# WebSocket reconnect policy
# ---------------------------------------------------------------------------
WS_RECONNECT_MAX_DELAY = 60.0  # seconds; upper bound of the exponential backoff
WS_RATE_LIMIT_BACKOFF = 30.0  # seconds; minimum wait after the server answers 429 on connect
WS_TOKEN_REFRESH_LEAD = 60.0  # seconds; reconnect with a fresh token this long before expiry
WS_SERVER_MAX_CONNECTIONS = 10  # the server allows this many sockets per client

# The stream server's MaxMessageSize is 4096 bytes. Keep every frame we send under it (with a
# margin): a long topic list is split over several subscribe/unsubscribe frames.
WS_MAX_FRAME_BYTES = 4000
