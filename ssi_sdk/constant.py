"""Protocol constants for SSI SDK (fixed by server/spec, not user-configurable)."""

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
DEFAULT_SIZE = 1000
DEFAULT_PAGE = 1
# ---------------------------------------------------------------------------
# Rate Limiting & Retries
# ---------------------------------------------------------------------------
DEFAULT_TIMEOUT = 60  # seconds
DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_DELAY = 2  # seconds (base for exponential backoff)
DEFAULT_RATE_LIMIT_PER_SECOND = 10
WS_THREAD_JOIN_TIMEOUT = 5  # seconds

# ---------------------------------------------------------------------------
# HTTP Headers & Auth
# ---------------------------------------------------------------------------
HEADER_CONTENT_TYPE = "Content-Type"
HEADER_ACCEPT = "Accept"
HEADER_AUTHORIZATION = "Authorization"
HEADER_RETRY_AFTER = "Retry-After"
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

# ---------------------------------------------------------------------------
# API Endpoints — Authentication
# ---------------------------------------------------------------------------
EP_ACCESS_TOKEN = "/api/v3/auth/token"
EP_REFRESH_TOKEN = "/api/v3/auth/refresh"
EP_REQUEST_OTP = "/api/v3/auth/requestOtp"

# Returned while a Smart OTP push-approval hasn't been confirmed on the
# device yet: HTTP 409 with body {"code": 401114, "msg": "Push-approval is
# pending"}. Confirmed against SSI FastConnect UAT.
SMART_OTP_PENDING_STATUS = 409
SMART_OTP_PENDING_CODE = 401114

# Smart OTP approval polling — max number of authenticate() attempts and the
# delay between them.
SMART_OTP_POLL_MAX_RETRIES = 5
SMART_OTP_POLL_INTERVAL = 5  # seconds

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
EP_TRADING_MAX_BUY_SELL = "/api/v3/trading/maxBuySell"
EP_TRADING_FCO_ORDER = "/api/v3/trading/fco/order"
EP_TRADING_FCO_LIST = "/api/v3/trading/fco/list"
EP_TRADING_FCO_ORDER_BOOK = "/api/v3/trading/fco/orderbook"

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
