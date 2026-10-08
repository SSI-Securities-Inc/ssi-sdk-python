"""FCO data models."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any

from ssi_sdk._version import __version__
from ssi_sdk.enums import (
    FCOOperator,
    FCOStatus,
    FCOStatusLike,
    FCOType,
    FCOTypeLike,
    OrderSide,
    OrderStatus,
    OrderType,
)
from ssi_sdk.models.trading import NumberLike, PriceLike
from ssi_sdk.utils import (
    format_price,
    is_no_content,
    pick,
    to_enum,
    to_int,
    to_number,
    to_opt_float,
)

# The server's responses encode the trigger operator as a number; requests use the name.
_OPERATOR_BY_NUMBER = {
    0: FCOOperator.GREATER_OR_EQUAL,
    1: FCOOperator.EQUAL,
    2: FCOOperator.GREATER,
    3: FCOOperator.LESSER,
    4: FCOOperator.LESSER_OR_EQUAL,
}


def _parse_operator(raw: Any) -> FCOOperator | str | None:
    """Parse an operator given as a name or as the server's number 0..4 (raw if unknown)."""
    if raw is None or raw == "":
        return None
    if not isinstance(raw, bool):
        try:
            number = int(str(raw).strip())
        except ValueError:
            number = None
        if number in _OPERATOR_BY_NUMBER:
            return _OPERATOR_BY_NUMBER[number]
    return to_enum(FCOOperator, raw)


def parse_fco_common(data: dict) -> dict[str, Any]:
    """Fields every FCO payload carries (REST list/order book and stream events alike).

    One parser, so the REST models and the stream message cannot drift apart. camelCase is
    read first; the spec's casing is a fallback (server DTOs are camelCase).

    Returns:
        ``fco_id``, ``account_no``, ``symbol``, ``quantity``, ``matched_quantity``,
        ``is_place_order`` and ``type`` (enum member, raw string if unknown, or None).
    """
    return {
        "fco_id": str(pick(data, "fcoId", "FcoId", default="")),
        "account_no": str(pick(data, "accountNo", "AccountNo", default="")),
        "symbol": str(pick(data, "symbol", "Symbol", default="")),
        "quantity": to_int(pick(data, "quantity", "Quantity")),
        "matched_quantity": to_int(pick(data, "matchedQuantity", "matchedQuality")),
        "is_place_order": bool(pick(data, "isPlaceOrder", "IsPlaceOrder", default=False)),
        "type": to_enum(FCOType, data.get("type")),
    }


