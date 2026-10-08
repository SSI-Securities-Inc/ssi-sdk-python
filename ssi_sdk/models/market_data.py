"""Market data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ssi_sdk.constant import DEFAULT_PAGE, DEFAULT_SIZE
from ssi_sdk.enums import Board, Timeframe
from ssi_sdk.utils import to_float, to_int, to_number, to_opt_float, to_opt_int


def _to_board(raw: Any) -> Board | str | None:
    """Parse a board leniently: known value -> ``Board``, unknown -> raw string, empty -> None."""
    if raw is None or raw == "":
        return None
    return Board.from_value(raw) or str(raw)


def _blank_to_none(value: Any) -> Any:
    """Map the server's empty-string "no value" marker to None."""
    return None if value is None or (isinstance(value, str) and not value.strip()) else value


@dataclass
class DownloadDataRequest:
    """Bulk download data request.

    Deprecated: the server has no ``data/file`` endpoint yet and its final response shape
    (``dataLink`` vs ``files[]``) is undecided, so nothing uses this model. Do not build on it.
    """

    symbol: str = ""
    timeframe: Timeframe = Timeframe.DAY_1

    def to_dict(self) -> dict:
        """Convert the request to an API payload with camelCase keys.

        Returns:
            Dictionary with ``symbol`` and ``timeFrame`` keys for the API request.
        """
        return {
            "symbol": self.symbol,
            "timeFrame": self.timeframe.value,
        }


@dataclass
class DownloadData:
    """Bulk download data result.

    Deprecated: see :class:`DownloadDataRequest`. The ``{data, totalCount}`` shape does not
    match what the server is planned to return.
    """

    data: list[dict[str, Any]] = field(default_factory=list)
    total_count: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> DownloadData:
        """Build a DownloadData instance from an API response dictionary.

        Args:
            data: API response dict with a ``data`` list and optional ``totalCount``.
        Returns:
            A DownloadData populated with the items and their total count.
        """
        items = data.get("data", [])
        return cls(
            data=items,
            total_count=data.get("totalCount", len(items)),
        )


@dataclass
class OHLCRequest:
    """OHLC data request.

    Attributes:
        symbol: Ticker symbol.
        from_date: Start of the range/window.
        to_date: End of the range/window.
    """

    symbol: str
    from_date: str
    to_date: str
    timeframe: Timeframe
    page: int = DEFAULT_PAGE
    size: int = DEFAULT_SIZE

    def to_dict(self) -> dict:
        """Convert the request to an API payload with camelCase keys.

        Returns:
            Dictionary with symbol, date range, timeframe, and pagination keys.
        """
        return {
            "symbol": self.symbol,
            "from": self.from_date,
            "to": self.to_date,
            "timeFrame": self.timeframe.value,
            "pageIndex": self.page,
            "pageSize": self.size,
        }


@dataclass
class OHLCData:
    """OHLC data result.

    Attributes:
        symbol: Ticker symbol.
        trading_date: Trading date as the server formats it (varies by endpoint; see
            ``parse_date``).
        open_price: Opening price.
        high_price: Highest price.
        low_price: Lowest price.
        close_price: Closing/last price.
        volume: Traded volume.
        value: Traded value.
    """

    symbol: str
    trading_date: str
    open_price: float | int
    high_price: float | int
    low_price: float | int
    close_price: float | int
    volume: int
    value: float | int

    @classmethod
    def from_list(cls, data: list[dict]) -> list[OHLCData]:
        """Build a list of OHLCData candles from a list of API dictionaries.

        Args:
            data: List of dicts with camelCase OHLC fields (open, high, low, close, volume).
        Returns:
            List of OHLCData instances, one per input candle.
        """
        return [
            cls(
                symbol=item.get("symbol", ""),
                trading_date=item.get("tradingDate", ""),
                open_price=to_number(item.get("open", 0.0)),
                high_price=to_number(item.get("high", 0.0)),
                low_price=to_number(item.get("low", 0.0)),
                close_price=to_number(item.get("close", 0.0)),
                volume=to_int(item.get("volume", 0)),
                value=to_number(item.get("value", 0.0)),
            )
            for item in data
        ]


