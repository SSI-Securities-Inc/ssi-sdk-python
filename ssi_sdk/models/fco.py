"""FCO data models."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ssi_sdk._version import __version__
from ssi_sdk.utils import to_float, to_int, to_number
from ssi_sdk.enums import FCOType, FCOOperator, FCOStatus, OrderSide, OrderStatus, OrderType

@dataclass
class FCOListRequest:
    """Request parameters for querying the FCO list."""

    account_no: str
    fco_id: str | None = None
    type: FCOType | None = None
    process_status: FCOStatus | None = None
    symbol: str | None = None
    side: OrderSide | None = None
    from_date: str | None = None
    to_date: str | None = None
    page_index: int = 1
    page_size: int = 10
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
            status_enum = FCOStatus.from_value(self.process_status)
            params["processStatus"] = status_enum.value if status_enum else self.process_status
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
    operator: FCOOperator | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> FCOParams | None:
        """Create FCOParams from a dictionary."""
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
            operator=FCOOperator.from_value(data.get("operator")) if data.get("operator") is not None else None,
        )

    def __repr__(self) -> str:
        fields = []
        for key, val in self.__dict__.items():
            if val is not None and val != 0 and val != 0.0 and val != "":
                fields.append(f"{key}={repr(val)}")
        return f"FCOParams({', '.join(fields)})"

    def to_dict(self) -> dict:
        """Convert to dict, omitting None, 0, 0.0, and empty values."""
        res = {}
        for key, val in self.__dict__.items():
            if val is not None and val != 0 and val != 0.0 and val != "":
                if isinstance(val, Enum):
                    res[key] = val.value
                else:
                    res[key] = val
        return res


@dataclass
class FCOInfo:
    """A conditional order item in the FCO order book / list."""

    fco_id: str = ""
    client_id: str = ""
    account_no: str = ""
    quantity: int = 0
    price: str = ""
    price_slip: str = ""
    symbol: str = ""
    type: FCOType | None = None
    from_date: str = ""
    to_date: str = ""
    matched_quantity: int = 0
    is_place_order: bool = False
    status: FCOStatus | None = None
    detail: str = ""
    params: FCOParams | None = None

    @classmethod
    def from_dict(cls, data: dict) -> FCOInfo:
        """Build an FCOInfo from a camelCase API response dict."""
        params_dict = data.get("params") or data.get("fco_params") or data.get("fcoParams")
        params = FCOParams.from_dict(params_dict) if params_dict else None
        return cls(
            fco_id=str(data.get("fcoId", "")),
            client_id=str(data.get("username", "")),
            account_no=str(data.get("accountNo", "")),
            quantity=to_int(data.get("quantity"), 0),
            price=str(data.get("price") if data.get("price") is not None else ""),
            price_slip=str(data.get("priceSlip") if data.get("priceSlip") is not None else ""),
            symbol=str(data.get("symbol", "")),
            type=FCOType.from_value(data.get("type")),
            from_date=str(data.get("from", "")),
            to_date=str(data.get("to", "")),
            matched_quantity=to_int(data.get("matchedQuantity"), 0),
            is_place_order=bool(data.get("isPlaceOrder", False)),
            status=FCOStatus.from_value(data.get("status")) if data.get("status") is not None else None,
            detail=str(data.get("detail", "")),
            params=params
        )

    @classmethod
    def from_list(cls, data: list) -> list[FCOInfo]:
        """Convert a list of raw dicts into FCOInfo objects."""
        return [cls.from_dict(item) for item in data]


@dataclass
class FCOListResponse:
    """Paginated response containing list of FCO orders."""

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
            data_dict = data or {}
            fco_list_raw = data_dict.get("data") or data_dict.get("fcoList") or data_dict.get("fco_list") or []

        return cls(
            page_index=to_int(data_dict.get("pageIndex"), 1),
            page_size=to_int(data_dict.get("pageSize"), 10),
            items_count=to_int(data_dict.get("itemsCount"), 0),
            pages_count=to_int(data_dict.get("pagesCount"), 0),
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
    """An entry in the FCO order book / execution log representing an FCO order."""

    fco_id: str = ""
    account_no: str = ""
    quantity: float = 0.0
    price: str = ""
    symbol: str = ""
    side: OrderSide | None = None
    order_type: OrderType | None = None
    is_main_order: bool = False
    is_attached_order: bool = False
    created_time: str = ""
    updated_time: str = ""
    unique_id: str = ""
    order_id: str = ""
    matched_quantity: float = 0.0
    os_quantity: float = 0.0
    avg_price: float = 0.0
    status: OrderStatus | None = None
    detail: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> FCOOrder:
        """Create FCOOrder from a dictionary."""
        return cls(
            fco_id=str(data.get("fcoId", "")),
            account_no=str(data.get("accountNo", "")),
            quantity=to_number(data.get("quantity"), 0.0),
            price=str(data.get("price") if data.get("price") is not None else ""),
            symbol=str(data.get("symbol", "")),
            side=OrderSide.from_value(data.get("side")) if data.get("side") is not None else None,
            order_type=OrderType.from_value(data.get("orderType")) if data.get("orderType") is not None else None,
            is_main_order=bool(data.get("isMainOrder", False)),
            is_attached_order=bool(data.get("isAttachedOrder", False)),
            created_time=str(data.get("createdTime", "")),
            updated_time=str(data.get("updatedTime", "")),
            unique_id=str(data.get("uniqueId", "")),
            order_id=str(data.get("orderId", "")),
            matched_quantity=to_number(data.get("matchedQuantity"), 0.0),
            os_quantity=to_number(data.get("osQuantity"), 0.0),
            avg_price=to_number(data.get("avgPrice"), 0.0),
            status=OrderStatus.from_value(data.get("status")) if data.get("status") is not None else None,
            detail=str(data.get("detail", "")),
        )

    @classmethod
    def from_list(cls, data: list) -> list[FCOOrder]:
        """Convert a list of raw dicts into FCOOrder objects."""
        return [cls.from_dict(item) for item in data]


@dataclass
class FCOOrderBookResponse:
    """Paginated response containing list of FCO order book entries."""

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
            data_dict = data or {}
            order_book_raw = data_dict.get("data") or data_dict.get("orderBook") or data_dict.get("order_book") or []

        return cls(
            page_index=to_int(data_dict.get("pageIndex"), 1),
            page_size=to_int(data_dict.get("pageSize"), 10),
            items_count=to_int(data_dict.get("itemsCount"), 0),
            pages_count=to_int(data_dict.get("pagesCount"), 0),
            order_book=FCOOrder.from_list(order_book_raw),
        )


@dataclass
class GTDParams:
    account_no: str
    symbol: str | None = None
    side: OrderSide | None = None
    price: int | float | OrderType | None = None
    price_slip: int | float = 0
    quantity: int | None = None
    from_date: str | None = None
    to_date: str | None = None

    device_id: str = "A1:B2:C3:D4:E5:F6"
    user_agent: str = "SSI Python SDK/" + __version__

    def to_dict(self) -> dict:
        """Convert request parameters to camelCase API query dict."""
        if isinstance(self.price, (int, float)):
            price = f"{self.price}"
            price_slip = self.price_slip
        elif isinstance(self.price, str):
            price = self.price
            price_slip = self.price_slip
        elif hasattr(self.price, "value"):
            price = self.price.value
            price_slip = 0
        else:
            price = str(self.price) if self.price is not None else ""
            price_slip = 0
        return {
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
            "userAgent": self.user_agent
        }

    @classmethod
    def from_dict(cls, data: dict) -> GTDParams:
        """Convert a camelCase API dict into a GTDParams object."""
        return cls(
            account_no=data.get("accountNo"),
            symbol=data.get("symbol"),
            side=OrderSide.from_value(data.get("fco_params", {}).get("side")),
            price=data.get("price"),
            price_slip=data.get("priceSlip"),
            quantity=data.get("quantity"),
            from_date=data.get("from"),
            to_date=data.get("to"),
        )

    def to_str(self) -> str:
        """Serialize the place-order payload to a JSON string.

        Returns:
            JSON string of the camelCase payload produced by to_dict.
        """
        return json.dumps(self.to_dict())


@dataclass
class StopParams:
    account_no: str
    symbol: str
    side: OrderSide
    stop_price: int 
    operator: FCOOperator # greater_than_or_equal, smaller_than_or_equal
    quantity: int
    from_date: str | None = None
    to_date: str | None = None
    price: int | float = 0
    price_slip: int | float = 0
    fco_type: FCOType = FCOType.STOP
    device_id: str = "A1:B2:C3:D4:E5:F6"
    user_agent: str = "SSI Python SDK/" + __version__

    def to_dict(self) -> dict:
        """Convert request parameters to camelCase API query dict."""
        if self.fco_type == FCOType.STOP:
            price = OrderType.MTL.value
            price_slip = 0
        else:
            price =f"{self.price}"
            price_slip = self.price_slip
        return {
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
            "userAgent": self.user_agent
        }

    def to_str(self) -> str:
        """Serialize the place-order payload to a JSON string.

        Returns:
            JSON string of the camelCase payload produced by to_dict.
        """
        return json.dumps(self.to_dict())


@dataclass
class TrailingStopParams:
    account_no: str
    symbol: str
    side: OrderSide
    quantity: int
    active_price: int
    trailing_amount: int
    price_slip: int | float = 0
    from_date: str | None = None
    to_date: str | None = None
    fco_type: FCOType = FCOType.TRAILING_STOP
    device_id: str = "A1:B2:C3:D4:E5:F6"
    user_agent: str = "SSI Python SDK/" + __version__
    
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
        return params

    def to_str(self) -> str:
        """Serialize the place-order payload to a JSON string.

        Returns:
            JSON string of the camelCase payload produced by to_dict.
        """
        return json.dumps(self.to_dict())


@dataclass
class OCOParams:
    account_no: str
    symbol: str
    quantity: int

    side: OrderSide
    tp_active_price: int | float
    sl_active_price: int | float
    tp_price: int | float | OrderType
    sl_price: int | float | OrderType
    tp_slip: int | float
    sl_slip: int | float

    from_date: str | None = None
    to_date: str | None = None
    fco_type: FCOType = FCOType.OCO
    device_id: str = "A1:B2:C3:D4:E5:F6"
    user_agent: str = "SSI Python SDK/" + __version__

    def to_dict(self) -> dict:
        """Convert request parameters to camelCase API query dict."""
        tp_price_str = (
            f"{self.tp_price}"
            if isinstance(self.tp_price, (int, float))
            else (
                self.tp_price
                if isinstance(self.tp_price, str)
                else (
                    self.tp_price.value
                    if hasattr(self.tp_price, "value")
                    else str(self.tp_price)
                )
            )
        )
        sl_price_str = (
            f"{self.sl_price}"
            if isinstance(self.sl_price, (int, float))
            else (
                self.sl_price
                if isinstance(self.sl_price, str)
                else (
                    self.sl_price.value
                    if hasattr(self.sl_price, "value")
                    else str(self.sl_price)
                )
            )
        )

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
            "code": "",
        }
        return params

    def to_str(self) -> str:
        """Serialize the place-order payload to a JSON string.

        Returns:
            JSON string of the camelCase payload produced by to_dict.
        """
        return json.dumps(self.to_dict())


@dataclass
class BullBearParams:
    account_no: str
    symbol: str
    quantity: int

    side: OrderSide
    price: int | float | OrderType
    price_slip: int | float
    tp_active_price: int | float
    sl_active_price: int | float
    tp_price: int | float | OrderType
    sl_price: int | float | OrderType
    tp_slip: int | float
    sl_slip: int | float

    from_date: str | None = None
    to_date: str | None = None
    fco_type: FCOType = FCOType.BULL_BEAR
    device_id: str = "A1:B2:C3:D4:E5:F6"
    user_agent: str = "SSI Python SDK/" + __version__

    def to_dict(self) -> dict:
        """Convert request parameters to camelCase API query dict."""
        if isinstance(self.price, (int, float)):
            price = f"{self.price}"
            price_slip = self.price_slip
        elif isinstance(self.price, str):
            price = self.price
            price_slip = self.price_slip
        elif hasattr(self.price, "value"):
            price = self.price.value
            price_slip = 0
        else:
            price = str(self.price) if self.price is not None else ""
            price_slip = 0

        if isinstance(self.tp_price, (int, float)):
            tp_price_str = f"{self.tp_price}"
            tp_slip = self.tp_slip
        elif isinstance(self.tp_price, str):
            tp_price_str = self.tp_price
            tp_slip = self.tp_slip
        elif hasattr(self.tp_price, "value"):
            tp_price_str = self.tp_price.value
            tp_slip = 0
        else:
            tp_price_str = str(self.tp_price) if self.tp_price is not None else ""
            tp_slip = 0

        if isinstance(self.sl_price, (int, float)):
            sl_price_str = f"{self.sl_price}"
            sl_slip = self.sl_slip
        elif isinstance(self.sl_price, str):
            sl_price_str = self.sl_price
            sl_slip = self.sl_slip
        elif hasattr(self.sl_price, "value"):
            sl_price_str = self.sl_price.value
            sl_slip = 0
        else:
            sl_price_str = str(self.sl_price) if self.sl_price is not None else ""
            sl_slip = 0

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
        return params

    def to_str(self) -> str:
        """Serialize the place-order payload to a JSON string.

        Returns:
            JSON string of the camelCase payload produced by to_dict.
        """
        return json.dumps(self.to_dict())


@dataclass
class FCOPlaceResponse:
    fco_id: str

    @classmethod
    def from_dict(cls, data: dict) -> FCOPlaceResponse:
        """Create FCOPlaceResponse from a dictionary."""
        return cls(
            fco_id=str(data.get("fcoId", "")),
        )


@dataclass
class FCOCancelRequest:
    fco_id: str

    def to_dict(self) -> dict:
        return {
            "fcoId": self.fco_id
        }

    def to_str(self) -> str:
        """Serialize the place-order payload to a JSON string.

        Returns:
            JSON string of the camelCase payload produced by to_dict.
        """
        return json.dumps(self.to_dict())


@dataclass
class FCOCancelResponse:
    fco_id: str

    @classmethod
    def from_dict(cls, data: dict) -> FCOPlaceResponse:
        """Create FCOPlaceResponse from a dictionary."""
        return cls(
            fco_id=str(data.get("fcoId", "")),
        )
