"""Data models for SSI SDK."""

from ssi_sdk.models.account import Account
from ssi_sdk.models.auth import (
    OTPRequest,
    OTPResponse,
    RefreshTokenRequest,
    Token,
    TokenRequest,
)
from ssi_sdk.models.fco import (
    BullBearParams,
    FCOCancelRequest,
    FCOCancelResponse,
    FCOInfo,
    FCOListRequest,
    FCOListResponse,
    FCOOrder,
    FCOOrderBookRequest,
    FCOOrderBookResponse,
    FCOParams,
    FCOPlaceResponse,
    FCOStatusHistoryItem,
    FCOStatusHistoryRequest,
    GTDParams,
    OCOParams,
    StopParams,
    TrailingStopParams,
)
from ssi_sdk.models.market_data import (
    DownloadData,
    DownloadDataRequest,
    MarketIndexes,
    MarketIndexesRequest,
    MarketIndexSummary,
    MarketIndexSummaryRequest,
    MasterData,
    MasterDataRequest,
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
    DataMessage,
    FCOOrderUpdateMessage,
    ForeignRoomMessage,
    HeartbeatMessage,
    IndexSummaryMessage,
    IndexTickMessage,
    IntervalMessage,
    MarketDataMessage,
    MarketFlagMessage,
    MarketStatusMessage,
    OddLotMessage,
    OrderMatchMessage,
    OrderStatusMessage,
    PortfolioMessage,
    PutMessage,
    QuoteMessage,
    RequestMessage,
    TradeMessage,
    TradingMessage,
)
from ssi_sdk.models.trading import (
    BatchCancelOrderItem,
    BatchOrderRequest,
    BatchOrderResponse,
    BatchOrderResult,
    BatchPlaceOrderItem,
    CancelOrderRequest,
    CancelOrderResponse,
    MaxBuySellRequest,
    MaxBuySellResponse,
    ModifyOrderRequest,
    ModifyOrderResponse,
    NumberLike,
    PlaceOrderRequest,
    PlaceOrderResponse,
    PriceLike,
)

__all__ = [
    # -------------------------------------------------------------------------
    # Authentication models
    # -------------------------------------------------------------------------
    "Token",
    "TokenRequest",
    "OTPRequest",
    "OTPResponse",
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
    "MasterDataRequest",
    "MasterData",
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
    "BatchCancelOrderItem",
    "BatchPlaceOrderItem",
    "NumberLike",
    "PriceLike",
    "BatchOrderRequest",
    "BatchOrderResponse",
    "BatchOrderResult",
    "CancelOrderRequest",
    "CancelOrderResponse",
    "MaxBuySellRequest",
    "MaxBuySellResponse",
    # -------------------------------------------------------------------------
    # FCO models
    # -------------------------------------------------------------------------
    "FCOListRequest",
    "FCOListResponse",
    "FCOInfo",
    "FCOParams",
    "FCOOrderBookRequest",
    "FCOOrder",
    "FCOOrderBookResponse",
    "FCOPlaceResponse",
    "FCOCancelRequest",
    "FCOCancelResponse",
    "FCOStatusHistoryItem",
    "FCOStatusHistoryRequest",
    "GTDParams",
    "StopParams",
    "TrailingStopParams",
    "OCOParams",
    "BullBearParams",
    # -------------------------------------------------------------------------
    # Streaming models
    # -------------------------------------------------------------------------
    "RequestMessage",
    "HeartbeatMessage",
    "TradeMessage",
    "QuoteMessage",
    "IntervalMessage",
    "MarketStatusMessage",
    "MarketDataMessage",
    "IndexSummaryMessage",
    "IndexTickMessage",
    "MarketFlagMessage",
    "DataMessage",
    "TradingMessage",
    "ForeignRoomMessage",
    "PutMessage",
    "OddLotMessage",
    "OrderStatusMessage",
    "OrderMatchMessage",
    "PortfolioMessage",
    "FCOOrderUpdateMessage",
    # -------------------------------------------------------------------------
    # Order book models (not implemented yet)
    # -------------------------------------------------------------------------
    "OrderBookRequest",
    "OrderBook",
    "Order",
]
