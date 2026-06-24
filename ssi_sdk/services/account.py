"""Account service — async and sync."""

from __future__ import annotations

import logging

from ssi_sdk.constant import EP_ACCOUNT_INFO
from ssi_sdk.models.account import Account
from ssi_sdk.transport.rest_client import AsyncRestClient, RestClient

logger = logging.getLogger("ssi_sdk.services.account")


def _parse_accounts(data: list) -> list[Account]:
    """Convert a raw account list payload into Account objects."""
    return Account.from_list(data)


class AsyncAccountService:
    """Async account operations."""

    def __init__(self, rest_client: AsyncRestClient):
        """Initialize the async account service with a REST client."""
        self._rest = rest_client

    async def get_account_info(self) -> list[Account]:
        """Get the list of accessible trading accounts.

        Returns:
            The accessible trading accounts.
        Raises:
            APIError: If the request fails or the response is invalid.
        """
        data = await self._rest.get(EP_ACCOUNT_INFO)
        return _parse_accounts(data)


class AccountService:
    """Synchronous account operations."""

    def __init__(self, rest_client: RestClient):
        """Initialize the sync account service with a REST client."""
        self._rest = rest_client

    def get_account_info(self) -> list[Account]:
        """Get the list of accessible trading accounts.

        Returns:
            The accessible trading accounts.
        Raises:
            APIError: If the request fails or the response is invalid.
        """
        data = self._rest.get(EP_ACCOUNT_INFO)
        return _parse_accounts(data)
