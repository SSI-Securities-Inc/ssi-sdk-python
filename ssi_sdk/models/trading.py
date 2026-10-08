"""Trading data models."""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TypedDict

from ssi_sdk._version import __version__
from ssi_sdk.enums import OrderSide, OrderStatus, OrderType
from ssi_sdk.exceptions import ValidationError
from ssi_sdk.utils.converter import (
    format_price,
    pick,
    to_int,
    to_opt_int,
    to_price_decimal,
)

# Order types that carry a real price; every other type is priced by the market.
_PRICED_ORDER_TYPES = (OrderType.LO, OrderType.PLO)

# Price as callers may pass it (a number, a ``Decimal`` or a decimal string). Held internally as
# Decimal so no float noise reaches the wire. Use this alias in your own signatures.
PriceLike = Decimal | int | float | str
Price = PriceLike  # historical internal name
# A numeric request field (trigger prices, trailing amounts, slips): sent as a JSON number.
NumberLike = Decimal | int | float


def _parse_status(raw: object) -> OrderStatus | str:
    """Parse an order status, keeping the raw string when this SDK does not know it."""
    return OrderStatus.from_value(raw) or (raw if isinstance(raw, str) else "") or ""


@dataclass
class PlaceOrderRequest:
    """Payload for placing a new order.

    Attributes:
        account_no: Trading account number.
        symbol: Ticker symbol.
        side: Order side: an ``OrderSide``, or the raw string for an unknown value.
        quantity: Order quantity (shares/contracts).
        price: Price in VND (a word such as ``"ATO"`` for market-priced orders).
        order_type: Order type: an ``OrderType`` member, or the raw string for an unknown
            type.
        client_request_id: Idempotency key chosen by the caller (<= 20 characters).
        device_id: Device identifier sent with the order (set by the SDK: this machine's id).
        user_agent: User-Agent sent with the order.
    """

    account_no: str | None = None
    symbol: str | None = None
    side: OrderSide = OrderSide.BUY
    quantity: int | None = None
    price: Price | None = None
    order_type: OrderType = OrderType.LO
    client_request_id: str | None = None
    device_id: str = ""
    user_agent: str = "SSI Python SDK/" + __version__

    def __post_init__(self) -> None:
        """Hold the price as Decimal."""
        self.price = to_price_decimal(self.price)

    def _price_text(self) -> str:
        """Price as a plain decimal string (never exponent notation, never ``"None"``).

        Raises:
            ValidationError: If a priced order type (LO/PLO) has no price.
        """
        if self.price is None:
            if self.order_type in _PRICED_ORDER_TYPES:
                raise ValidationError(f"price is required for {self.order_type.value} orders")
            # Market-priced types (ATO/ATC/MTL/MP/...) are sent with price 0, as before.
            return "0"
        return format_price(self.price)

    def to_dict(self) -> dict:
        """Build the camelCase API payload for placing the order.

        Returns:
            Dict with camelCase keys (accountNo, symbol, side, quantity, price,
            orderType, clientRequestId, deviceId, userAgent) for the place-order request.
            ``price`` is a string, ``quantity`` an integer.
        Raises:
            ValidationError: If a priced order type has no price.
        """
        result = {
            "accountNo": self.account_no,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "price": self._price_text(),
            "orderType": self.order_type.value,
            "clientRequestId": self.client_request_id,
            "deviceId": self.device_id,
            "userAgent": self.user_agent,
        }
        return result

    def to_str(self) -> str:
        """Serialize the place-order payload to a JSON string.

        Returns:
            JSON string of the camelCase payload produced by to_dict.
        """
        return json.dumps(self.to_dict())


@dataclass
class PlaceOrderResponse:
    """Response for placing a new order.

    Attributes:
        order_id: Server-assigned order id.
        client_request_id: Idempotency key chosen by the caller (<= 20 characters).
        status: Status: an enum member, or the raw string for a value this SDK does not
            know.
    """

    order_id: str
    client_request_id: str
    status: OrderStatus | str

    @classmethod
    def from_dict(cls, data: dict) -> PlaceOrderResponse:
        """Build a PlaceOrderResponse from a camelCase API response dict.

        Args:
            data: API response dict with keys orderId, clientRequestId, orderStatus.
        Returns:
            A PlaceOrderResponse populated from data. An unrecognized orderStatus is kept
            as the raw string rather than raising.
        """
        order_status = _parse_status(data.get("orderStatus"))
        return cls(
            order_id=data.get("orderId", ""),
            client_request_id=data.get("clientRequestId", ""),
            status=order_status,
        )


