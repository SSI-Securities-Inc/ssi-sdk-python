"""Market data service (OHLC, Index, Security) — async and sync."""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator, Iterator
from datetime import datetime

from ssi_sdk.constant import (
    DEFAULT_PAGE,
    DEFAULT_SIZE,
    EP_DATA_INDEX_LIST,
    EP_DATA_INDEX_SUMMARY,
    EP_DATA_MASTER_DATA,
    EP_DATA_OHLC,
    EP_DATA_SECURITIES_BY_BOARD,
    EP_DATA_SECURITIES_SUMMARY,
)
from ssi_sdk.enums import ALLOWED_TIMEFRAMES, Board, Timeframe
from ssi_sdk.exceptions import APIError, ValidationError
from ssi_sdk.models import (
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
from ssi_sdk.transport.rest_client import AsyncRestClient, RestClient
from ssi_sdk.utils import (
    from_beginning_of_day,
    from_end_of_day,
    is_no_content,
    parse_date_arg,
    pick,
    require_date_range,
    require_exactly_one,
    require_non_empty,
    require_positive,
    require_symbol,
    to_int,
    today_date_str,
)

logger = logging.getLogger("ssi_sdk.services.market_data")


# ── shared logic (no async) ─────────────────────────────────

# Boards the REST data endpoints serve; DERIVATIVES exists only on the stream/master data.
_REST_BOARDS = (Board.HOSE, Board.HNX, Board.UPCOM)

_WEEK_MONTH_REJECTED = (
    "The server does not support the {name} timeframe (error 400210); "
    "request 1d bars and aggregate them client-side instead"
)


def _rows(data, what: str) -> list:
    """Return the rows of a bare-array endpoint.

    The server answers an empty result with HTTP 200 and ``{"code": 204}`` (an object,
    not ``[]``), so that marker maps to an empty list rather than a parse error.
    """
    if isinstance(data, list):
        return data
    if is_no_content(data):
        return []
    raise APIError(f"Unexpected response format while reading {what}", response_body=data)


def _data_rows(data, what: str) -> list:
    """Return the ``data`` rows of an enveloped endpoint (``{"data": [...], ...}``)."""
    if is_no_content(data):
        return []
    if isinstance(data, dict):
        rows = data.get("data")
        if rows is None:
            return []
        if isinstance(rows, list):
            return rows
    raise APIError(f"Unexpected response format while reading {what}", response_body=data)


def _pages_count(data) -> int:
    """Total pages of a paginated response (``pagesCount``, falling back to ``pageCount``)."""
    return to_int(pick(data, "pagesCount", "pageCount"), 1) if isinstance(data, dict) else 1


def _rest_board(board: Board | str | None) -> Board | None:
    """Validate a board for a REST data endpoint (HOSE/HNX/UPCOM only)."""
    if board is None:
        return None
    resolved = Board.from_value(board)
    if resolved not in _REST_BOARDS:
        allowed = ", ".join(b.value for b in _REST_BOARDS)
        raise ValidationError(f"board must be one of {allowed}, got '{board}'")
    return resolved


def _check_timeframe(timeframe: Timeframe) -> Timeframe:
    """Reject timeframes the OHLC endpoint does not accept."""
    if timeframe not in ALLOWED_TIMEFRAMES:
        allowed = ", ".join(sorted(t.value for t in ALLOWED_TIMEFRAMES))
        raise ValidationError(f"timeframe {timeframe.value} is not supported; use one of {allowed}")
    return timeframe


def _check_paging(page: int, size: int) -> None:
    """The server validates neither ``pageIndex`` nor ``pageSize``; 0 or negative values give
    undefined results, so refuse them here."""
    require_positive(page, "page")
    require_positive(size, "size")


def _clamp_future_end(timeframe: Timeframe, from_date: str, to_date: str) -> str:
    """Minute/hour bars: a ``to`` later than today makes the server answer nothing at all (it
    only handles ``to`` before or equal to today), so cut it to the end of today. Daily bars
    are not affected, and a range that starts in the future is left alone (it is empty anyway).
    """
    if timeframe is Timeframe.DAY_1:
        return to_date
    today = datetime.now().date()
    if parse_date_arg(to_date, "to", allow_time=True).date() > today >= parse_date_arg(
        from_date, "from", allow_time=True
    ).date():
        return from_end_of_day()
    return to_date


_DATE_ONLY = re.compile(r"\d{4}[/-]\d{2}[/-]\d{2}")


def _with_time(value: str, time_text: str) -> str:
    """``YYYY/MM/DD`` -> ``YYYY/MM/DD <time_text>``: the OHLC endpoint answers 400213 ("Invalid
    Date/Timestamp Format") to a bare date, so a date alone is completed with a time."""
    text = value.strip()
    if _DATE_ONLY.fullmatch(text):
        return f"{text.replace('-', '/')} {time_text}"
    return value


def _build_ohlc_params(
    symbol: str,
    timeframe: Timeframe,
    from_date: str | None,
    to_date: str | None,
    page: int,
    size: int,
) -> dict:
    """Build the OHLC request query params, applying default date bounds.

    The server accepts exactly one symbol per call and needs a full timestamp: a bare
    ``YYYY/MM/DD`` is completed to ``00:00:00`` (from) / ``23:59:59`` (to).
    """
    require_symbol(symbol, "symbol")
    _check_timeframe(timeframe)
    _check_paging(page, size)
    from_date = from_date or from_beginning_of_day()
    to_date = to_date or from_end_of_day()
    require_date_range(from_date, to_date, allow_time=True)
    from_date = _with_time(from_date, "00:00:00")
    to_date = _with_time(to_date, "23:59:59")
    to_date = _clamp_future_end(timeframe, from_date, to_date)
    return OHLCRequest(
        symbol=symbol,
        from_date=from_date,
        to_date=to_date,
        timeframe=timeframe,
        page=page,
        size=size,
    ).to_dict()


def _parse_ohlc(data: dict) -> list[OHLCData]:
    """Parse the raw OHLC response payload into a list of OHLCData."""
    return OHLCData.from_list(data=_data_rows(data, "OHLC"))


def _build_index_params(board: Board | None) -> dict:
    """Build the market indexes request query params."""
    return MarketIndexesRequest(board=_rest_board(board)).to_dict()


def _parse_indexes(data) -> list[MarketIndexes]:
    """Parse the raw indexes response payload into a list of MarketIndexes."""
    return MarketIndexes.from_list(_rows(data, "indexes"))


def _build_index_summary_params(
    index: str | None,
    board: Board | None,
    trading_date: str | None,
) -> dict:
    """Build the market index summary request query params."""
    return MarketIndexSummaryRequest(
        index=index,
        board=_rest_board(board),
        trading_date=trading_date,
    ).to_dict()


def _parse_index_summary(data) -> list[MarketIndexSummary]:
    """Parse the raw index summary payload into a list of MarketIndexSummary."""
    return MarketIndexSummary.from_list(_rows(data, "index summary"))


def _build_securities_info_params(
    index: str | None,
    board: Board | None,
    symbol: str | None,
) -> dict:
    """Build the securities info request query params."""
    return SecuritiesInfoRequest(index=index, board=_rest_board(board), symbol=symbol).to_dict()


def _parse_securities_info(data) -> list[SecuritiesInfo]:
    """Parse the raw securities info payload into a list of SecuritiesInfo."""
    return SecuritiesInfo.from_list(_rows(data, "securities info"))


def _build_securities_summary_params(
    from_date: str,
    to_date: str,
    symbol: str | None,
    index: str | None,
    page: int,
    size: int,
) -> dict:
    """Build the securities summary request query params.

    Exactly one of ``symbol``/``index`` is required and ``from``/``to`` must be
    ``YYYY/MM/DD`` with ``from <= to``; the server enforces the same, this just fails early.
    """
    require_exactly_one(symbol, index, "symbol", "index")
    require_date_range(from_date, to_date)
    _check_paging(page, size)
    return SecuritiesSummaryRequest(
        symbol=symbol,
        index=index,
        from_date=from_date,
        to_date=to_date,
        page=page,
        size=size,
    ).to_dict()


def _parse_securities_summary(data: dict) -> list[SecuritiesSummary]:
    """Parse the raw securities summary payload into a list of SecuritiesSummary."""
    return SecuritiesSummary.from_list(_data_rows(data, "securities summary"))


def _build_master_data_params(
    from_date: str,
    to_date: str,
    page: int,
    size: int,
) -> dict:
    """Build the master data request query params."""
    require_date_range(from_date, to_date)
    _check_paging(page, size)
    return MasterDataRequest(
        from_date=from_date,
        to_date=to_date,
        page=page,
        size=size,
    ).to_dict()


def _parse_master_data(data: dict) -> list[MasterData]:
    """Parse the raw master data response payload into a list of MasterData."""
    return MasterData.from_list(_data_rows(data, "master data"))


def _master_data_pages_count(data: dict) -> int:
    """Extract the total page count from a raw master data response payload."""
    return _pages_count(data)


def _check_page_size(size: int) -> int:
    """Page size must be positive, or an iterate-until-short-page loop never ends."""
    require_positive(size, "size")
    return size


# ── async class ──────────────────────────────────────────────


class AsyncMarketDataService:
    """Async market data: OHLC, index info, security info."""

    def __init__(self, rest_client: AsyncRestClient):
        """Initialize the service with an async REST client."""
        self._rest = rest_client

    # -- OHLC internal ------------------------------------------------

    async def _download_ohlc(self, symbol: str, timeframe: Timeframe) -> dict:
        """Download bulk OHLC data for a symbol (not implemented)."""
        raise NotImplementedError("OHLC download is not implemented yet")

    async def _get_ohlc(
        self,
        symbol: str,
        timeframe: Timeframe,
        from_date: str | None = None,
        to_date: str | None = None,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[OHLCData]:
        """Fetch OHLC bars for a symbol at the given timeframe."""
        params = _build_ohlc_params(symbol, timeframe, from_date, to_date, page, size)
        data = await self._rest.get(EP_DATA_OHLC, params=params)
        return _parse_ohlc(data)

    async def iter_ohlc(
        self,
        symbol: str,
        timeframe: Timeframe,
        from_date: str | None = None,
        to_date: str | None = None,
        size: int = DEFAULT_SIZE,
    ) -> AsyncIterator[OHLCData]:
        """Iterate over every OHLC bar in a range, fetching page after page.

        The OHLC endpoint reports no page count, so paging stops at the first empty or
        short page. Bars arrive in server order: newest first.

        Args:
            symbol: A single ticker symbol, e.g. "VNM".
            timeframe: Bar timeframe (1d, 1m, 3m, 5m, 15m or 1h).
            from_date: Range start; defaults to the start of today.
            to_date: Range end; defaults to the end of today.
            size: Bars requested per page (> 0).
        Yields:
            OHLCData bars.
        Raises:
            ValidationError: On a bad symbol, timeframe, date range or page size.
        """
        _check_page_size(size)
        page = DEFAULT_PAGE
        while True:
            bars = await self._get_ohlc(symbol, timeframe, from_date, to_date, page, size)
            for bar in bars:
                yield bar
            if len(bars) < size:
                return
            page += 1

    async def get_ohlc_all(
        self,
        symbol: str,
        timeframe: Timeframe,
        from_date: str | None = None,
        to_date: str | None = None,
        size: int = DEFAULT_SIZE,
        ascending: bool = False,
    ) -> list[OHLCData]:
        """Fetch every OHLC bar in a range across all pages.

        Args:
            symbol: A single ticker symbol, e.g. "VNM".
            timeframe: Bar timeframe (1d, 1m, 3m, 5m, 15m or 1h).
            from_date: Range start; defaults to the start of today.
            to_date: Range end; defaults to the end of today.
            size: Bars requested per page (> 0).
            ascending: Return oldest first. The server sends newest first.
        Returns:
            All bars in the range.
        Raises:
            ValidationError: On a bad symbol, timeframe, date range or page size.
        """
        bars = [bar async for bar in self.iter_ohlc(symbol, timeframe, from_date, to_date, size)]
        return bars[::-1] if ascending else bars

    # -- OHLC public (all preserved) -----------------------------------

    async def download_ohlc_1minute(self, symbol: str) -> dict:
        """Download bulk 1-minute OHLC data for a symbol.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            Raw OHLC payload.
        Raises:
            NotImplementedError: Bulk OHLC download is not implemented yet. The server has no
                ``data/file`` endpoint yet (its final response shape is undecided), so this
                stays unimplemented on purpose.
        """
        return await self._download_ohlc(symbol, Timeframe.MINUTE_1)

    async def download_ohlc_1day(self, symbol: str) -> dict:
        """Download bulk 1-day OHLC data for a symbol.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            Raw OHLC payload.
        Raises:
            NotImplementedError: Bulk OHLC download is not implemented yet. The server has no
                ``data/file`` endpoint yet (its final response shape is undecided), so this
                stays unimplemented on purpose.
        """
        return await self._download_ohlc(symbol, Timeframe.DAY_1)

    async def get_ohlc_1minute(self, symbol: str) -> list[OHLCData]:
        """Get 1-minute OHLC bars for the latest trading day.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            List of 1-minute OHLC bars.
        Raises:
            ValidationError: If symbol is empty.
        """
        return await self._get_ohlc(symbol, Timeframe.MINUTE_1)

    async def get_ohlc_1minute_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[OHLCData]:
        """Get 1-minute OHLC bars between two dates.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
            page: 1-based page number for pagination.
            size: Number of bars per page.
        Returns:
            List of 1-minute OHLC bars.
        Raises:
            ValidationError: If from_date or to_date is empty.
        """
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return await self._get_ohlc(symbol, Timeframe.MINUTE_1, from_date, to_date, page, size)

    async def get_ohlc_3minute(self, symbol: str) -> list[OHLCData]:
        """Get 3-minute OHLC bars for the latest trading day.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            List of 3-minute OHLC bars.
        Raises:
            ValidationError: If symbol is empty.
        """
        return await self._get_ohlc(symbol, Timeframe.MINUTE_3)

    async def get_ohlc_3minute_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[OHLCData]:
        """Get 3-minute OHLC bars between two dates.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
            page: 1-based page number for pagination.
            size: Number of bars per page.
        Returns:
            List of 3-minute OHLC bars.
        Raises:
            ValidationError: If from_date or to_date is empty.
        """
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return await self._get_ohlc(symbol, Timeframe.MINUTE_3, from_date, to_date, page, size)

    async def get_ohlc_5minute(self, symbol: str) -> list[OHLCData]:
        """Get 5-minute OHLC bars for the latest trading day.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            List of 5-minute OHLC bars.
        Raises:
            ValidationError: If symbol is empty.
        """
        return await self._get_ohlc(symbol, Timeframe.MINUTE_5)

    async def get_ohlc_5minute_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[OHLCData]:
        """Get 5-minute OHLC bars between two dates.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
            page: 1-based page number for pagination.
            size: Number of bars per page.
        Returns:
            List of 5-minute OHLC bars.
        Raises:
            ValidationError: If from_date or to_date is empty.
        """
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return await self._get_ohlc(symbol, Timeframe.MINUTE_5, from_date, to_date, page, size)

    async def get_ohlc_15minute(self, symbol: str) -> list[OHLCData]:
        """Get 15-minute OHLC bars for the latest trading day.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            List of 15-minute OHLC bars.
        Raises:
            ValidationError: If symbol is empty.
        """
        return await self._get_ohlc(symbol, Timeframe.MINUTE_15)

    async def get_ohlc_15minute_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[OHLCData]:
        """Get 15-minute OHLC bars between two dates.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
            page: 1-based page number for pagination.
            size: Number of bars per page.
        Returns:
            List of 15-minute OHLC bars.
        Raises:
            ValidationError: If from_date or to_date is empty.
        """
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return await self._get_ohlc(symbol, Timeframe.MINUTE_15, from_date, to_date, page, size)

    async def get_ohlc_1hour(self, symbol: str) -> list[OHLCData]:
        """Get 1-hour OHLC bars for the latest trading day.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            List of 1-hour OHLC bars.
        Raises:
            ValidationError: If symbol is empty.
        """
        return await self._get_ohlc(symbol, Timeframe.HOUR_1)

    async def get_ohlc_1hour_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[OHLCData]:
        """Get 1-hour OHLC bars between two dates.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
            page: 1-based page number for pagination.
            size: Number of bars per page.
        Returns:
            List of 1-hour OHLC bars.
        Raises:
            ValidationError: If from_date or to_date is empty.
        """
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return await self._get_ohlc(symbol, Timeframe.HOUR_1, from_date, to_date, page, size)

    async def get_ohlc_1day_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[OHLCData]:
        """Get 1-day OHLC bars between two dates.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
            page: 1-based page number for pagination.
            size: Number of bars per page.
        Returns:
            List of 1-day OHLC bars.
        Raises:
            ValidationError: If from_date or to_date is empty.
        """
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return await self._get_ohlc(symbol, Timeframe.DAY_1, from_date, to_date, page, size)

    async def get_ohlc_1week_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[OHLCData]:
        """Deprecated: the server does not serve 1-week OHLC bars.

        Always raises ``ValidationError`` (the server answers 400210). Request 1-day bars with
        ``get_ohlc_1day_historical`` and aggregate them client-side.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
            page: 1-based page number for pagination.
            size: Number of bars per page.
        Returns:
            List of 1-week OHLC bars.
        Raises:
            ValidationError: If from_date or to_date is empty.
        """
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        raise ValidationError(_WEEK_MONTH_REJECTED.format(name="1w"))

    async def get_ohlc_1month_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[OHLCData]:
        """Deprecated: the server does not serve 1-month OHLC bars.

        Always raises ``ValidationError`` (the server answers 400210). Request 1-day bars with
        ``get_ohlc_1day_historical`` and aggregate them client-side.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
            page: 1-based page number for pagination.
            size: Number of bars per page.
        Returns:
            List of 1-month OHLC bars.
        Raises:
            ValidationError: If from_date or to_date is empty.
        """
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        raise ValidationError(_WEEK_MONTH_REJECTED.format(name="1M"))

    # -- Index ---------------------------------------------------------

    async def _get_indexes(self, board: Board | None = None) -> list[MarketIndexes]:
        """Fetch market indexes, optionally filtered by board."""
        params = _build_index_params(board)
        data = await self._rest.get(EP_DATA_INDEX_LIST, params=params)
        return _parse_indexes(data)

    async def get_indexes(self) -> list[MarketIndexes]:
        """Get all market indexes.

        Returns:
            List of market indexes.
        """
        return await self._get_indexes()

    async def get_indexes_by_board(self, board: Board) -> list[MarketIndexes]:
        """Get market indexes for a specific exchange board.

        Args:
            board: Exchange board to filter by.
        Returns:
            List of market indexes on the board.
        Raises:
            ValidationError: If board is empty.
        """
        require_non_empty(board, "board")
        return await self._get_indexes(board=board)

    # -- Index summary -------------------------------------------------

    async def _get_index_summary(
        self,
        index: str | None = None,
        board: Board | None = None,
        trading_date: str | None = None,
    ) -> list[MarketIndexSummary]:
        """Fetch index summaries filtered by index, board, or trading date."""
        params = _build_index_summary_params(index, board, trading_date)
        data = await self._rest.get(EP_DATA_INDEX_SUMMARY, params=params)
        return _parse_index_summary(data)

    async def get_index_summary(self, index: str) -> MarketIndexSummary | None:
        """Get the latest summary for an index.

        Args:
            index: Index code.
        Returns:
            The index summary, or None if not found.
        Raises:
            ValidationError: If index is empty.
        """
        require_non_empty(index, "index")
        result = await self._get_index_summary(index=index)
        return result[0] if result else None

    async def get_index_summary_historical(
        self,
        index: str,
        trading_date: str,
    ) -> MarketIndexSummary | None:
        """Get the summary for an index on a specific trading date.

        Args:
            index: Index code.
            trading_date: Trading date "YYYY/MM/DD".
        Returns:
            The index summary, or None if not found.
        Raises:
            ValidationError: If index or trading_date is empty.
        """
        require_non_empty(index, "index")
        require_non_empty(trading_date, "tradingDate")
        result = await self._get_index_summary(index=index, trading_date=trading_date)
        return result[0] if result else None

    async def get_board_summary(self, board: Board) -> MarketIndexSummary | None:
        """Get the latest summary for an exchange board.

        Args:
            board: Exchange board.
        Returns:
            The board summary, or None if not found.
        Raises:
            ValidationError: If board is empty.
        """
        require_non_empty(board, "board")
        result = await self._get_index_summary(board=board)
        return result[0] if result else None

    async def get_board_summary_historical(
        self,
        board: Board,
        trading_date: str,
    ) -> MarketIndexSummary | None:
        """Get the summary for an exchange board on a specific trading date.

        Args:
            board: Exchange board.
            trading_date: Trading date "YYYY/MM/DD".
        Returns:
            The board summary, or None if not found.
        Raises:
            ValidationError: If board or trading_date is empty.
        """
        require_non_empty(board, "board")
        require_non_empty(trading_date, "tradingDate")
        result = await self._get_index_summary(board=board, trading_date=trading_date)
        return result[0] if result else None

    # -- Securities info -----------------------------------------------

    async def _get_securities_info(
        self,
        index: str | None = None,
        board: Board | None = None,
        symbol: str | None = None,
    ) -> list[SecuritiesInfo]:
        """Fetch securities info filtered by index, board, or symbol."""
        params = _build_securities_info_params(index, board, symbol)
        data = await self._rest.get(EP_DATA_SECURITIES_BY_BOARD, params=params)
        return _parse_securities_info(data)

    async def get_securities_info(self, symbol: str) -> SecuritiesInfo | None:
        """Get the info record for a single security.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            The security info, or None if not found.
        Raises:
            ValidationError: If symbol is empty.
        """
        require_non_empty(symbol, "symbol")
        result = await self._get_securities_info(symbol=symbol)
        return result[0] if result else None

    async def get_securities_info_by_index(self, index: str) -> list[SecuritiesInfo]:
        """Get info records for all securities in an index.

        Args:
            index: Index code.
        Returns:
            List of security info records.
        Raises:
            ValidationError: If index is empty.
        """
        require_non_empty(index, "index")
        return await self._get_securities_info(index=index)

    async def get_securities_info_by_board(self, board: Board) -> list[SecuritiesInfo]:
        """Get info records for all securities on an exchange board.

        Args:
            board: Exchange board.
        Returns:
            List of security info records.
        Raises:
            ValidationError: If board is empty.
        """
        require_non_empty(board, "board")
        return await self._get_securities_info(board=board)

    # -- Securities summary --------------------------------------------

    async def _get_securities_summary(
        self,
        from_date: str,
        to_date: str,
        symbol: str | None = None,
        index: str | None = None,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[SecuritiesSummary]:
        """Fetch securities summaries for a date range, filtered by symbol or index."""
        params = _build_securities_summary_params(
            from_date,
            to_date,
            symbol,
            index,
            page,
            size,
        )
        data = await self._rest.get(EP_DATA_SECURITIES_SUMMARY, params=params)
        items = _parse_securities_summary(data)
        pages = _pages_count(data)
        while page < pages and items:
            page += 1
            params = _build_securities_summary_params(
                from_date, to_date, symbol, index, page, size
            )
            data = await self._rest.get(EP_DATA_SECURITIES_SUMMARY, params=params)
            more = _parse_securities_summary(data)
            if not more:
                break
            items.extend(more)
        return items

    async def get_securities_summary(self, symbol: str) -> list[SecuritiesSummary]:
        """Get today's securities summary for a symbol.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            List of securities summary records for today.
        Raises:
            ValidationError: If symbol is empty.
        """
        require_non_empty(symbol, "symbol")
        return await self._get_securities_summary(
            symbol=symbol,
            from_date=today_date_str(),
            to_date=today_date_str(),
        )

    async def get_securities_summary_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
    ) -> list[SecuritiesSummary]:
        """Get the securities summary for a symbol between two dates.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
        Returns:
            List of securities summary records.
        Raises:
            ValidationError: If symbol, from_date, or to_date is empty.
        """
        require_non_empty(symbol, "symbol")
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return await self._get_securities_summary(
            symbol=symbol,
            from_date=from_date,
            to_date=to_date,
        )

    async def get_securities_summary_by_index(self, index: str) -> list[SecuritiesSummary]:
        """Get today's securities summary for all members of an index.

        Args:
            index: Index code.
        Returns:
            List of securities summary records for today.
        Raises:
            ValidationError: If index is empty.
        """
        require_non_empty(index, "index")
        return await self._get_securities_summary(
            index=index,
            from_date=today_date_str(),
            to_date=today_date_str(),
        )

    async def get_securities_summary_by_index_historical(
        self,
        index: str,
        from_date: str,
        to_date: str,
    ) -> list[SecuritiesSummary]:
        """Get the securities summary for index members between two dates.

        Args:
            index: Index code.
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
        Returns:
            List of securities summary records.
        Raises:
            ValidationError: If index, from_date, or to_date is empty.
        """
        require_non_empty(index, "index")
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return await self._get_securities_summary(
            index=index,
            from_date=from_date,
            to_date=to_date,
        )

    # -- Master data -----------------------------------------------------

    async def _get_master_data(self, from_date: str, to_date: str) -> list[MasterData]:
        """Fetch every page of master data for a date range and return the combined list."""
        page = DEFAULT_PAGE
        items: list[MasterData] = []
        while True:
            params = _build_master_data_params(from_date, to_date, page, DEFAULT_SIZE)
            data = await self._rest.get(EP_DATA_MASTER_DATA, params=params)
            items.extend(_parse_master_data(data))
            if page >= _master_data_pages_count(data):
                break
            page += 1
        return items

    async def get_master_data(self) -> list[MasterData]:
        """Get today's reference price data (ceiling/floor/reference) for all symbols.

        The API paginates this endpoint — this method fetches every page
        internally and returns the combined list, so callers don't need to
        deal with page/size themselves.

        Returns:
            List of today's reference price records.
        """
        today = today_date_str()
        return await self._get_master_data(today, today)

    async def get_master_data_historical(
        self, from_date: str, to_date: str
    ) -> list[MasterData]:
        """Get reference price data (ceiling/floor/reference) for all symbols.

        The API paginates this endpoint — this method fetches every page
        internally and returns the combined list, so callers don't need to
        deal with page/size themselves.

        Args:
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
        Returns:
            List of reference price records in the date range.
        Raises:
            ValidationError: If from_date or to_date is empty.
        """
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return await self._get_master_data(from_date, to_date)


# ── sync class ───────────────────────────────────────────────


class MarketDataService:
    """Synchronous market data: OHLC, index info, security info."""

    def __init__(self, rest_client: RestClient):
        """Initialize the service with a synchronous REST client."""
        self._rest = rest_client

    # -- OHLC internal ------------------------------------------------

    def _download_ohlc(self, symbol: str, timeframe: Timeframe) -> dict:
        """Download bulk OHLC data for a symbol (not implemented)."""
        raise NotImplementedError("OHLC download is not implemented yet")

    def _get_ohlc(
        self,
        symbol: str,
        timeframe: Timeframe,
        from_date: str | None = None,
        to_date: str | None = None,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[OHLCData]:
        """Fetch OHLC bars for a symbol at the given timeframe."""
        params = _build_ohlc_params(symbol, timeframe, from_date, to_date, page, size)
        data = self._rest.get(EP_DATA_OHLC, params=params)
        return _parse_ohlc(data)

    def iter_ohlc(
        self,
        symbol: str,
        timeframe: Timeframe,
        from_date: str | None = None,
        to_date: str | None = None,
        size: int = DEFAULT_SIZE,
    ) -> Iterator[OHLCData]:
        """Iterate over every OHLC bar in a range, fetching page after page.

        The OHLC endpoint reports no page count, so paging stops at the first empty or
        short page. Bars arrive in server order: newest first.

        Args:
            symbol: A single ticker symbol, e.g. "VNM".
            timeframe: Bar timeframe (1d, 1m, 3m, 5m, 15m or 1h).
            from_date: Range start; defaults to the start of today.
            to_date: Range end; defaults to the end of today.
            size: Bars requested per page (> 0).
        Yields:
            OHLCData bars.
        Raises:
            ValidationError: On a bad symbol, timeframe, date range or page size.
        """
        _check_page_size(size)
        page = DEFAULT_PAGE
        while True:
            bars = self._get_ohlc(symbol, timeframe, from_date, to_date, page, size)
            for bar in bars:
                yield bar
            if len(bars) < size:
                return
            page += 1

    def get_ohlc_all(
        self,
        symbol: str,
        timeframe: Timeframe,
        from_date: str | None = None,
        to_date: str | None = None,
        size: int = DEFAULT_SIZE,
        ascending: bool = False,
    ) -> list[OHLCData]:
        """Fetch every OHLC bar in a range across all pages.

        Args:
            symbol: A single ticker symbol, e.g. "VNM".
            timeframe: Bar timeframe (1d, 1m, 3m, 5m, 15m or 1h).
            from_date: Range start; defaults to the start of today.
            to_date: Range end; defaults to the end of today.
            size: Bars requested per page (> 0).
            ascending: Return oldest first. The server sends newest first.
        Returns:
            All bars in the range.
        Raises:
            ValidationError: On a bad symbol, timeframe, date range or page size.
        """
        bars = [bar for bar in self.iter_ohlc(symbol, timeframe, from_date, to_date, size)]
        return bars[::-1] if ascending else bars

    # -- OHLC public (all preserved) -----------------------------------

    def download_ohlc_1minute(self, symbol: str) -> dict:
        """Download bulk 1-minute OHLC data for a symbol.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            Raw OHLC payload.
        Raises:
            NotImplementedError: Bulk OHLC download is not implemented yet. The server has no
                ``data/file`` endpoint yet (its final response shape is undecided), so this
                stays unimplemented on purpose.
        """
        return self._download_ohlc(symbol, Timeframe.MINUTE_1)

    def download_ohlc_1day(self, symbol: str) -> dict:
        """Download bulk 1-day OHLC data for a symbol.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            Raw OHLC payload.
        Raises:
            NotImplementedError: Bulk OHLC download is not implemented yet. The server has no
                ``data/file`` endpoint yet (its final response shape is undecided), so this
                stays unimplemented on purpose.
        """
        return self._download_ohlc(symbol, Timeframe.DAY_1)

    def get_ohlc_1minute(self, symbol: str) -> list[OHLCData]:
        """Get 1-minute OHLC bars for the latest trading day.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            List of 1-minute OHLC bars.
        Raises:
            ValidationError: If symbol is empty.
        """
        return self._get_ohlc(symbol, Timeframe.MINUTE_1)

    def get_ohlc_1minute_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[OHLCData]:
        """Get 1-minute OHLC bars between two dates.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
            page: 1-based page number for pagination.
            size: Number of bars per page.
        Returns:
            List of 1-minute OHLC bars.
        Raises:
            ValidationError: If from_date or to_date is empty.
        """
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return self._get_ohlc(symbol, Timeframe.MINUTE_1, from_date, to_date, page, size)

    def get_ohlc_3minute(self, symbol: str) -> list[OHLCData]:
        """Get 3-minute OHLC bars for the latest trading day.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            List of 3-minute OHLC bars.
        Raises:
            ValidationError: If symbol is empty.
        """
        return self._get_ohlc(symbol, Timeframe.MINUTE_3)

    def get_ohlc_3minute_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[OHLCData]:
        """Get 3-minute OHLC bars between two dates.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
            page: 1-based page number for pagination.
            size: Number of bars per page.
        Returns:
            List of 3-minute OHLC bars.
        Raises:
            ValidationError: If from_date or to_date is empty.
        """
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return self._get_ohlc(symbol, Timeframe.MINUTE_3, from_date, to_date, page, size)

    def get_ohlc_5minute(self, symbol: str) -> list[OHLCData]:
        """Get 5-minute OHLC bars for the latest trading day.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            List of 5-minute OHLC bars.
        Raises:
            ValidationError: If symbol is empty.
        """
        return self._get_ohlc(symbol, Timeframe.MINUTE_5)

    def get_ohlc_5minute_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[OHLCData]:
        """Get 5-minute OHLC bars between two dates.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
            page: 1-based page number for pagination.
            size: Number of bars per page.
        Returns:
            List of 5-minute OHLC bars.
        Raises:
            ValidationError: If from_date or to_date is empty.
        """
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return self._get_ohlc(symbol, Timeframe.MINUTE_5, from_date, to_date, page, size)

    def get_ohlc_15minute(self, symbol: str) -> list[OHLCData]:
        """Get 15-minute OHLC bars for the latest trading day.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            List of 15-minute OHLC bars.
        Raises:
            ValidationError: If symbol is empty.
        """
        return self._get_ohlc(symbol, Timeframe.MINUTE_15)

    def get_ohlc_15minute_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[OHLCData]:
        """Get 15-minute OHLC bars between two dates.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
            page: 1-based page number for pagination.
            size: Number of bars per page.
        Returns:
            List of 15-minute OHLC bars.
        Raises:
            ValidationError: If from_date or to_date is empty.
        """
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return self._get_ohlc(symbol, Timeframe.MINUTE_15, from_date, to_date, page, size)

    def get_ohlc_1hour(self, symbol: str) -> list[OHLCData]:
        """Get 1-hour OHLC bars for the latest trading day.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            List of 1-hour OHLC bars.
        Raises:
            ValidationError: If symbol is empty.
        """
        return self._get_ohlc(symbol, Timeframe.HOUR_1)

    def get_ohlc_1hour_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[OHLCData]:
        """Get 1-hour OHLC bars between two dates.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
            page: 1-based page number for pagination.
            size: Number of bars per page.
        Returns:
            List of 1-hour OHLC bars.
        Raises:
            ValidationError: If from_date or to_date is empty.
        """
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return self._get_ohlc(symbol, Timeframe.HOUR_1, from_date, to_date, page, size)

    def get_ohlc_1day_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[OHLCData]:
        """Get 1-day OHLC bars between two dates.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
            page: 1-based page number for pagination.
            size: Number of bars per page.
        Returns:
            List of 1-day OHLC bars.
        Raises:
            ValidationError: If from_date or to_date is empty.
        """
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return self._get_ohlc(symbol, Timeframe.DAY_1, from_date, to_date, page, size)

    def get_ohlc_1week_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[OHLCData]:
        """Deprecated: the server does not serve 1-week OHLC bars.

        Always raises ``ValidationError`` (the server answers 400210). Request 1-day bars with
        ``get_ohlc_1day_historical`` and aggregate them client-side.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
            page: 1-based page number for pagination.
            size: Number of bars per page.
        Returns:
            List of 1-week OHLC bars.
        Raises:
            ValidationError: If from_date or to_date is empty.
        """
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        raise ValidationError(_WEEK_MONTH_REJECTED.format(name="1w"))

    def get_ohlc_1month_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[OHLCData]:
        """Deprecated: the server does not serve 1-month OHLC bars.

        Always raises ``ValidationError`` (the server answers 400210). Request 1-day bars with
        ``get_ohlc_1day_historical`` and aggregate them client-side.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
            page: 1-based page number for pagination.
            size: Number of bars per page.
        Returns:
            List of 1-month OHLC bars.
        Raises:
            ValidationError: If from_date or to_date is empty.
        """
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        raise ValidationError(_WEEK_MONTH_REJECTED.format(name="1M"))

    # -- Index ---------------------------------------------------------

    def _get_indexes(self, board: Board | None = None) -> list[MarketIndexes]:
        """Fetch market indexes, optionally filtered by board."""
        params = _build_index_params(board)
        data = self._rest.get(EP_DATA_INDEX_LIST, params=params)
        return _parse_indexes(data)

    def get_indexes(self) -> list[MarketIndexes]:
        """Get all market indexes.

        Returns:
            List of market indexes.
        """
        return self._get_indexes()

    def get_indexes_by_board(self, board: Board) -> list[MarketIndexes]:
        """Get market indexes for a specific exchange board.

        Args:
            board: Exchange board to filter by.
        Returns:
            List of market indexes on the board.
        Raises:
            ValidationError: If board is empty.
        """
        require_non_empty(board, "board")
        return self._get_indexes(board=board)

    # -- Index summary -------------------------------------------------

    def _get_index_summary(
        self,
        index: str | None = None,
        board: Board | None = None,
        trading_date: str | None = None,
    ) -> list[MarketIndexSummary]:
        """Fetch index summaries filtered by index, board, or trading date."""
        params = _build_index_summary_params(index, board, trading_date)
        data = self._rest.get(EP_DATA_INDEX_SUMMARY, params=params)
        return _parse_index_summary(data)

    def get_index_summary(self, index: str) -> MarketIndexSummary | None:
        """Get the latest summary for an index.

        Args:
            index: Index code.
        Returns:
            The index summary, or None if not found.
        Raises:
            ValidationError: If index is empty.
        """
        require_non_empty(index, "index")
        result = self._get_index_summary(index=index)
        return result[0] if result else None

    def get_index_summary_historical(
        self,
        index: str,
        trading_date: str,
    ) -> MarketIndexSummary | None:
        """Get the summary for an index on a specific trading date.

        Args:
            index: Index code.
            trading_date: Trading date "YYYY/MM/DD".
        Returns:
            The index summary, or None if not found.
        Raises:
            ValidationError: If index or trading_date is empty.
        """
        require_non_empty(index, "index")
        require_non_empty(trading_date, "tradingDate")
        result = self._get_index_summary(index=index, trading_date=trading_date)
        return result[0] if result else None

    def get_board_summary(self, board: Board) -> MarketIndexSummary | None:
        """Get the latest summary for an exchange board.

        Args:
            board: Exchange board.
        Returns:
            The board summary, or None if not found.
        Raises:
            ValidationError: If board is empty.
        """
        require_non_empty(board, "board")
        result = self._get_index_summary(board=board)
        return result[0] if result else None

    def get_board_summary_historical(
        self,
        board: Board,
        trading_date: str,
    ) -> MarketIndexSummary | None:
        """Get the summary for an exchange board on a specific trading date.

        Args:
            board: Exchange board.
            trading_date: Trading date "YYYY/MM/DD".
        Returns:
            The board summary, or None if not found.
        Raises:
            ValidationError: If board or trading_date is empty.
        """
        require_non_empty(board, "board")
        require_non_empty(trading_date, "tradingDate")
        result = self._get_index_summary(board=board, trading_date=trading_date)
        return result[0] if result else None

    # -- Securities info -----------------------------------------------

    def _get_securities_info(
        self,
        index: str | None = None,
        board: Board | None = None,
        symbol: str | None = None,
    ) -> list[SecuritiesInfo]:
        """Fetch securities info filtered by index, board, or symbol."""
        params = _build_securities_info_params(index, board, symbol)
        data = self._rest.get(EP_DATA_SECURITIES_BY_BOARD, params=params)
        return _parse_securities_info(data)

    def get_securities_info(self, symbol: str) -> SecuritiesInfo | None:
        """Get the info record for a single security.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            The security info, or None if not found.
        Raises:
            ValidationError: If symbol is empty.
        """
        require_non_empty(symbol, "symbol")
        result = self._get_securities_info(symbol=symbol)
        return result[0] if result else None

    def get_securities_info_by_index(self, index: str) -> list[SecuritiesInfo]:
        """Get info records for all securities in an index.

        Args:
            index: Index code.
        Returns:
            List of security info records.
        Raises:
            ValidationError: If index is empty.
        """
        require_non_empty(index, "index")
        return self._get_securities_info(index=index)

    def get_securities_info_by_board(self, board: Board) -> list[SecuritiesInfo]:
        """Get info records for all securities on an exchange board.

        Args:
            board: Exchange board.
        Returns:
            List of security info records.
        Raises:
            ValidationError: If board is empty.
        """
        require_non_empty(board, "board")
        return self._get_securities_info(board=board)

    # -- Securities summary --------------------------------------------

    def _get_securities_summary(
        self,
        from_date: str,
        to_date: str,
        symbol: str | None = None,
        index: str | None = None,
        page: int = DEFAULT_PAGE,
        size: int = DEFAULT_SIZE,
    ) -> list[SecuritiesSummary]:
        """Fetch securities summaries for a date range, filtered by symbol or index."""
        params = _build_securities_summary_params(
            from_date,
            to_date,
            symbol,
            index,
            page,
            size,
        )
        data = self._rest.get(EP_DATA_SECURITIES_SUMMARY, params=params)
        items = _parse_securities_summary(data)
        pages = _pages_count(data)
        while page < pages and items:
            page += 1
            params = _build_securities_summary_params(
                from_date, to_date, symbol, index, page, size
            )
            data = self._rest.get(EP_DATA_SECURITIES_SUMMARY, params=params)
            more = _parse_securities_summary(data)
            if not more:
                break
            items.extend(more)
        return items

    def get_securities_summary(self, symbol: str) -> list[SecuritiesSummary]:
        """Get today's securities summary for a symbol.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
        Returns:
            List of securities summary records for today.
        Raises:
            ValidationError: If symbol is empty.
        """
        require_non_empty(symbol, "symbol")
        return self._get_securities_summary(
            symbol=symbol,
            from_date=today_date_str(),
            to_date=today_date_str(),
        )

    def get_securities_summary_historical(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
    ) -> list[SecuritiesSummary]:
        """Get the securities summary for a symbol between two dates.

        Args:
            symbol: Ticker symbol, e.g. "VNM".
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
        Returns:
            List of securities summary records.
        Raises:
            ValidationError: If symbol, from_date, or to_date is empty.
        """
        require_non_empty(symbol, "symbol")
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return self._get_securities_summary(
            symbol=symbol,
            from_date=from_date,
            to_date=to_date,
        )

    def get_securities_summary_by_index(self, index: str) -> list[SecuritiesSummary]:
        """Get today's securities summary for all members of an index.

        Args:
            index: Index code.
        Returns:
            List of securities summary records for today.
        Raises:
            ValidationError: If index is empty.
        """
        require_non_empty(index, "index")
        return self._get_securities_summary(
            index=index,
            from_date=today_date_str(),
            to_date=today_date_str(),
        )

    def get_securities_summary_by_index_historical(
        self,
        index: str,
        from_date: str,
        to_date: str,
    ) -> list[SecuritiesSummary]:
        """Get the securities summary for index members between two dates.

        Args:
            index: Index code.
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
        Returns:
            List of securities summary records.
        Raises:
            ValidationError: If index, from_date, or to_date is empty.
        """
        require_non_empty(index, "index")
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return self._get_securities_summary(
            index=index,
            from_date=from_date,
            to_date=to_date,
        )

    # -- Master data -----------------------------------------------------

    def _get_master_data(self, from_date: str, to_date: str) -> list[MasterData]:
        """Fetch every page of master data for a date range and return the combined list."""
        page = DEFAULT_PAGE
        items: list[MasterData] = []
        while True:
            params = _build_master_data_params(from_date, to_date, page, DEFAULT_SIZE)
            data = self._rest.get(EP_DATA_MASTER_DATA, params=params)
            items.extend(_parse_master_data(data))
            if page >= _master_data_pages_count(data):
                break
            page += 1
        return items

    def get_master_data(self) -> list[MasterData]:
        """Get today's reference price data (ceiling/floor/reference) for all symbols.

        The API paginates this endpoint — this method fetches every page
        internally and returns the combined list, so callers don't need to
        deal with page/size themselves.

        Returns:
            List of today's reference price records.
        """
        today = today_date_str()
        return self._get_master_data(today, today)

    def get_master_data_historical(self, from_date: str, to_date: str) -> list[MasterData]:
        """Get reference price data (ceiling/floor/reference) for all symbols.

        The API paginates this endpoint — this method fetches every page
        internally and returns the combined list, so callers don't need to
        deal with page/size themselves.

        Args:
            from_date: Start date "YYYY/MM/DD".
            to_date: End date "YYYY/MM/DD".
        Returns:
            List of reference price records in the date range.
        Raises:
            ValidationError: If from_date or to_date is empty.
        """
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return self._get_master_data(from_date, to_date)
