"""Trading data models."""

from __future__ import annotations

import json
from dataclasses import dataclass

from ssi_sdk._version import __version__
from ssi_sdk.enums import OrderSide, OrderStatus, OrderType


@dataclass
class PlaceOrderRequest:
    """Payload for placing a new order."""

    account_no: str | None = None
    symbol: str | None = None
    side: OrderSide = OrderSide.BUY
    quantity: int | None = None
    price: float | None = None
    order_type: OrderType = OrderType.LO
    client_request_id: str | None = None
    device_id: str = "A1:B2:C3:D4:E5:F6"
    user_agent: str = "SSI Python SDK/" + __version__

    def to_dict(self) -> dict:
        """Build the camelCase API payload for placing the order.

        Returns:
            Dict with camelCase keys (accountNo, symbol, side, quantity, price,
            orderType, clientRequestId, deviceId, userAgent) for the place-order request.
        """
        result = {
            "accountNo": self.account_no,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "price": f"{self.price}",
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
    """Response for placing a new order."""

    order_id: str
    client_request_id: str
    status: OrderStatus

    @classmethod
    def from_dict(cls, data: dict) -> PlaceOrderResponse:
        """Build a PlaceOrderResponse from a camelCase API response dict.

        Args:
            data: API response dict with keys orderId, clientRequestId, orderStatus.
        Returns:
            A PlaceOrderResponse populated from data.
        Raises:
            ValueError: If orderStatus is not a valid OrderStatus value.
        """
        raw_status = data.get("orderStatus") or ""
        try:
            order_status = OrderStatus(raw_status)
        except ValueError:
            order_status = raw_status
        return cls(
            order_id=data.get("orderId", ""),
            client_request_id=data.get("clientRequestId", ""),
            status=order_status,
        )


@dataclass
class ModifyOrderRequest:
    """Modify order payload."""

    account_no: str | None = None
    quantity: int | None = None
    price: float | None = None
    order_id: str | None = None
    client_modify_id: str | None = None
    client_request_id: str | None = None
    device_id: str = "A1:B2:C3:D4:E5:F6"
    user_agent: str = "SSI Python SDK/" + __version__

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
            result["price"] = f"{self.price}"
        return result

    def to_str(self) -> str:
        """Serialize the modify-order payload to a JSON string.

        Returns:
            JSON string of the camelCase payload produced by to_dict.
        """
        return json.dumps(self.to_dict())


@dataclass
class ModifyOrderResponse:
    """Response for modifying an order."""

    client_modify_id: str
    order_id: str
    client_request_id: str
    status: OrderStatus

    @classmethod
    def from_dict(cls, data: dict) -> ModifyOrderResponse:
        """Build a ModifyOrderResponse from a camelCase API response dict.

        Args:
            data: API response dict with keys clientModifyId, orderId, clientRequestId,
                orderStatus.
        Returns:
            A ModifyOrderResponse populated from data.
        Raises:
            ValueError: If orderStatus is not a valid OrderStatus value.
        """
        raw_status = data.get("orderStatus") or ""
        try:
            order_status = OrderStatus(raw_status)
        except ValueError:
            order_status = raw_status
        return cls(
            client_modify_id=data.get("clientModifyId", ""),
            order_id=data.get("orderId", ""),
            client_request_id=data.get("clientRequestId", ""),
            status=order_status,
        )


@dataclass
class CancelOrderRequest:
    """Cancel order payload."""

    account_no: str | None = None
    order_id: str | None = None
    client_request_id: str | None = None
    client_cancel_id: str | None = None
    device_id: str = "A1:B2:C3:D4:E5:F6"
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
    """Response for canceling an order."""

    client_cancel_id: str
    order_id: str
    client_request_id: str
    status: OrderStatus

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
        raw_status = data.get("orderStatus") or ""
        try:
            order_status = OrderStatus(raw_status)
        except ValueError:
            order_status = raw_status
        return cls(
            client_cancel_id=data.get("clientCancelId", ""),
            order_id=data.get("orderId", ""),
            client_request_id=data.get("clientRequestId", ""),
            status=order_status,
        )


@dataclass
class MaxBuySellRequest:
    """Payload for max buy/sell request."""

    account_no: str | None = None
    symbol: str | None = None
    price: int | float = 0

    def to_dict(self) -> dict:
        """Build the camelCase API payload for the max buy/sell request.

        The symbol is upper-cased; price is included only when set.

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
            result["price"] = f"{self.price}"
        return result


@dataclass
class MaxBuySellResponse:
    """Response for max buy/sell request."""

    account_no: str
    symbol: str
    max_buy_quantity: int
    max_sell_quantity: int
    margin_ratio: str
    purchase_power: str

    @classmethod
    def from_dict(cls, data: dict, symbol: str) -> MaxBuySellResponse:
        """Build a MaxBuySellResponse from a camelCase API response dict.

        Args:
            data: API response dict with keys accountNo, maxBuyQty, maxSellQty,
                marginRatio, purchasePower.
            symbol: Ticker for the response; stored upper-cased.
        Returns:
            A MaxBuySellResponse populated from data and symbol.
        """
        return cls(
            account_no=data.get("accountNo", ""),
            symbol=symbol.upper(),
            max_buy_quantity=data.get("maxBuyQty", 0),
            max_sell_quantity=data.get("maxSellQty", 0),
            margin_ratio=data.get("marginRatio", ""),
            purchase_power=data.get("purchasePower", ""),
        )
