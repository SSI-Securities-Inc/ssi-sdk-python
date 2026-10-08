"""Account data models."""

from __future__ import annotations

from dataclasses import dataclass

from ssi_sdk.enums import AccountType


@dataclass
class Account:
    """Accessible trading account.

    Attributes:
        account_no: Trading account number.
        account_type: Account type: an ``AccountType``, the raw string for an unknown type,
            or ``None``.
    """

    account_no: str = ""
    account_type: AccountType | str | None = None

    @classmethod
    def from_list(cls, data: list[dict]) -> list[Account]:
        """Create a list of Account instances from a list of dictionaries.

        Args:
            data: API items with camelCase keys ``accountNo`` and ``accountType``.
        Returns:
            A list of Account instances. ``account_type`` is the matching ``AccountType``,
            the raw value when the server sends one this SDK does not know (e.g. ``"2"``),
            and ``None`` when the key is missing.
        """
        accounts = []
        for item in data:
            raw_type = item.get("accountType")
            accounts.append(
                cls(
                    account_no=item.get("accountNo", ""),
                    account_type=AccountType.from_value(raw_type) or raw_type,
                )
            )
        return accounts