def _json_number(value: Any) -> Any:
    """``json.dumps`` hook: a ``Decimal`` goes out as a plain JSON number (int if whole)."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _price_and_slip(price: Any, slip: Any) -> tuple[str, Any]:
    """Return ``(price_text, slip)`` for an FCO price that may be a number or a word.

    A numeric price keeps its slip; an order-type word (``MP``/``MTL``/...) has no slip.
    """
    if isinstance(price, Enum):
        return str(price.value), 0
    if isinstance(price, str):
        return price, slip
    if isinstance(price, (int, float)) and not isinstance(price, bool):
        return format_price(price), slip
    return ("" if price is None else str(price)), 0


def _price_text(price: Any) -> str:
    """Price text for a take-profit/stop-loss leg (number formatted plainly, or the word)."""
    return _price_and_slip(price, 0)[0]

@dataclass
class FCOListRequest:
    """Request parameters for querying the FCO list.

    Attributes:
        account_no: Trading account number.
        fco_id: Id of the conditional order.
        type: Message/FCO type.
        process_status: Processing status of the conditional order.
        symbol: Ticker symbol.
        side: Order side: an ``OrderSide``, or the raw string for an unknown value.
        from_date: Start of the range/window.
        to_date: End of the range/window.
        page_index: 1-based page number.
        page_size: Rows per page.
    """

    account_no: str
    fco_id: str | None = None
    type: FCOTypeLike | None = None
    process_status: FCOStatusLike | list[FCOStatusLike] | None = None
    symbol: str | None = None
    side: OrderSide | str | None = None
    from_date: str | None = None
    to_date: str | None = None
    page_index: int | None = 1
    page_size: int | None = 10
    extra_params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert request parameters to camelCase API query dict."""
        params = {
            "accountNo": self.account_no,
        }
        if self.fco_id is not None:
            params["fcoId"] = self.fco_id
        if self.type is not None:
            type_enum = FCOType.from_value(self.type)
            params["type"] = type_enum.value if type_enum else self.type
        if self.process_status is not None:
            if isinstance(self.process_status, (list, tuple)):
                # Several statuses go out as a repeated ``processStatus`` query key.
                params["processStatus"] = [
                    getattr(FCOStatus.from_value(item), "value", item)
                    for item in self.process_status
                ]
            else:
                status_enum = FCOStatus.from_value(self.process_status)
                params["processStatus"] = (
                    status_enum.value if status_enum else self.process_status
                )
        if self.symbol is not None:
            params["symbol"] = self.symbol
        if self.side is not None:
            side_enum = OrderSide.from_value(self.side)
            params["side"] = side_enum.value if side_enum else self.side
        if self.from_date is not None:
            params["from"] = self.from_date
        if self.to_date is not None:
            params["to"] = self.to_date
        if self.page_index is not None:
            params["pageIndex"] = self.page_index
        if self.page_size is not None:
            params["pageSize"] = self.page_size

        if self.extra_params:
            params.update(self.extra_params)
        return params


@dataclass
class FCOParams:
    """Detailed trigger parameters of an FCO order."""

    stop_price: float | None = None
    side: OrderSide | None = None
    active_price: float | None = None
    trailing_amount: float | None = None
    tp_active_price: float | None = None
    sl_active_price: float | None = None
    tp_price: str | None = None
    sl_price: str | None = None
    tp_slip: float | None = None
    sl_slip: float | None = None
    operator: FCOOperator | str | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> FCOParams | None:
        """Create FCOParams from a dictionary.

        ``operator`` may be a name or the server's number 0..4 (0 greater-or-equal,
        1 equal, 2 greater, 3 lesser, 4 lesser-or-equal); an unknown one stays raw.
        """
        if not data:
            return None

        return cls(
            stop_price=to_number(data.get("stopPrice")) if data.get("stopPrice") is not None else None,
            side=OrderSide.from_value(data.get("side")) if data.get("side") is not None else None,
            active_price=to_number(data.get("activePrice")) if data.get("activePrice") is not None else None,
            trailing_amount=to_number(data.get("trailingAmount")) if data.get("trailingAmount") is not None else None,
            tp_active_price=to_number(data.get("tpActivePrice")) if data.get("tpActivePrice") is not None else None,
            sl_active_price=to_number(data.get("slActivePrice")) if data.get("slActivePrice") is not None else None,
            tp_price=data.get("tpPrice"),
            sl_price=data.get("slPrice"),
            tp_slip=to_number(data.get("tpSlip")) if data.get("tpSlip") is not None else None,
            sl_slip=to_number(data.get("slSlip")) if data.get("slSlip") is not None else None,
            operator=_parse_operator(pick(data, "operator", "price_operator")),
        )

    def __repr__(self) -> str:
        fields = []
        for key, val in self.__dict__.items():
            if val is not None and val != "":
                fields.append(f"{key}={repr(val)}")
        return f"FCOParams({', '.join(fields)})"

    def to_dict(self) -> dict:
        """Convert to dict, omitting only unset (None) and empty-string values.

        A legitimate ``0`` (for example a zero slip) is kept.
        """
        res = {}
        for key, val in self.__dict__.items():
            if val is not None and val != "":
                if isinstance(val, Enum):
                    res[key] = val.value
                else:
                    res[key] = val
        return res


