"""Data models for SSI SDK."""

from ssi_sdk.models.account import Account
from ssi_sdk.models.auth import OTPRequest, RefreshTokenRequest, Token, TokenRequest
from ssi_sdk.models.market_data import (
    DownloadData,
    DownloadDataRequest,
    MarketIndexes,
    MarketIndexesRequest,
    MarketIndexSummary,
    MarketIndexSummaryRequest,
    OHLCData,
    OHLCRequest,
    SecuritiesInfo,
    SecuritiesInfoRequest,
    SecuritiesSummary,
    SecuritiesSummaryRequest,
)
from ssi_sdk.models.portfolio import (
    PPMMR,
    AccountBalance,
    AccountBalanceRequest,
    AllDerivativePosition,
    DerivativeAccountBalance,
    DerivativePosition,
    DerivativePPMMR,
    EquityAccountBalance,
    EquityPosition,
    EquityPPMMR,
    Order,
    OrderBook,
    OrderBookRequest,
    Position,
    PositionsRequest,
    PPMMRRequest,
)
from ssi_sdk.models.streaming import (
    ForeignRoomMessage,
    HeartbeatMessage,
    IntervalMessage,
    MarketStatusMessage,
    OddLotMessage,
    OrderStatusMessage,
    PortfolioMessage,
    PutMessage,
    QuoteMessage,
    RequestMessage,
    TradeMessage,
)
from ssi_sdk.models.trading import (
    CancelOrderRequest,
    CancelOrderResponse,
    MaxBuySellRequest,
    MaxBuySellResponse,
    ModifyOrderRequest,
    ModifyOrderResponse,
    PlaceOrderRequest,
    PlaceOrderResponse,
)

__all__ = [
    # -------------------------------------------------------------------------
    # Authentication models
    # -------------------------------------------------------------------------
    "Token",
    "TokenRequest",
    "OTPRequest",
    "RefreshTokenRequest",
    # -------------------------------------------------------------------------
    # Account models
    # -------------------------------------------------------------------------
    "Account",
    # -------------------------------------------------------------------------
    # Market data models
    # -------------------------------------------------------------------------
    "DownloadData",
    "DownloadDataRequest",
    "OHLCRequest",
    "OHLCData",
    "MarketIndexes",
    "MarketIndexesRequest",
    "MarketIndexSummary",
    "MarketIndexSummaryRequest",
    "SecuritiesInfo",
    "SecuritiesInfoRequest",
    "SecuritiesSummary",
    "SecuritiesSummaryRequest",
    # -------------------------------------------------------------------------
    # Portfolio models
    # -------------------------------------------------------------------------
    "AccountBalanceRequest",
    "AccountBalance",
    "EquityAccountBalance",
    "DerivativeAccountBalance",
    "PositionsRequest",
    "Position",
    "DerivativePosition",
    "AllDerivativePosition",
    "EquityPosition",
    # -------------------------------------------------------------------------
    # PPMMR models
    # -------------------------------------------------------------------------
    "PPMMRRequest",
    "PPMMR",
    "EquityPPMMR",
    "DerivativePPMMR",
    # -------------------------------------------------------------------------
    # Trading models
    # -------------------------------------------------------------------------
    "PlaceOrderRequest",
    "PlaceOrderResponse",
    "ModifyOrderRequest",
    "ModifyOrderResponse",
    "CancelOrderRequest",
    "CancelOrderResponse",
    "MaxBuySellRequest",
    "MaxBuySellResponse",
    # -------------------------------------------------------------------------
    # Streaming models
    # -------------------------------------------------------------------------
    "RequestMessage",
    "HeartbeatMessage",
    "TradeMessage",
    "QuoteMessage",
    "IntervalMessage",
    "MarketStatusMessage",
    "ForeignRoomMessage",
    "PutMessage",
    "OddLotMessage",
    "OrderStatusMessage",
    "PortfolioMessage",
    # -------------------------------------------------------------------------
    # Order book models (not implemented yet)
    # -------------------------------------------------------------------------
    "OrderBookRequest",
    "OrderBook",
    "Order",
]
