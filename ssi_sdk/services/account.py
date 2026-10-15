"""Account service — async and sync."""

from __future__ import annotations

import logging

from ssi_sdk.constant import EP_ACCOUNT_INFO
from ssi_sdk.exceptions import APIError
from ssi_sdk.models.account import Account
from ssi_sdk.transport.rest_client import AsyncRestClient, RestClient
from ssi_sdk.utils.converter import is_no_content

logger = logging.getLogger("ssi_sdk.services.account")


def _parse_accounts(data: list | dict) -> list[Account]:
    """Convert a raw account list payload into Account objects.

    The server answers ``{"code": 204}`` instead of an empty array when there is nothing
    to list; that yields an empty list. Any other non-list body is an error.
    """
    if isinstance(data, list):
        return Account.from_list(data)
    if is_no_content(data):
        return []
    raise APIError("Unexpected response format while listing accounts", response_body=data)


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