@dataclass
class FCOInfo:
    """A conditional order item in the FCO order book / list.

    Attributes:
        fco_id: Id of the conditional order.
        account_no: Trading account number.
        quantity: Order quantity (shares/contracts).
        price: Price in VND (a word such as ``"ATO"`` for market-priced orders).
        symbol: Ticker symbol.
        type: Message/FCO type.
        from_date: Start of the range/window.
        to_date: End of the range/window.
        matched_quantity: Quantity matched so far.
        is_place_order: Whether the conditional order has already placed its order.
        status: Status: an enum member, or the raw string for a value this SDK does not
            know.
        detail: Free-text detail from the server.
        order_type: Order type: an ``OrderType`` member, or the raw string for an unknown
            type.
    """

    fco_id: str = ""
    client_id: str = ""
    account_no: str = ""
    quantity: int = 0
    price: str = ""
    price_slip: float | None = None
    symbol: str = ""
    type: FCOType | str | None = None
    from_date: str = ""
    to_date: str = ""
    matched_quantity: int = 0
    is_place_order: bool = False
    status: FCOStatus | str | None = None
    detail: str = ""
    params: FCOParams | None = None
    order_type: OrderType | str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> FCOInfo:
        """Build an FCOInfo from a camelCase API response dict."""
        params_dict = pick(data, "params", "fco_params", "fcoParams")
        params = FCOParams.from_dict(params_dict) if params_dict else None
        common = parse_fco_common(data)
        return cls(
            fco_id=common["fco_id"],
            client_id=str(pick(data, "username", "Username", default="")),
            account_no=common["account_no"],
            quantity=common["quantity"],
            price=str(data.get("price") if data.get("price") is not None else ""),
            price_slip=to_opt_float(data.get("priceSlip")),
            symbol=common["symbol"],
            type=common["type"],
            from_date=str(data.get("from", "")),
            to_date=str(data.get("to", "")),
            matched_quantity=common["matched_quantity"],
            is_place_order=common["is_place_order"],
            status=to_enum(FCOStatus, data.get("status")),
            detail=str(data.get("detail", "")),
            params=params,
            order_type=to_enum(OrderType, data.get("orderType")),
        )

    @classmethod
    def from_list(cls, data: list) -> list[FCOInfo]:
        """Convert a list of raw dicts into FCOInfo objects."""
        return [cls.from_dict(item) for item in data]


@dataclass
class FCOListResponse:
    """Paginated response containing list of FCO orders.

    Attributes:
        page_index: 1-based page number.
        page_size: Rows per page.
        items_count: Total items.
        pages_count: Total pages as the server computes it (can miss the last partial page).
    """

    page_index: int = 1
    page_size: int = 10
    items_count: int = 0
    pages_count: int = 0
    fco_list: list[FCOInfo] = field(default_factory=list)

    def __iter__(self):
        return iter(self.fco_list)

    def __getitem__(self, index):
        return self.fco_list[index]

    def __len__(self):
        return len(self.fco_list)

    @classmethod
    def from_dict(cls, data: dict | list) -> FCOListResponse:
        """Create an FCOListResponse from API dict or list response."""
        if isinstance(data, list):
            fco_list_raw = data
            data_dict = {}
        else:
            data_dict = {} if is_no_content(data) else data or {}
            fco_list_raw = pick(data_dict, "data", "fcoList", "fco_list") or []

        return cls(
            page_index=to_int(data_dict.get("pageIndex"), 1),
            page_size=to_int(data_dict.get("pageSize"), 10),
            items_count=to_int(data_dict.get("itemsCount"), 0),
            pages_count=to_int(pick(data_dict, "pagesCount", "pageCount"), 0),
            fco_list=FCOInfo.from_list(fco_list_raw),
        )


@dataclass
class FCOOrderBookRequest:
    fco_id: str
    page_index: int = 1
    page_size: int = 10

    def to_dict(self) -> dict:
        """Convert request parameters to camelCase API query dict."""
        params = {
            "fcoId": self.fco_id
        }
        if self.page_index is not None:
            params["pageIndex"] = self.page_index
        if self.page_size is not None:
            params["pageSize"] = self.page_size

        return params