@dataclass
class MarketIndexesRequest:
    """Market index information request."""

    board: Board | None = None

    def to_dict(self) -> dict:
        """Convert the request to an API payload with camelCase keys.

        Returns:
            Dictionary with a ``board`` key, or an empty dict when no board is set.
        """
        if self.board is None:
            return {}
        return {
            "board": self.board.value,
        }


@dataclass
class MarketIndexes:
    """Market indices information.

    Attributes:
        index: Index code, e.g. ``"VN30"``.
        index_name: Index name (the server repeats the code).
        board: Exchange board: a ``Board``, or the raw string for an unknown board.
        board_raw: The board exactly as the server sent it.
    """

    index: str
    index_name: str
    board: Board | str | None = None
    board_raw: str | None = None

    @classmethod
    def from_list(cls, data: list[dict]) -> list[MarketIndexes]:
        """Build a list of MarketIndexes from a list of API dictionaries.

        Args:
            data: List of dicts with ``index``, ``indexName``, and optional ``board`` keys.
        Returns:
            List of MarketIndexes instances, one per input dictionary. ``board`` is the
            matching ``Board``, or the raw string for a board this SDK does not know.
        """
        return [
            cls(
                index=item.get("index", ""),
                index_name=item.get("indexName", ""),
                board=_to_board(item.get("board")),
                board_raw=_blank_to_none(item.get("board")),
            )
            for item in data
        ]


@dataclass
class MarketIndexSummaryRequest:
    """Market index summary request.

    Attributes:
        index: Index code, e.g. ``"VN30"``.
        board: Exchange board: a ``Board``, or the raw string for an unknown board.
        trading_date: Trading date as the server formats it (varies by endpoint; see
            ``parse_date``).
    """

    index: str | None = None
    board: Board | None = None
    trading_date: str | None = None

    def to_dict(self) -> dict:
        """Convert the request to an API payload with camelCase keys.

        Returns:
            Dictionary containing only the set fields (index, board, tradingDate).
        """
        data = {}
        if self.index is not None:
            data["index"] = self.index
        if self.board is not None:
            data["board"] = self.board.value
        if self.trading_date is not None:
            data["tradingDate"] = self.trading_date
        return data