@dataclass
class ModifyOrderRequest:
    """Modify order payload.

    Attributes:
        account_no: Trading account number.
        quantity: Order quantity (shares/contracts).
        price: Price in VND (a word such as ``"ATO"`` for market-priced orders).
        order_id: Server-assigned order id.
        client_modify_id: Id of this modification request (generated by the SDK).
        client_request_id: Idempotency key chosen by the caller (<= 20 characters).
        device_id: Device identifier sent with the order (set by the SDK: this machine's id).
        user_agent: User-Agent sent with the order.
    """

    account_no: str | None = None
    quantity: int | None = None
    price: Price | None = None
    order_id: str | None = None
    client_modify_id: str | None = None
    client_request_id: str | None = None
    device_id: str = ""
    user_agent: str = "SSI Python SDK/" + __version__

    def __post_init__(self) -> None:
        """Hold the price as Decimal."""
        self.price = to_price_decimal(self.price)

    def to_dict(self) -> dict:
        """Build the camelCase API payload for modifying the order.

        Optional fields (orderId, clientRequestId, quantity, price) are included only
        when set.

        Returns:
            Dict with camelCase keys for the modify-order request.
        """
        result = {
            "accountNo": self.account_no,
            "clientModifyId": self.client_modify_id,
            "deviceId": self.device_id,
            "userAgent": self.user_agent,
        }
        if self.order_id is not None:
            result["orderId"] = self.order_id
        if self.client_request_id is not None:
            result["clientRequestId"] = self.client_request_id
        if self.quantity is not None:
            result["quantity"] = self.quantity
        if self.price is not None:
            result["price"] = format_price(self.price)
        return result

    def to_str(self) -> str:
        """Serialize the modify-order payload to a JSON string.

        Returns:
            JSON string of the camelCase payload produced by to_dict.
        """
        return json.dumps(self.to_dict())


@dataclass
class ModifyOrderResponse:
    """Response for modifying an order.

    Attributes:
        client_modify_id: Id of this modification request (generated by the SDK).
        order_id: Server-assigned order id.
        client_request_id: Idempotency key chosen by the caller (<= 20 characters).
        status: Status: an enum member, or the raw string for a value this SDK does not
            know.
    """

    client_modify_id: str
    order_id: str
    client_request_id: str
    status: OrderStatus | str

    @classmethod
    def from_dict(cls, data: dict) -> ModifyOrderResponse:
        """Build a ModifyOrderResponse from a camelCase API response dict.

        Args:
            data: API response dict with keys clientModifyId, orderId, clientRequestId,
                orderStatus.
        Returns:
            A ModifyOrderResponse populated from data.
            An unrecognized orderStatus is kept as the raw string rather than raising.
        """
        order_status = _parse_status(data.get("orderStatus"))
        return cls(
            client_modify_id=data.get("clientModifyId", ""),
            order_id=data.get("orderId", ""),
            client_request_id=data.get("clientRequestId", ""),
            status=order_status,
        )


@dataclass
class CancelOrderRequest:
    """Cancel order payload.

    Attributes:
        account_no: Trading account number.
        order_id: Server-assigned order id.
        client_request_id: Idempotency key chosen by the caller (<= 20 characters).
        client_cancel_id: Id of this cancel request (generated by the SDK).
        device_id: Device identifier sent with the order (set by the SDK: this machine's id).
        user_agent: User-Agent sent with the order.
    """

    account_no: str | None = None
    order_id: str | None = None
    client_request_id: str | None = None
    client_cancel_id: str | None = None
    device_id: str = ""
    user_agent: str = "SSI Python SDK/" + __version__

    def to_dict(self) -> dict:
        """Build the camelCase API payload for cancelling the order.

        Optional fields (orderId, clientRequestId) are included only when set.

        Returns:
            Dict with camelCase keys for the cancel-order request.
        """
        result = {
            "accountNo": self.account_no,
            "clientCancelId": self.client_cancel_id,
            "deviceId": self.device_id,
            "userAgent": self.user_agent,
        }
        if self.order_id is not None:
            result["orderId"] = self.order_id
        if self.client_request_id is not None:
            result["clientRequestId"] = self.client_request_id
        return result

    def to_str(self) -> str:
        """Serialize the cancel-order payload to a JSON string.

        Returns:
            JSON string of the camelCase payload produced by to_dict.
        """
        return json.dumps(self.to_dict())


