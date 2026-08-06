"""Portfolio service — async and sync."""

from __future__ import annotations

import logging

from ssi_sdk.config import Config
from ssi_sdk.constant import (
    DEFAULT_PAGE,
    DEFAULT_SIZE,
    EP_ACCOUNT_BALANCE,
    EP_ACCOUNT_PPMMR,
    EP_ORDER_HISTORY,
    EP_POSITIONS,
)
from ssi_sdk.models import (
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
from ssi_sdk.transport.rest_client import AsyncRestClient, RestClient
from ssi_sdk.utils import require_non_empty, today_date_str

logger = logging.getLogger("ssi_sdk.services.portfolio")


# ── shared logic ─────────────────────────────────────────────


def _build_balance_params(client_id: str, account_no: str) -> dict:
    """Build query params for the account balance request."""
    return AccountBalanceRequest(client_id=client_id, account_no=account_no).to_dict()


def _build_order_book_params(
    account_no: str,
    from_date: str | None,
    to_date: str | None,
) -> dict:
    """Build query params for the order book request."""
    return OrderBookRequest(
        account_no=account_no,
        from_date=from_date,
        to_date=to_date,
        page=DEFAULT_PAGE,
        size=DEFAULT_SIZE,
    ).to_dict()


def _build_positions_params(client_id: str | None, account_no: str | None) -> dict:
    """Build query params for the positions request."""
    return PositionsRequest(client_id=client_id, account_no=account_no).to_dict()


def _build_ppmmr_params(account_no: str | None) -> dict:
    """Build query params for the PPMMR request."""
    return PPMMRRequest(account_no=account_no).to_dict()


# ── async class ──────────────────────────────────────────────


class AsyncPortfolioService:
    """Async portfolio operations."""

    def __init__(self, rest_client: AsyncRestClient, config: Config):
        """Initialize the service with an async REST client and config."""
        self._rest = rest_client
        self._client_id = config.client_id

    async def _get_balance(self, account_no: str) -> AccountBalance:
        """Fetch the combined account balance for the account."""
        params = _build_balance_params(self._client_id, account_no)
        data = await self._rest.get(EP_ACCOUNT_BALANCE, params=params)
        return AccountBalance.from_dict(data)

    async def get_equity_balance(self, account_no: str) -> EquityAccountBalance:
        """Get the equity account balance for a trading account.

        Args:
            account_no: Trading account number.
        Returns:
            The equity portion of the account balance.
        Raises:
            ValidationError: If account_no is empty.
        """
        require_non_empty(account_no, "accountNo")
        return (await self._get_balance(account_no)).equity

    async def get_derivative_balance(self, account_no: str) -> DerivativeAccountBalance:
        """Get the derivative account balance for a trading account.

        Args:
            account_no: Trading account number.
        Returns:
            The derivative portion of the account balance.
        Raises:
            ValidationError: If account_no is empty.
        """
        require_non_empty(account_no, "accountNo")
        return (await self._get_balance(account_no)).derivative

    async def _get_order_book(
        self,
        account_no: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> OrderBook:
        """Fetch the order book for the account within the date range."""
        params = _build_order_book_params(account_no, from_date, to_date)
        data = await self._rest.get(EP_ORDER_HISTORY, params=params)
        return OrderBook.from_dict(data)

    async def get_today_orders(self, account_no: str) -> list[Order]:
        """Get today's orders for a trading account.

        Args:
            account_no: Trading account number.
        Returns:
            The list of orders placed today.
        Raises:
            ValidationError: If account_no is empty.
        """
        require_non_empty(account_no, "accountNo")
        today = today_date_str()
        return (await self._get_order_book(account_no, from_date=today, to_date=today)).orders

    async def get_historical_orders(
        self,
        account_no: str,
        from_date: str,
        to_date: str,
    ) -> list[Order]:
        """Get historical orders for a trading account within a date range.

        Args:
            account_no: Trading account number.
            from_date: Start date in "YYYY/MM/DD" format.
            to_date: End date in "YYYY/MM/DD" format.
        Returns:
            The list of orders placed within the date range.
        Raises:
            ValidationError: If account_no, from_date, or to_date is empty.
        """
        require_non_empty(account_no, "accountNo")
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return (await self._get_order_book(account_no, from_date=from_date, to_date=to_date)).orders

    async def _get_positions(
        self,
        client_id: str | None = None,
        account_no: str | None = None,
    ) -> Position:
        """Fetch the combined positions for the account."""
        params = _build_positions_params(client_id, account_no)
        data = await self._rest.get(EP_POSITIONS, params=params)
        return Position.from_dict(data)

    async def get_equity_positions(self, account_no: str) -> list[EquityPosition]:
        """Get equity positions for a trading account.

        Args:
            account_no: Trading account number.
        Returns:
            The list of equity positions.
        Raises:
            ValidationError: If account_no is empty.
        """
        require_non_empty(account_no, "accountNo")
        return (await self._get_positions(client_id=self._client_id, account_no=account_no)).equity

    async def get_derivative_positions(self, account_no: str) -> list[AllDerivativePosition]:
        """Get all derivative positions for a trading account.

        Args:
            account_no: Trading account number.
        Returns:
            The list of all derivative positions (open and closed).
        Raises:
            ValidationError: If account_no is empty.
        """
        require_non_empty(account_no, "accountNo")
        return (
            await self._get_positions(client_id=self._client_id, account_no=account_no)
        ).derivative

    async def get_open_derivative_positions(self, account_no: str) -> list[DerivativePosition]:
        """Get open derivative positions for a trading account.

        Args:
            account_no: Trading account number.
        Returns:
            The list of open derivative positions.
        Raises:
            ValidationError: If account_no is empty.
        """
        require_non_empty(account_no, "accountNo")
        return (
            await self._get_positions(client_id=self._client_id, account_no=account_no)
        ).derivative.open_positions

    async def get_closed_derivative_positions(self, account_no: str) -> list[DerivativePosition]:
        """Get closed derivative positions for a trading account.

        Args:
            account_no: Trading account number.
        Returns:
            The list of closed derivative positions.
        Raises:
            ValidationError: If account_no is empty.
        """
        require_non_empty(account_no, "accountNo")
        return (
            await self._get_positions(client_id=self._client_id, account_no=account_no)
        ).derivative.closed_positions

    async def _get_ppmmr(self, account_no: str | None = None) -> PPMMR:
        """Fetch the combined PPMMR for the account."""
        params = _build_ppmmr_params(account_no)
        data = await self._rest.get(EP_ACCOUNT_PPMMR, params=params)
        return PPMMR.from_dict(data)

    async def get_equity_ppmmr(self, account_no: str) -> EquityPPMMR:
        """Get equity purchasing power and maintenance margin ratio for a trading account.

        Args:
            account_no: Trading account number.
        Returns:
            The equity purchasing power and maintenance margin ratio.
        Raises:
            ValidationError: If account_no is empty.
        """
        require_non_empty(account_no, "accountNo")
        return (await self._get_ppmmr(account_no=account_no)).equity

    async def get_derivative_ppmmr(self, account_no: str) -> DerivativePPMMR:
        """Get derivative purchasing power and maintenance margin ratio for a trading account.

        Args:
            account_no: Trading account number.
        Returns:
            The derivative purchasing power and maintenance margin ratio.
        Raises:
            ValidationError: If account_no is empty.
        """
        require_non_empty(account_no, "accountNo")
        return (await self._get_ppmmr(account_no=account_no)).derivative


# ── sync class ───────────────────────────────────────────────


class PortfolioService:
    """Synchronous portfolio operations."""

    def __init__(self, rest_client: RestClient, config: Config):
        """Initialize the service with a sync REST client and config."""
        self._rest = rest_client
        self._client_id = config.client_id

    def _get_balance(self, account_no: str) -> AccountBalance:
        """Fetch the combined account balance for the account."""
        params = _build_balance_params(self._client_id, account_no)
        data = self._rest.get(EP_ACCOUNT_BALANCE, params=params)
        return AccountBalance.from_dict(data)

    def get_equity_balance(self, account_no: str) -> EquityAccountBalance:
        """Get the equity account balance for a trading account.

        Args:
            account_no: Trading account number.
        Returns:
            The equity portion of the account balance.
        Raises:
            ValidationError: If account_no is empty.
        """
        require_non_empty(account_no, "accountNo")
        return self._get_balance(account_no).equity

    def get_derivative_balance(self, account_no: str) -> DerivativeAccountBalance:
        """Get the derivative account balance for a trading account.

        Args:
            account_no: Trading account number.
        Returns:
            The derivative portion of the account balance.
        Raises:
            ValidationError: If account_no is empty.
        """
        require_non_empty(account_no, "accountNo")
        return self._get_balance(account_no).derivative

    def _get_order_book(
        self,
        account_no: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> OrderBook:
        """Fetch the order book for the account within the date range."""
        params = _build_order_book_params(account_no, from_date, to_date)
        data = self._rest.get(EP_ORDER_HISTORY, params=params)
        return OrderBook.from_dict(data)

    def get_today_orders(self, account_no: str) -> list[Order]:
        """Get today's orders for a trading account.

        Args:
            account_no: Trading account number.
        Returns:
            The list of orders placed today.
        Raises:
            ValidationError: If account_no is empty.
        """
        require_non_empty(account_no, "accountNo")
        today = today_date_str()
        return self._get_order_book(account_no, from_date=today, to_date=today).orders

    def get_historical_orders(
        self,
        account_no: str,
        from_date: str,
        to_date: str,
    ) -> list[Order]:
        """Get historical orders for a trading account within a date range.

        Args:
            account_no: Trading account number.
            from_date: Start date in "YYYY/MM/DD" format.
            to_date: End date in "YYYY/MM/DD" format.
        Returns:
            The list of orders placed within the date range.
        Raises:
            ValidationError: If account_no, from_date, or to_date is empty.
        """
        require_non_empty(account_no, "accountNo")
        require_non_empty(from_date, "fromDate")
        require_non_empty(to_date, "toDate")
        return self._get_order_book(account_no, from_date=from_date, to_date=to_date).orders

    def _get_positions(
        self,
        client_id: str | None = None,
        account_no: str | None = None,
    ) -> Position:
        """Fetch the combined positions for the account."""
        params = _build_positions_params(client_id, account_no)
        data = self._rest.get(EP_POSITIONS, params=params)
        return Position.from_dict(data)

    def get_equity_positions(self, account_no: str) -> list[EquityPosition]:
        """Get equity positions for a trading account.

        Args:
            account_no: Trading account number.
        Returns:
            The list of equity positions.
        Raises:
            ValidationError: If account_no is empty.
        """
        require_non_empty(account_no, "accountNo")
        return self._get_positions(client_id=self._client_id, account_no=account_no).equity

    def get_derivative_positions(self, account_no: str) -> list[AllDerivativePosition]:
        """Get all derivative positions for a trading account.

        Args:
            account_no: Trading account number.
        Returns:
            The list of all derivative positions (open and closed).
        Raises:
            ValidationError: If account_no is empty.
        """
        require_non_empty(account_no, "accountNo")
        return self._get_positions(client_id=self._client_id, account_no=account_no).derivative

    def get_open_derivative_positions(self, account_no: str) -> list[DerivativePosition]:
        """Get open derivative positions for a trading account.

        Args:
            account_no: Trading account number.
        Returns:
            The list of open derivative positions.
        Raises:
            ValidationError: If account_no is empty.
        """
        require_non_empty(account_no, "accountNo")
        return self._get_positions(
            client_id=self._client_id, account_no=account_no
        ).derivative.open_positions

    def get_closed_derivative_positions(self, account_no: str) -> list[DerivativePosition]:
        """Get closed derivative positions for a trading account.

        Args:
            account_no: Trading account number.
        Returns:
            The list of closed derivative positions.
        Raises:
            ValidationError: If account_no is empty.
        """
        require_non_empty(account_no, "accountNo")
        return self._get_positions(
            client_id=self._client_id, account_no=account_no
        ).derivative.closed_positions

    def _get_ppmmr(self, account_no: str | None = None) -> PPMMR:
        """Fetch the combined PPMMR for the account."""
        params = _build_ppmmr_params(account_no)
        data = self._rest.get(EP_ACCOUNT_PPMMR, params=params)
        return PPMMR.from_dict(data)

    def get_equity_ppmmr(self, account_no: str) -> EquityPPMMR:
        """Get equity purchasing power and maintenance margin ratio for a trading account.

        Args:
            account_no: Trading account number.
        Returns:
            The equity purchasing power and maintenance margin ratio.
        Raises:
            ValidationError: If account_no is empty.
        """
        require_non_empty(account_no, "accountNo")
        return self._get_ppmmr(account_no=account_no).equity

    def get_derivative_ppmmr(self, account_no: str) -> DerivativePPMMR:
        """Get derivative purchasing power and maintenance margin ratio for a trading account.

        Args:
            account_no: Trading account number.
        Returns:
            The derivative purchasing power and maintenance margin ratio.
        Raises:
            ValidationError: If account_no is empty.
        """
        require_non_empty(account_no, "accountNo")
        return self._get_ppmmr(account_no=account_no).derivative