@dataclass
class MarketIndexSummary:
    """Market index summary information.

    Attributes:
        trading_date: Trading date as the server formats it (varies by endpoint; see
            ``parse_date``).
        total_buy_foreign: Foreign buy volume.
        total_sell_foreign: Foreign sell volume.
    """

    trading_date: str
    total_trade: int
    total_trade_value: float
    total_match: int
    total_match_value: float
    total_deal: int
    total_deal_value: float
    index_change: float
    index_change_percent: float
    index_value: float
    total_advance_stock: int
    total_decline_stock: int
    total_steady_stock: int
    total_ceiling_stock: int
    total_floor_stock: int
    total_prop_buy: int
    total_prop_buy_value: float
    total_prop_sell: int
    total_prop_sell_value: float
    total_buy_foreign: float | None = None
    total_buy_foreign_value: float | None = None
    total_sell_foreign: float | None = None
    total_sell_foreign_value: float | None = None
    net_purchases_foreign_volume: float | None = None
    net_purchases_foreign_value: float | None = None

    @classmethod
    def from_list(cls, data: list[dict]) -> list[MarketIndexSummary]:
        """Build a list of MarketIndexSummary from a list of API dictionaries.

        Args:
            data: List of dicts with camelCase index summary fields (trades, values, counts).
        Returns:
            List of MarketIndexSummary instances, one per input dictionary.
        """
        return [
            cls(
                trading_date=item.get("tradingDate", ""),
                total_trade=to_int(item.get("totalTrade", 0)),
                total_trade_value=to_float(item.get("totalTradeValue", 0.0)),
                total_match=to_int(item.get("totalMatch", 0)),
                total_match_value=to_float(item.get("totalMatchValue", 0.0)),
                total_deal=to_int(item.get("totalDeal", 0)),
                total_deal_value=to_float(item.get("totalDealValue", 0.0)),
                index_change=to_float(item.get("indexChange", 0.0)),
                index_change_percent=to_float(item.get("indexChangePercentage", 0.0)),
                index_value=to_float(item.get("indexValue", 0.0)),
                total_advance_stock=to_int(item.get("totalAdvanceStock", 0)),
                total_decline_stock=to_int(item.get("totalDeclineStock", 0)),
                total_steady_stock=to_int(item.get("totalNoChangeStock", 0)),
                total_ceiling_stock=to_int(item.get("totalCeilingStock", 0)),
                total_floor_stock=to_int(item.get("totalFloorStock", 0)),
                total_prop_buy=to_int(item.get("totalPropBuy", 0)),
                total_prop_buy_value=to_float(item.get("totalPropBuyValue", 0.0)),
                total_prop_sell=to_int(item.get("totalPropSell", 0)),
                total_prop_sell_value=to_float(item.get("totalPropSellValue", 0.0)),
                total_buy_foreign=to_opt_float(item.get("totalBuyForeign")),
                total_buy_foreign_value=to_opt_float(item.get("totalBuyForeignValue")),
                total_sell_foreign=to_opt_float(item.get("totalSellForeign")),
                total_sell_foreign_value=to_opt_float(item.get("totalSellForeignValue")),
                net_purchases_foreign_volume=to_opt_float(
                    item.get("netPurchasesForeignVolume")
                ),
                net_purchases_foreign_value=to_opt_float(item.get("netPurchasesForeignValue")),
            )
            for item in data
        ]


@dataclass
class SecuritiesInfoRequest:
    """Securities information request.

    Attributes:
        symbol: Ticker symbol.
        board: Exchange board: a ``Board``, or the raw string for an unknown board.
        index: Index code, e.g. ``"VN30"``.
    """

    symbol: str | None = None
    board: Board | None = None
    index: str | None = None

    def to_dict(self) -> dict:
        """Convert the request to an API payload with camelCase keys.

        Returns:
            Dictionary containing only the set fields (symbol, board, index).
        """
        data = {}
        if self.symbol is not None:
            data["symbol"] = self.symbol
        if self.board is not None:
            data["board"] = self.board.value
        if self.index is not None:
            data["index"] = self.index
        return data


@dataclass
class SecuritiesInfo:
    """Securities information.

    Attributes:
        symbol: Ticker symbol.
        board: Exchange board: a ``Board``, or the raw string for an unknown board.
        index: Index code, e.g. ``"VN30"``.
        lot_size: Trading lot size.
        listed_shares: Number of listed shares.
        stock_type: Security type code.
    """

    symbol: str
    board: Board | str | None = None
    index: str | None = None
    symbol_name_vi: str | None = None
    symbol_name_en: str | None = None
    lot_size: int | None = None
    maturity_date: str | None = None
    first_trading_date: str | None = None
    last_trading_date: str | None = None
    cw_underlying_symbol: str | None = None
    cw_exercise_price: float | None = None
    cw_execution_ratio: float | None = None
    listed_shares: int | None = None
    icb_code: str | None = None
    icb_name: str | None = None
    i_index: float | None = None
    i_nav: float | None = None
    open_interest: float | None = None
    settlement_price: float | None = None
    stock_type: str | None = None

    @classmethod
    def from_list(cls, data: list[dict]) -> list[SecuritiesInfo]:
        """Build a list of SecuritiesInfo from a list of API dictionaries.

        Args:
            data: List of dicts with camelCase securities fields (symbol, names, CW info, etc.).
        Returns:
            List of SecuritiesInfo instances, one per input dictionary. A numeric field the
            server omits or leaves empty is ``None`` (not 0), and an empty date is ``None``.
        """
        return [
            cls(
                symbol=item.get("symbol", ""),
                board=_to_board(item.get("board")),
                index=item.get("index"),
                symbol_name_vi=item.get("symbolNameVi"),
                symbol_name_en=item.get("symbolNameEn"),
                lot_size=to_opt_int(item.get("lotSize")),
                maturity_date=_blank_to_none(item.get("maturityDate")),
                first_trading_date=_blank_to_none(item.get("firstTradingDate")),
                last_trading_date=_blank_to_none(item.get("lastTradingDate")),
                cw_underlying_symbol=_blank_to_none(item.get("cwUnderlyingSymbol")),
                cw_exercise_price=to_opt_float(item.get("cwExercisePrice")),
                cw_execution_ratio=to_opt_float(item.get("cwExecutionRatio")),
                listed_shares=to_opt_int(item.get("listedShare")),
                icb_code=_blank_to_none(item.get("icbCode")),
                icb_name=_blank_to_none(item.get("icbName")),
                i_index=to_opt_float(item.get("iIndex")),
                i_nav=to_opt_float(item.get("iNav")),
                open_interest=to_opt_float(item.get("openInterest")),
                settlement_price=to_opt_float(item.get("settlementPrice")),
                stock_type=_blank_to_none(item.get("stockType")),
            )
            for item in data
        ]