@dataclass
class FCOOrder:
    """An entry in the FCO order book / execution log representing an FCO order.

    Attributes:
        fco_id: Id of the conditional order.
        account_no: Trading account number.
        quantity: Order quantity (shares/contracts).
        price: Price in VND (a word such as ``"ATO"`` for market-priced orders).
        symbol: Ticker symbol.
        side: Order side: an ``OrderSide``, or the raw string for an unknown value.
        order_type: Order type: an ``OrderType`` member, or the raw string for an unknown
            type.
        updated_time: When the entry was last updated.
        unique_id: Server id of this entry.
        order_id: Server-assigned order id.
        matched_quantity: Quantity matched so far.
        os_quantity: Outstanding quantity. The REST order book never sends it, so it is
            ``None`` there.
        avg_price: Average matched price.
        status: Status: an enum member, or the raw string for a value this SDK does not
            know.
        detail: Free-text detail from the server.
        type: Message/FCO type.
    """

    fco_id: str = ""
    account_no: str = ""
    quantity: int = 0
    price: str = ""
    symbol: str = ""
    side: OrderSide | str | None = None
    order_type: OrderType | str | None = None
    is_main_order: bool = False
    is_attached_order: bool = False
    created_time: str = ""
    updated_time: str = ""
    unique_id: str = ""
    order_id: str = ""
    matched_quantity: int = 0
    os_quantity: int = 0
    avg_price: float = 0.0
    status: OrderStatus | str | None = None
    detail: str = ""
    type: FCOType | str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> FCOOrder:
        """Create FCOOrder from a dictionary."""
        common = parse_fco_common(data)
        return cls(
            fco_id=common["fco_id"],
            account_no=common["account_no"],
            quantity=common["quantity"],
            price=str(data.get("price") if data.get("price") is not None else ""),
            symbol=common["symbol"],
            side=to_enum(OrderSide, data.get("side")),
            order_type=to_enum(OrderType, data.get("orderType")),
            is_main_order=bool(pick(data, "isMainOrder", "IsMainOrder", default=False)),
            is_attached_order=bool(data.get("isAttachedOrder", False)),
            created_time=str(data.get("createdTime", "")),
            updated_time=str(data.get("updatedTime", "")),
            unique_id=str(pick(data, "uniqueId", "uniquedId", "UniqueId", default="")),
            order_id=str(data.get("orderId", "")),
            matched_quantity=common["matched_quantity"],
            os_quantity=to_int(data.get("osQuantity")),
            avg_price=to_number(data.get("avgPrice"), 0.0),
            status=to_enum(OrderStatus, data.get("status")),
            detail=str(data.get("detail", "")),
            type=common["type"],
        )

    @classmethod
    def from_list(cls, data: list) -> list[FCOOrder]:
        """Convert a list of raw dicts into FCOOrder objects."""
        return [cls.from_dict(item) for item in data]


@dataclass
class FCOOrderBookResponse:
    """Paginated response containing list of FCO order book entries.

    The server computes the page count with integer division, so the last partial page can
    be missing from ``pages_count``: page until a page comes back empty, or use
    ``items_count``.

    Attributes:
        page_index: 1-based page number.
        page_size: Rows per page.
        items_count: Total items.
        pages_count: Total pages as the server computes it (can miss the last partial page).
    """

    page_index: int = 1
    page_size: int = 10
    items_count: int = 0
    pages_count: int = 0
    order_book: list[FCOOrder] = field(default_factory=list)

    def __iter__(self):
        return iter(self.order_book)

    def __getitem__(self, index):
        return self.order_book[index]

    def __len__(self):
        return len(self.order_book)

    @classmethod
    def from_dict(cls, data: dict | list) -> FCOOrderBookResponse:
        """Create an FCOOrderBookResponse from API dict or list response."""
        if isinstance(data, list):
            order_book_raw = data
            data_dict = {}
        else:
            data_dict = {} if is_no_content(data) else data or {}
            order_book_raw = pick(data_dict, "data", "orderBook", "order_book") or []

        return cls(
            page_index=to_int(data_dict.get("pageIndex"), 1),
            page_size=to_int(data_dict.get("pageSize"), 10),
            items_count=to_int(data_dict.get("itemsCount"), 0),
            pages_count=to_int(pick(data_dict, "pagesCount", "pageCount"), 0),
            order_book=FCOOrder.from_list(order_book_raw),
        )


