"""Account data models."""

from __future__ import annotations

from dataclasses import dataclass

from ssi_sdk.enums import AccountType


@dataclass
class Account:
    """Accessible trading account."""

    account_no: str = ""
    account_type: AccountType = AccountType.EQUITY

    @classmethod
    def from_list(cls, data: list[dict]) -> list[Account]:
        """Create a list of Account instances from a list of dictionaries.

        Args:
            data: API items with camelCase keys ``accountNo`` and ``accountType``.
        Returns:
            A list of Account instances, defaulting account_type to ``Cash`` when absent.
        """
        return [
            cls(
                account_no=item.get("accountNo", ""),
                account_type=AccountType(item.get("accountType", "Cash")),
            )
            for item in data
        ]