@dataclass
class MasterDataRequest:
    """Master data (reference price) request.

    Attributes:
        from_date: Start of the range/window.
        to_date: End of the range/window.
    """

    from_date: str | None = None
    to_date: str | None = None
    page: int = DEFAULT_PAGE
    size: int = DEFAULT_SIZE

    def to_dict(self) -> dict:
        """Convert the request to an API payload with the endpoint's query keys.

        Returns:
            Dictionary with pagination keys, plus the lower-case ``from``/``to`` date range
            only for the bounds that were set.
        """
        data: dict[str, Any] = {}
        if self.from_date is not None:
            data["from"] = self.from_date
        if self.to_date is not None:
            data["to"] = self.to_date
        data["pageIndex"] = self.page
        data["pageSize"] = self.size
        return data


@dataclass
class MasterData:
    """Reference price (ceiling/floor/reference) for a symbol on a trading date.

    Attributes:
        board: Exchange board: a ``Board``, or the raw string for an unknown board.
        symbol: Ticker symbol.
        trading_date: Trading date as the server formats it (varies by endpoint; see
            ``parse_date``).
        ceiling: Ceiling price of the day.
        floor: Floor price of the day.
        ref_price: Reference price of the day.
    """

    board: Board | str | None
    symbol: str
    trading_date: str
    ceiling: float
    floor: float
    ref_price: float

    @classmethod
    def from_list(cls, data: list[dict]) -> list[MasterData]:
        """Build a list of MasterData from a list of API dictionaries.

        Args:
            data: List of dicts with camelCase master data fields (exchange, symbol, prices).
        Returns:
            List of MasterData instances, one per input dictionary.
        """
        return [
            cls(
                board=_to_board(item.get("board")),
                symbol=item.get("symbol", ""),
                trading_date=item.get("tradingDate", ""),
                ceiling=to_number(item.get("ceiling", 0.0)),
                floor=to_number(item.get("floor", 0.0)),
                ref_price=to_number(item.get("refPrice", 0.0)),
            )
            for item in data
        ]


@dataclass
class SecuritiesSummaryRequest:
    """Securities summary request.

    Attributes:
        from_date: Start of the range/window.
        to_date: End of the range/window.
        symbol: Ticker symbol.
        index: Index code, e.g. ``"VN30"``.
    """

    from_date: str
    to_date: str
    symbol: str | None = None
    index: str | None = None
    page: int = DEFAULT_PAGE
    size: int = DEFAULT_SIZE

    def to_dict(self) -> dict:
        """Convert the request to an API payload with camelCase keys.

        Returns:
            Dictionary with date range and pagination keys, plus symbol/index when set.
        """
        data = {
            "from": self.from_date,
            "to": self.to_date,
            "pageIndex": self.page,
            "pageSize": self.size,
        }
        if self.symbol is not None:
            data["symbol"] = self.symbol
        if self.index is not None:
            data["index"] = self.index
        return data