@dataclass
class GTDParams:
    account_no: str
    symbol: str | None = None
    side: OrderSide | None = None
    price: PriceLike | OrderType | None = None
    price_slip: NumberLike = 0
    quantity: int | None = None
    from_date: str | None = None
    to_date: str | None = None

    device_id: str = ""
    user_agent: str = "SSI Python SDK/" + __version__
    code: str | None = None

    def to_dict(self) -> dict:
        """Convert request parameters to camelCase API query dict."""
        price, price_slip = _price_and_slip(self.price, self.price_slip)
        payload = {
            "accountNo": self.account_no,
            "type": FCOType.GTD.value,
            "symbol": self.symbol,
            "side": self.side.value,
            "price": price,
            "priceSlip": price_slip,
            "quantity": self.quantity,
            "from": self.from_date,
            "to": self.to_date,
            "deviceId": self.device_id,
            "userAgent": self.user_agent,
        }
        if self.code:
            payload["code"] = self.code
        return payload

    @classmethod
    def from_dict(cls, data: dict) -> GTDParams:
        """Convert a camelCase API dict into a GTDParams object."""
        return cls(
            account_no=data.get("accountNo"),
            symbol=data.get("symbol"),
            side=OrderSide.from_value(data.get("side")),
            price=data.get("price"),
            price_slip=data.get("priceSlip") or 0,
            quantity=data.get("quantity"),
            from_date=data.get("from"),
            to_date=data.get("to"),
        )

    def to_str(self) -> str:
        """Serialize the payload to the JSON string that is signed and sent.

        Returns:
            JSON string of the camelCase payload produced by to_dict.
        """
        return json.dumps(self.to_dict(), default=_json_number)


@dataclass
class StopParams:
    account_no: str
    symbol: str
    side: OrderSide
    stop_price: NumberLike
    operator: FCOOperator  # e.g. GREATER_OR_EQUAL / LESSER_OR_EQUAL
    quantity: int
    from_date: str | None = None
    to_date: str | None = None
    price: PriceLike | OrderType = 0
    price_slip: NumberLike = 0
    fco_type: FCOType = FCOType.STOP
    device_id: str = ""
    user_agent: str = "SSI Python SDK/" + __version__
    code: str | None = None

    def to_dict(self) -> dict:
        """Convert request parameters to camelCase API query dict."""
        if self.fco_type == FCOType.STOP:
            price = OrderType.MTL.value
            price_slip = 0
        else:
            price = _price_text(self.price)
            price_slip = self.price_slip
        payload = {
            "accountNo": self.account_no,
            "type": self.fco_type.value,
            "symbol": self.symbol,
            "side": self.side.value,
            "price": price,
            "priceSlip": price_slip,
            "quantity": self.quantity,
            "from": self.from_date,
            "to": self.to_date,
            "stopPrice": self.stop_price,
            "operator": self.operator.value,
            "deviceId": self.device_id,
            "userAgent": self.user_agent,
        }
        if self.code:
            payload["code"] = self.code
        return payload

    def to_str(self) -> str:
        """Serialize the payload to the JSON string that is signed and sent.

        Returns:
            JSON string of the camelCase payload produced by to_dict.
        """
        return json.dumps(self.to_dict(), default=_json_number)