@dataclass
class CancelOrderResponse:
    """Response for canceling an order.

    Attributes:
        client_cancel_id: Id of this cancel request (generated by the SDK).
        order_id: Server-assigned order id.
        client_request_id: Idempotency key chosen by the caller (<= 20 characters).
        status: Status: an enum member, or the raw string for a value this SDK does not
            know.
    """

    client_cancel_id: str
    order_id: str
    client_request_id: str
    status: OrderStatus | str

    @classmethod
    def from_dict(cls, data: dict) -> CancelOrderResponse:
        """Build a CancelOrderResponse from a camelCase API response dict.

        An unrecognized orderStatus is kept as the raw string rather than raising.

        Args:
            data: API response dict with keys clientCancelId, orderId, clientRequestId,
                orderStatus.
        Returns:
            A CancelOrderResponse populated from data.
        """
        order_status = _parse_status(data.get("orderStatus"))
        return cls(
            client_cancel_id=data.get("clientCancelId", ""),
            order_id=data.get("orderId", ""),
            client_request_id=data.get("clientRequestId", ""),
            status=order_status,
        )


@dataclass
class MaxBuySellRequest:
    """Payload for max buy/sell request.

    Attributes:
        account_no: Trading account number.
        symbol: Ticker symbol.
        price: Price in VND (a word such as ``"ATO"`` for market-priced orders).
    """

    account_no: str | None = None
    symbol: str | None = None
    price: Price | None = None

    def __post_init__(self) -> None:
        """Hold the price as Decimal."""
        self.price = to_price_decimal(self.price)

    def to_dict(self) -> dict:
        """Build the camelCase API payload for the max buy/sell request.

        The symbol is upper-cased; ``price`` is sent only when set (as a plain string).

        Returns:
            Dict with camelCase keys (accountNo, symbol, and optionally price).
        Raises:
            AttributeError: If symbol is None (has no upper method).
        """
        result = {
            "accountNo": self.account_no,
            "symbol": self.symbol.upper(),
        }
        if self.price is not None:
            result["price"] = format_price(self.price)
        return result


@dataclass
class MaxBuySellResponse:
    """Response for max buy/sell request.

    Derivative accounts get only the two quantities: ``purchasing_power`` and
    ``margin_ratio`` stay ``None`` there, which is not the same as 0.

    Attributes:
        account_no: Trading account number.
        symbol: Ticker symbol.
        max_buy_quantity: Maximum quantity that can be bought.
        max_sell_quantity: Maximum quantity that can be sold.
        margin_ratio: Margin ratio as the server's string; ``None`` on derivative accounts.
        purchasing_power: Purchasing power; ``None`` on derivative accounts.
    """

    account_no: str
    symbol: str
    max_buy_quantity: int
    max_sell_quantity: int
    margin_ratio: str | None = None
    purchasing_power: int | None = None

    @property
    def purchase_power(self) -> str:
        """Deprecated alias of ``purchasing_power`` (string, "" when absent)."""
        warnings.warn(
            "purchase_power is deprecated; use purchasing_power",
            DeprecationWarning,
            stacklevel=2,
        )
        return "" if self.purchasing_power is None else str(self.purchasing_power)

    @classmethod
    def from_dict(cls, data: dict, symbol: str) -> MaxBuySellResponse:
        """Build a MaxBuySellResponse from a camelCase API response dict.

        Args:
            data: API response dict with keys accountNo, maxBuyQty, maxSellQty and, for
                equity accounts, marginRatio and purchasingPower (``purchasePower`` is
                read as a fallback).
            symbol: Ticker for the response; stored upper-cased.
        Returns:
            A MaxBuySellResponse populated from data and symbol.
        """
        margin_ratio = data.get("marginRatio")
        return cls(
            account_no=data.get("accountNo", ""),
            symbol=symbol.upper(),
            max_buy_quantity=to_int(data.get("maxBuyQty")),
            max_sell_quantity=to_int(data.get("maxSellQty")),
            margin_ratio=None if margin_ratio in (None, "") else str(margin_ratio),
            purchasing_power=to_opt_int(pick(data, "purchasingPower", "purchasePower")),
        )