@dataclass
class SecuritiesSummary:
    """Securities summary information.

    Attributes:
        symbol: Ticker symbol.
        trading_date: Trading date as the server formats it (varies by endpoint; see
            ``parse_date``).
        open_price: Opening price.
        high_price: Highest price.
        low_price: Lowest price.
        close_price: Closing/last price.
        ceiling: Not sent by ``securitiesSummary`` (stays 0); use ``get_master_data()``.
        floor: Not sent by ``securitiesSummary`` (stays 0); use ``get_master_data()``.
        ref_price: Not sent by ``securitiesSummary`` (stays 0); use ``get_master_data()``.
    """

    symbol: str
    trading_date: str
    price_change: float
    price_change_percent: float
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    average_price: float
    total_match: int
    total_match_value: float
    total_buy: int
    total_trade_buy: float
    total_sell: int
    total_trade_sell: float
    total_foreign_buy: int = 0
    total_foreign_buy_value: float = 0.0
    total_foreign_sell: int = 0
    total_foreign_sell_value: float = 0.0
    remain_foreign_room: int = 0
    total_foreign_room: int = 0
    total_deal: int = 0
    total_deal_value: float = 0.0
    open_interest: float = 0.0
    settlement_price: float = 0.0
    ceiling: float | None = None
    floor: float | None = None
    ref_price: float | None = None

    @classmethod
    def from_list(cls, data: list[dict]) -> list[SecuritiesSummary]:
        """Build a list of SecuritiesSummary from a list of API dictionaries.

        Args:
            data: List of dicts with camelCase summary fields (prices, changes, match totals).
        Returns:
            List of SecuritiesSummary instances, one per input dictionary.
        """
        return [
            cls(
                symbol=item.get("symbol", ""),
                trading_date=item.get("tradingDate", ""),
                price_change=to_number(item.get("priceChange", 0.0)),
                price_change_percent=to_number(item.get("priceChangePercentage", 0.0)),
                open_price=to_number(item.get("open", 0.0)),
                high_price=to_number(item.get("high", 0.0)),
                low_price=to_number(item.get("low", 0.0)),
                close_price=to_number(item.get("close", 0.0)),
                average_price=to_number(item.get("average", 0.0)),
                total_match=to_int(item.get("totalMatch", 0)),
                total_match_value=to_number(item.get("totalMatchValue", 0.0)),
                total_buy=to_int(item.get("totalBuy", 0)),
                total_trade_buy=to_number(item.get("totalTradeBuy", 0.0)),
                total_sell=to_int(item.get("totalSell", 0)),
                total_trade_sell=to_number(item.get("totalTradeSell", 0.0)),
                total_foreign_buy=to_int(item.get("totalForeignBuy", 0)),
                total_foreign_buy_value=to_number(item.get("totalForeignBuyValue", 0.0)),
                total_foreign_sell=to_int(item.get("totalForeignSell", 0)),
                total_foreign_sell_value=to_number(item.get("totalForeignSellValue", 0.0)),
                remain_foreign_room=to_int(item.get("remainForeignRoom", 0)),
                total_foreign_room=to_int(item.get("totalForeignRoom", 0)),
                total_deal=to_int(item.get("totalDeal", 0)),
                total_deal_value=to_number(item.get("totalDealValue", 0.0)),
                open_interest=to_number(item.get("openInterest", 0.0)),
                settlement_price=to_number(item.get("settlementPrice", 0.0)),
                ceiling=to_opt_float(item.get("ceiling")),
                floor=to_opt_float(item.get("floor")),
                ref_price=to_opt_float(item.get("refPrice")),
            )
            for item in data
        ]