@dataclass
class TrailingStopParams:
    account_no: str
    symbol: str
    side: OrderSide
    quantity: int
    active_price: NumberLike
    trailing_amount: NumberLike
    price_slip: NumberLike = 0
    from_date: str | None = None
    to_date: str | None = None
    fco_type: FCOType = FCOType.TRAILING_STOP
    device_id: str = ""
    user_agent: str = "SSI Python SDK/" + __version__
    code: str | None = None

    def to_dict(self) -> dict:
        """Convert request parameters to camelCase API query dict."""
        params = {
            "accountNo": self.account_no,
            "type": self.fco_type.value,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "from": self.from_date,
            "to": self.to_date,
            "activePrice": self.active_price,
            "trailingAmount": self.trailing_amount,
            "userAgent": self.user_agent,
            "deviceId": self.device_id
        }
        if self.fco_type == FCOType.TRAILING_STOP:
            params["price"] = OrderType.MTL.value
            params["priceSlip"] = 0
        else:
            params["priceSlip"] = self.price_slip
        if self.code:
            params["code"] = self.code
        return params

    def to_str(self) -> str:
        """Serialize the payload to the JSON string that is signed and sent.

        Returns:
            JSON string of the camelCase payload produced by to_dict.
        """
        return json.dumps(self.to_dict(), default=_json_number)


@dataclass
class OCOParams:
    account_no: str
    symbol: str
    quantity: int

    side: OrderSide
    tp_active_price: NumberLike
    sl_active_price: NumberLike
    tp_price: PriceLike | OrderType
    sl_price: PriceLike | OrderType
    tp_slip: NumberLike
    sl_slip: NumberLike

    from_date: str | None = None
    to_date: str | None = None
    fco_type: FCOType = FCOType.OCO
    device_id: str = ""
    user_agent: str = "SSI Python SDK/" + __version__
    code: str | None = None

    def to_dict(self) -> dict:
        """Convert request parameters to camelCase API query dict."""
        tp_price_str = _price_text(self.tp_price)
        sl_price_str = _price_text(self.sl_price)

        params = {
            "accountNo": self.account_no,
            "type": self.fco_type.value,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "from": self.from_date,
            "to": self.to_date,
            "tpActivePrice": self.tp_active_price,
            "slActivePrice": self.sl_active_price,
            "tpPrice": tp_price_str,
            "slPrice": sl_price_str,
            "tpSlip": self.tp_slip,
            "slSlip": self.sl_slip,
            "userAgent": self.user_agent,
            "deviceId": self.device_id,

            # TODO: remove hard code
            "price": "MP",
            "priceSlip": 0,
            "stopPrice": 0,
            "activePrice": 0,
            "trailingAmount": 0,
            "operator": "",
            "code": self.code or "",
        }
        return params

    def to_str(self) -> str:
        """Serialize the payload to the JSON string that is signed and sent.

        Returns:
            JSON string of the camelCase payload produced by to_dict.
        """
        return json.dumps(self.to_dict(), default=_json_number)


@dataclass
class BullBearParams:
    account_no: str
    symbol: str
    quantity: int

    side: OrderSide
    price: PriceLike | OrderType
    price_slip: NumberLike
    tp_active_price: NumberLike
    sl_active_price: NumberLike
    tp_price: PriceLike | OrderType
    sl_price: PriceLike | OrderType
    tp_slip: NumberLike
    sl_slip: NumberLike

    from_date: str | None = None
    to_date: str | None = None
    fco_type: FCOType = FCOType.BULL_BEAR
    device_id: str = ""
    user_agent: str = "SSI Python SDK/" + __version__
    code: str | None = None

    def to_dict(self) -> dict:
        """Convert request parameters to camelCase API query dict."""
        price, price_slip = _price_and_slip(self.price, self.price_slip)
        tp_price_str, tp_slip = _price_and_slip(self.tp_price, self.tp_slip)
        sl_price_str, sl_slip = _price_and_slip(self.sl_price, self.sl_slip)

        params = {
            "accountNo": self.account_no,
            "type": self.fco_type.value,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "price": price,
            "priceSlip": price_slip,
            "from": self.from_date,
            "to": self.to_date,
            "tpActivePrice": self.tp_active_price,
            "slActivePrice": self.sl_active_price,
            "tpPrice": tp_price_str,
            "slPrice": sl_price_str,
            "tpSlip": tp_slip,
            "slSlip": sl_slip,
            "userAgent": self.user_agent,
            "deviceId": self.device_id,
        }
        if self.code:
            params["code"] = self.code
        return params

    def to_str(self) -> str:
        """Serialize the payload to the JSON string that is signed and sent.

        Returns:
            JSON string of the camelCase payload produced by to_dict.
        """
        return json.dumps(self.to_dict(), default=_json_number)