@dataclass
class BatchOrderRequest:
    """Body of ``POST``/``DELETE /api/v3/trading/order/batch`` (and the WebSocket batch params).

    ``batch_request_id`` must be unused today for this apiKey (a repeat is a 409) and
    ``batch_request_time`` must be *now* in epoch milliseconds (outside the server's replay
    window it is a 400111). The whole batch is validated first: one bad order rejects all.

    Attributes:
        batch_request_id: Batch id (a reused id is a 409).
        batch_request_time: Time of the batch request in epoch milliseconds.
        orders: The orders.
    """

    batch_request_id: str
    batch_request_time: int
    orders: list[dict]

    def to_dict(self) -> dict:
        """Build the camelCase API payload."""
        return {
            "batchRequestId": self.batch_request_id,
            "batchRequestTime": self.batch_request_time,
            "orders": self.orders,
        }

    def to_str(self) -> str:
        """Serialize to the JSON string that is signed and sent (sign exactly this text)."""
        return json.dumps(self.to_dict())


@dataclass
class BatchOrderResult:
    """Outcome of one order of a batch.

    Attributes:
        client_request_id: Idempotency key chosen by the caller (<= 20 characters).
        order_id: Server-assigned order id.
        status: Status: an enum member, or the raw string for a value this SDK does not
            know.
        success: Whether this item succeeded.
        error_code: Server error code when the order was rejected.
        error_message: Server error text when the order was rejected.
        client_cancel_id: Id of this cancel request (generated by the SDK).
    """

    client_request_id: str = ""
    order_id: str = ""
    status: OrderStatus | str = ""
    success: bool = False
    error_code: str = ""
    error_message: str = ""
    client_cancel_id: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> BatchOrderResult:
        """Build a result from one ``results[]`` item; every key is optional."""
        return cls(
            client_request_id=str(data.get("clientRequestId") or ""),
            order_id=str(data.get("orderId") or ""),
            status=_parse_status(data.get("orderStatus")),
            success=bool(data.get("success", False)),
            error_code=str(data.get("errorCode") or ""),
            error_message=str(data.get("errorMessage") or ""),
            client_cancel_id=str(data.get("clientCancelId") or ""),
        )


@dataclass
class BatchOrderResponse:
    """Response of a batch request: ``{"batchRequestId", "results": [...]}``.

    Attributes:
        batch_request_id: Batch id (a reused id is a 409).
        results: One result per order, in request order.
    """

    batch_request_id: str = ""
    results: list[BatchOrderResult] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> BatchOrderResponse:
        """Parse the response; a missing or non-list ``results`` is an empty list."""
        raw = data.get("results") if isinstance(data, dict) else None
        items = raw if isinstance(raw, list) else []
        return cls(
            batch_request_id=str((data or {}).get("batchRequestId") or ""),
            results=[BatchOrderResult.from_dict(item) for item in items if isinstance(item, dict)],
        )


class _PlaceItemRequired(TypedDict):
    account_no: str
    symbol: str
    side: OrderSide
    quantity: int
    price: PriceLike | None
    order_type: OrderType


class BatchPlaceOrderItem(_PlaceItemRequired, total=False):
    """One order of ``place_batch_orders`` (the same arguments as ``place_order``).

    ``price`` may be ``None`` for market-priced types (ATO/ATC/MP/...); ``client_request_id`` is
    your idempotency key (<= 20 characters) and is generated when omitted.
    """

    client_request_id: str


class _CancelItemRequired(TypedDict):
    account_no: str


class BatchCancelOrderItem(_CancelItemRequired, total=False):
    """One order of ``cancel_batch_orders``: ``account_no`` plus **exactly one** of the ids."""

    order_id: str
    client_request_id: str