@dataclass
class FCOPlaceResponse:
    """Response to placing an FCO."""

    fco_id: str

    @classmethod
    def from_dict(cls, data: dict) -> FCOPlaceResponse:
        """Create FCOPlaceResponse from a dictionary."""
        return cls(
            fco_id=str(data.get("fcoId", "")),
        )


@dataclass
class FCOCancelRequest:
    """Payload for cancelling an FCO.

    ``device_id`` is required by the server (the service fills it from ``Config``); the
    server records its own IP, so no ``ipAddress`` is sent.

    Attributes:
        fco_id: Id of the conditional order.
        device_id: Device identifier sent with the order (set by the SDK: this machine's id).
        user_agent: User-Agent sent with the order.
        code: One-time code (OTP) when the account requires it for the command; omitted if empty.
    """

    fco_id: str
    device_id: str = ""
    user_agent: str | None = None
    code: str | None = None

    def to_dict(self) -> dict:
        """Build the camelCase API payload (``userAgent`` only when set)."""
        payload = {
            "fcoId": self.fco_id,
            "deviceId": self.device_id,
        }
        if self.user_agent:
            payload["userAgent"] = self.user_agent
        if self.code:
            payload["code"] = self.code
        return payload

    def to_str(self) -> str:
        """Serialize the payload to the JSON string that is signed and sent.

        Returns:
            JSON string of the camelCase payload produced by to_dict.
        """
        return json.dumps(self.to_dict(), default=_json_number)


@dataclass
class FCOCancelResponse:
    """Response to cancelling an FCO."""

    fco_id: str

    @classmethod
    def from_dict(cls, data: dict) -> FCOCancelResponse:
        """Create FCOCancelResponse from a dictionary."""
        return cls(
            fco_id=str(data.get("fcoId", "")),
        )


@dataclass
class FCOStatusHistoryRequest:
    """Query for the status history of one FCO."""

    fco_id: str

    def to_dict(self) -> dict:
        """Build the query parameters (the server binds ``fcoid`` case-insensitively)."""
        return {"fcoid": self.fco_id}


@dataclass
class FCOStatusHistoryItem:
    """One status transition of an FCO.

    Attributes:
        state: State name.
        time: When the state was entered.
        code: Status code, if any.
        detail: Free-text detail from the server.
    """

    state: str = ""
    time: str = ""
    code: str | None = None
    detail: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> FCOStatusHistoryItem:
        """Create an item from a ``{state, time, code, detail}`` dict."""
        code = data.get("code")
        return cls(
            state=str(data.get("state") or ""),
            time=str(data.get("time") or ""),
            code=None if code in (None, "") else str(code),
            detail=str(data.get("detail") or ""),
        )

    @classmethod
    def from_response(cls, data: dict | list) -> list[FCOStatusHistoryItem]:
        """Parse the ``statusHistory`` response: ``{"data": [...]}`` or the server's 204 marker."""
        if isinstance(data, dict):
            if is_no_content(data):
                return []
            data = data.get("data") or []
        return [cls.from_dict(item) for item in data if isinstance(item, dict)]
