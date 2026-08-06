"""Portfolio data models."""

from __future__ import annotations

from dataclasses import dataclass, field

from ssi_sdk.constant import DEFAULT_PAGE, DEFAULT_SIZE
from ssi_sdk.enums import OrderSide, OrderStatus, OrderType
from ssi_sdk.utils import to_float, to_int, to_number, to_price


@dataclass
class AccountBalanceRequest:
    """Account balance request."""

    client_id: str
    account_no: str | None = None

    def to_dict(self) -> dict:
        """Convert the request to an API query-parameter dictionary.

        Returns:
            Dictionary with ``clientId`` and optionally ``accountNo`` when set.
        """
        params = {"clientId": self.client_id}
        if self.account_no is not None:
            params["accountNo"] = self.account_no
        return params


@dataclass
class EquityAccountBalance:
    """Equity account balance information."""

    account_no: str = ""
    account_balance: float = 0.0
    total_debt: float = 0.0
    interest_loan: float = 0.0
    overdue_fee_loan: float = 0.0
    withdrawable: float = 0.0
    on_hold_cash: float = 0.0
    sell_unmatched: float = 0.0
    sell_t0: float = 0.0
    sell_t1: float = 0.0
    sell_t2: float = 0.0
    buy_unmatched: float = 0.0
    buy_t0: float = 0.0
    buy_t1: float = 0.0
    buy_t2: float = 0.0
    advance_cash_t0: float = 0.0
    advance_cash_t1: float = 0.0
    hold_subscription: float = 0.0

    @classmethod
    def from_dict(cls, data: dict) -> EquityAccountBalance:
        """Create an EquityAccountBalance from an API response dictionary.

        Args:
            data: Equity balance payload with camelCase keys (e.g. ``accountNo``,
                ``accountBalance``); missing keys default to empty or ``0.0``.
        Returns:
            Populated EquityAccountBalance instance.
        """
        return cls(
            account_no=data.get("accountNo", ""),
            account_balance=to_float(data.get("accountBalance")),
            total_debt=to_float(data.get("totalDebt")),
            interest_loan=to_float(data.get("interestLoan")),
            overdue_fee_loan=to_float(data.get("overdueFeeLoan")),
            withdrawable=to_float(data.get("withdrawable")),
            on_hold_cash=to_float(data.get("onHoldCash")),
            sell_unmatched=to_float(data.get("sellUnmatched")),
            sell_t0=to_float(data.get("sellT0")),
            sell_t1=to_float(data.get("sellT1")),
            sell_t2=to_float(data.get("sellT2")),
            buy_unmatched=to_float(data.get("buyUnmatched")),
            buy_t0=to_float(data.get("buyT0")),
            buy_t1=to_float(data.get("buyT1")),
            buy_t2=to_float(data.get("buyT2")),
            advance_cash_t0=to_float(data.get("advanceCashT0")),
            advance_cash_t1=to_float(data.get("advanceCashT1")),
            hold_subscription=to_float(data.get("holdSubscription")),
        )


@dataclass
class DerivativeAccountBalance:
    """Derivative account balance information."""

    account_no: str = ""
    account_balance: float = 0.0
    fee: float = 0.0
    commission: float = 0.0
    interest: float = 0.0
    ext_interest: float = 0.0
    loan: float = 0.0
    delivery_amount: float = 0.0
    floating_pl: float = 0.0
    trading_pl: float = 0.0
    total_pl: float = 0.0
    withdrawable: float = 0.0
    cash_ssi: float = 0.0
    valid_non_cash_ssi: float = 0.0
    cash_withdrawable_ssi: float = 0.0
    cash_vsdc: float = 0.0
    valid_non_cash_vsdc: float = 0.0
    cash_withdrawable_vsdc: float = 0.0

    @classmethod
    def from_dict(cls, data: dict) -> DerivativeAccountBalance:
        """Create a DerivativeAccountBalance from an API response dictionary.

        Args:
            data: Derivative balance payload with camelCase keys (e.g. ``accountNo``,
                ``accountBalance``); missing keys default to empty or ``0.0``.
        Returns:
            Populated DerivativeAccountBalance instance.
        """
        return cls(
            account_no=data.get("accountNo", ""),
            account_balance=to_float(data.get("accountBalance")),
            fee=to_float(data.get("fee")),
            commission=to_float(data.get("commission")),
            interest=to_float(data.get("interest")),
            ext_interest=to_float(data.get("extInterest")),
            loan=to_float(data.get("loan")),
            delivery_amount=to_float(data.get("deliveryAmount")),
            floating_pl=to_float(data.get("floatingPL")),
            trading_pl=to_float(data.get("tradingPL")),
            total_pl=to_float(data.get("totalPL")),
            withdrawable=to_float(data.get("withdrawable")),
            cash_ssi=to_float(data.get("cashSSI")),
            valid_non_cash_ssi=to_float(data.get("validNonCashSSI")),
            cash_withdrawable_ssi=to_float(data.get("cashWithdrawableSSI")),
            cash_vsdc=to_float(data.get("cashVSDC")),
            valid_non_cash_vsdc=to_float(data.get("validNonCashVSDC")),
            cash_withdrawable_vsdc=to_float(data.get("cashWithdrawableVSDC")),
        )


@dataclass
class AccountBalance:
    """Account balance information."""

    equity: EquityAccountBalance | None = None
    derivative: DerivativeAccountBalance | None = None

    @classmethod
    def from_dict(cls, data: dict) -> AccountBalance:
        """Create an AccountBalance from an API response dictionary.

        Args:
            data: Payload with optional ``equity`` and ``derivative`` sub-objects;
                absent or empty sections yield ``None`` for that side.
        Returns:
            AccountBalance wrapping the parsed equity and derivative balances.
        """
        return cls(
            equity=EquityAccountBalance.from_dict(data.get("equity", {}))
            if data.get("equity")
            else None,
            derivative=DerivativeAccountBalance.from_dict(data.get("derivative", {}))
            if data.get("derivative")
            else None,
        )


@dataclass
class PositionsRequest:
    """Positions request."""

    client_id: str
    account_no: str | None = None

    def to_dict(self) -> dict:
        """Convert the request to an API query-parameter dictionary.

        Returns:
            Dictionary with ``clientId`` and optionally ``accountNo`` when set.
        """
        params = {"clientId": self.client_id}
        if self.account_no is not None:
            params["accountNo"] = self.account_no
        return params


@dataclass
class EquityPosition:
    """Equity position information."""

    account_no: str = ""
    symbol: str = ""
    quantity: int = 0
    block_quantity: int = 0
    dividend_quantity: int = 0
    buying_quantity: int = 0
    bought_quantity: int = 0
    selling_quantity: int = 0
    sold_quantity: int = 0
    t1_sell_quantity: int = 0
    t2_sell_quantity: int = 0
    cost_price: float = 0.0
    mortgage_quantity: int = 0
    sellable_quantity: int = 0
    restricted_quantity: int = 0

    @classmethod
    def from_list(cls, data: list) -> list[EquityPosition]:
        """Create EquityPosition instances from a list of API response items.

        Args:
            data: List of equity position dicts with camelCase keys (e.g. ``symbol``,
                ``quantity``); missing keys default to empty or ``0``.
        Returns:
            List of EquityPosition instances, one per input item.
        """
        return [
            cls(
                account_no=item.get("accountNo", ""),
                symbol=item.get("symbol", ""),
                quantity=to_int(item.get("quantity", 0)),
                block_quantity=to_int(item.get("blockQuantity", 0)),
                dividend_quantity=to_int(item.get("dividendQuantity", 0)),
                buying_quantity=to_int(item.get("buyingQuantity", 0)),
                bought_quantity=to_int(item.get("boughtQuantity", 0)),
                selling_quantity=to_int(item.get("sellingQuantity", 0)),
                sold_quantity=to_int(item.get("soldQuantity", 0)),
                t1_sell_quantity=to_int(item.get("t1SellQuantity", 0)),
                t2_sell_quantity=to_int(item.get("t2SellQuantity", 0)),
                cost_price=to_float(item.get("costPrice")),
                mortgage_quantity=to_int(item.get("mortgageQuantity", 0)),
                sellable_quantity=to_int(item.get("sellableQuantity", 0)),
                restricted_quantity=to_int(item.get("restrictedQuantity", 0)),
            )
            for item in data
        ]


@dataclass
class DerivativePosition:
    """Derivative position information."""

    account_no: str = ""
    symbol: str = ""
    long: int = 0
    short: int = 0
    net: int = 0
    bid_avg_price: float = 0.0
    ask_avg_price: float = 0.0
    trade_price: float = 0.0
    floating_pl: float = 0.0
    trading_pl: float = 0.0

    @classmethod
    def from_list(cls, data: list) -> list[DerivativePosition]:
        """Create DerivativePosition instances from a list of API response items.

        Args:
            data: List of derivative position dicts with camelCase keys (e.g. ``symbol``,
                ``long``, ``short``); missing keys default to empty or ``0``.
        Returns:
            List of DerivativePosition instances, one per input item.
        """
        return [
            cls(
                account_no=item.get("accountNo", ""),
                symbol=item.get("symbol", ""),
                long=to_int(item.get("long", 0)),
                short=to_int(item.get("short", 0)),
                net=to_int(item.get("net", 0)),
                bid_avg_price=to_float(item.get("bidAvgPrice")),
                ask_avg_price=to_float(item.get("askAvgPrice")),
                trade_price=to_float(item.get("tradePrice")),
                floating_pl=to_float(item.get("floatingPL")),
                trading_pl=to_float(item.get("tradingPL")),
            )
            for item in data
        ]


@dataclass
class AllDerivativePosition:
    """Derivatives position information."""

    open_positions: list[DerivativePosition] = field(default_factory=list)
    closed_positions: list[DerivativePosition] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> AllDerivativePosition:
        """Create an AllDerivativePosition from an API response dictionary.

        Args:
            data: Payload with ``derOpenPositions`` and ``derClosePositions`` lists;
                absent keys yield empty position lists.
        Returns:
            AllDerivativePosition holding the open and closed position lists.
        """
        return cls(
            open_positions=DerivativePosition.from_list(data.get("derOpenPositions", [])),
            closed_positions=DerivativePosition.from_list(data.get("derClosePositions", [])),
        )


@dataclass
class Position:
    """Position information."""

    equity: list[EquityPosition] | None = None
    derivative: AllDerivativePosition | None = None

    @classmethod
    def from_dict(cls, data: dict) -> Position:
        """Create a Position from an API response dictionary.

        Args:
            data: Payload with optional ``equity`` list and ``derivative`` sub-object;
                absent or empty sections yield ``None`` for that side.
        Returns:
            Position wrapping the parsed equity and derivative positions.
        """
        return cls(
            equity=EquityPosition.from_list(data.get("equity", [])) if data.get("equity") else None,
            derivative=AllDerivativePosition.from_dict(data.get("derivative", {}))
            if data.get("derivative")
            else None,
        )


@dataclass
class PPMMRRequest:
    """PPMMR request."""

    account_no: str

    def to_dict(self) -> dict:
        """Convert the request to an API query-parameter dictionary.

        Returns:
            Dictionary with the ``accountNo`` key.
        """
        return {"accountNo": self.account_no}


@dataclass
class EquityPPMMR:
    """Equity PPMMR information."""

    account_no: str = ""
    dividend: float = 0.0
    loan_value: float = 0.0
    total_debt: float = 0.0
    debt: float = 0.0
    liability: float = 0.0
    liability_ssi: float = 0.0
    net_liability: float = 0.0
    fees: float = 0.0
    interest_ssi: float = 0.0
    interest_spv: float = 0.0
    withdrawable: float = 0.0
    ee: float = 0.0
    ee50: float = 0.0
    ee60: float = 0.0
    ee70: float = 0.0
    ee80: float = 0.0
    ee90: float = 0.0
    action: float = 0.0
    action_ssi: float = 0.0
    equity: float = 0.0
    equity_ssi: float = 0.0
    ee_cash: float = 0.0
    hold_subscription: float = 0.0
    bank_balance: float = 0.0
    on_hold_cash: float = 0.0
    doverdue: float = 0.0
    doverdue_ssi: float = 0.0
    account_balance: float = 0.0
    d: float = 0.0
    d_spv: float = 0.0
    d_ssi: float = 0.0
    cia: float = 0.0
    collateral_asset: float = 0.0
    collateral_asset_ssi: float = 0.0
    total_assets: float = 0.0
    total_equity: float = 0.0
    total_equity_ssi: float = 0.0
    lmv: float = 0.0
    lmv_margin: float = 0.0
    lmv_margin_ssi: float = 0.0
    call_lmv: float = 0.0
    force_lmv: float = 0.0
    call_lmv_ssi: float = 0.0
    force_lmv_ssi: float = 0.0
    lmv_non_marginable: float = 0.0
    lmv_non_marginable_ssi: float = 0.0
    pre_loan: float = 0.0
    margin_ratio: float = 0.0
    margin_ratio_ssi: float = 0.0
    purchasing_power: float = 0.0
    ee_origin: float = 0.0
    buy_unmatched: float = 0.0
    sell_unmatched: float = 0.0
    buy_t0: float = 0.0
    sell_t0: float = 0.0
    sell_t1: float = 0.0
    sell_t2: float = 0.0
    buy_t1: float = 0.0
    buy_t2: float = 0.0
    credit_limit: float = 0.0
    margin_call_lmv_sold: float = 0.0
    margin_call_lmv_sold_ssi: float = 0.0
    margin_call: float = 0.0
    margin_call_ssi: float = 0.0
    collateral_a: float = 0.0
    collateral_non: float = 0.0
    collateral_a_ssi: float = 0.0
    collateral_non_ssi: float = 0.0
    call_margin: float = 0.0
    call_force_sell: float = 0.0
    call_margin_ssi: float = 0.0
    call_force_sell_ssi: float = 0.0
    ar: float = 0.0

    @classmethod
    def from_dict(cls, data: dict) -> EquityPPMMR:
        """Create an EquityPPMMR from an API response dictionary.

        Args:
            data: Equity purchasing-power / margin payload with camelCase keys (e.g.
                ``purchasingPower``, ``marginRatio``); missing keys default to empty or ``0.0``.
        Returns:
            Populated EquityPPMMR instance.
        """
        return cls(
            account_no=data.get("accountNo", ""),
            dividend=to_float(data.get("dividend")),
            loan_value=to_float(data.get("loanValue")),
            total_debt=to_float(data.get("totalDebt")),
            debt=to_float(data.get("debt")),
            liability=to_float(data.get("liability")),
            liability_ssi=to_float(data.get("liabilitySSI")),
            net_liability=to_float(data.get("netLiability")),
            fees=to_float(data.get("fees")),
            interest_ssi=to_float(data.get("interestSSI")),
            interest_spv=to_float(data.get("interestSPV")),
            withdrawable=to_float(data.get("withdrawable")),
            ee=to_float(data.get("ee")),
            ee50=to_float(data.get("ee50")),
            ee60=to_float(data.get("ee60")),
            ee70=to_float(data.get("ee70")),
            ee80=to_float(data.get("ee80")),
            ee90=to_float(data.get("ee90")),
            action=to_float(data.get("action")),
            action_ssi=to_float(data.get("actionSSI")),
            equity=to_float(data.get("equity")),
            equity_ssi=to_float(data.get("equitySSI")),
            ee_cash=to_float(data.get("eeCash")),
            hold_subscription=to_float(data.get("holdSubscription")),
            bank_balance=to_float(data.get("bankBalance")),
            on_hold_cash=to_float(data.get("onHoldCash")),
            doverdue=to_float(data.get("doverdue")),
            doverdue_ssi=to_float(data.get("doverdueSSI")),
            account_balance=to_float(data.get("accountBalance")),
            d=to_float(data.get("D")),
            d_spv=to_float(data.get("dSPV")),
            d_ssi=to_float(data.get("dSSI")),
            cia=to_float(data.get("cia")),
            collateral_asset=to_float(data.get("collateralAsset")),
            collateral_asset_ssi=to_float(data.get("collateralAssetSSI")),
            total_assets=to_float(data.get("totalAssets")),
            total_equity=to_float(data.get("totalEquity")),
            total_equity_ssi=to_float(data.get("totalEquitySSI")),
            lmv=to_float(data.get("lmv")),
            lmv_margin=to_float(data.get("lmvMargin")),
            lmv_margin_ssi=to_float(data.get("lmvMarginSSI")),
            call_lmv=to_float(data.get("callLmv")),
            force_lmv=to_float(data.get("forceLmv")),
            call_lmv_ssi=to_float(data.get("callLmvSSI")),
            force_lmv_ssi=to_float(data.get("forceLmvSSI")),
            lmv_non_marginable=to_float(data.get("lmvNonMarginable")),
            lmv_non_marginable_ssi=to_float(data.get("lmvNonMarginableSSI")),
            pre_loan=to_float(data.get("preLoan")),
            margin_ratio=to_float(data.get("marginRatio")),
            margin_ratio_ssi=to_float(data.get("marginRatioSSI")),
            purchasing_power=to_float(data.get("purchasingPower")),
            ee_origin=to_float(data.get("eeOrigin")),
            buy_unmatched=to_float(data.get("buyUnmatched")),
            sell_unmatched=to_float(data.get("sellUnmatched")),
            buy_t0=to_float(data.get("buyT0")),
            buy_t1=to_float(data.get("buyT1")),
            buy_t2=to_float(data.get("buyT2")),
            sell_t0=to_float(data.get("sellT0")),
            sell_t1=to_float(data.get("sellT1")),
            sell_t2=to_float(data.get("sellT2")),
            credit_limit=to_float(data.get("creditLimit")),
            margin_call_lmv_sold=to_float(data.get("marginCallLmvSold")),
            margin_call_lmv_sold_ssi=to_float(data.get("marginCallLmvSoldSSI")),
            margin_call=to_float(data.get("marginCall")),
            margin_call_ssi=to_float(data.get("marginCallSSI")),
            collateral_a=to_float(data.get("collateralA")),
            collateral_non=to_float(data.get("collateralNon")),
            collateral_a_ssi=to_float(data.get("collateralASSI")),
            collateral_non_ssi=to_float(data.get("collateralNonSSI")),
            call_margin=to_float(data.get("callMargin")),
            call_force_sell=to_float(data.get("callForceSell")),
            call_margin_ssi=to_float(data.get("callMarginSSI")),
            call_force_sell_ssi=to_float(data.get("callForceSellSSI")),
            ar=to_float(data.get("ar")),
        )


@dataclass
class DerivativePPMMR:
    """Derivative PPMMR information."""

    account_no: str = ""
    account_balance: float = 0.0
    fee: float = 0.0
    commission: float = 0.0
    interest: float = 0.0
    loan: float = 0.0
    delivery_amount: float = 0.0
    floating_pl: float = 0.0
    trading_pl: float = 0.0
    total_pl: float = 0.0
    marginable: float = 0.0
    depositable: float = 0.0
    rc_call: float = 0.0
    withdrawable: float = 0.0
    non_cash_drawable_rc_call: float = 0.0
    cash_ssi: float = 0.0
    valid_non_cash_ssi: float = 0.0
    total_asset_ssi: float = 0.0
    withdrawable_ssi: float = 0.0
    ee_ssi: float = 0.0
    cash_vsdc: float = 0.0
    valid_non_cash_vsdc: float = 0.0
    total_asset_vsdc: float = 0.0
    withdrawable_vsdc: float = 0.0
    ee_vsdc: float = 0.0
    spread_margin_ssi: float = 0.0
    delivery_margin_ssi: float = 0.0
    margin_req_ssi: float = 0.0
    account_ratio_ssi: float = 0.0
    used_limit_warning_level1_ssi: float = 0.0
    used_limit_warning_level2_ssi: float = 0.0
    used_limit_warning_level3_ssi: float = 0.0
    margin_call_ssi: float = 0.0
    spread_margin_vsdc: float = 0.0
    delivery_margin_vsdc: float = 0.0
    margin_req_vsdc: float = 0.0
    account_ratio_vsdc: float = 0.0
    used_limit_warning_level1_vsdc: float = 0.0
    used_limit_warning_level2_vsdc: float = 0.0
    used_limit_warning_level3_vsdc: float = 0.0
    margin_call_vsdc: float = 0.0
    total_equity: float = 0.0
    ext_interest: float = 0.0

    @classmethod
    def from_dict(cls, data: dict) -> DerivativePPMMR:
        """Create a DerivativePPMMR from an API response dictionary.

        Args:
            data: Derivative purchasing-power / margin payload with camelCase keys (e.g.
                ``marginReqSSI``, ``accountRatioVSDC``); missing keys default to empty or ``0.0``.
        Returns:
            Populated DerivativePPMMR instance.
        """
        return cls(
            account_no=data.get("accountNo", ""),
            account_balance=to_number(data.get("accountBalance")),
            fee=to_number(data.get("fee")),
            commission=to_number(data.get("commission")),
            interest=to_number(data.get("interest")),
            loan=to_number(data.get("loan")),
            delivery_amount=to_number(data.get("deliveryAmount")),
            floating_pl=to_number(data.get("floatingPL")),
            trading_pl=to_number(data.get("tradingPL")),
            total_pl=to_number(data.get("totalPL")),
            marginable=to_number(data.get("marginable")),
            depositable=to_number(data.get("depositable")),
            rc_call=to_number(data.get("rcCall")),
            withdrawable=to_number(data.get("withdrawable")),
            non_cash_drawable_rc_call=to_number(data.get("nonCashDrawableRcCall")),
            cash_ssi=to_number(data.get("cashSSI")),
            valid_non_cash_ssi=to_number(data.get("validNonCashSSI")),
            total_asset_ssi=to_number(data.get("totalAssetSSI")),
            withdrawable_ssi=to_number(data.get("withdrawableSSI")),
            ee_ssi=to_number(data.get("eeSSI")),
            cash_vsdc=to_number(data.get("cashVSDC")),
            valid_non_cash_vsdc=to_number(data.get("validNonCashVSDC")),
            total_asset_vsdc=to_number(data.get("totalAssetVSDC")),
            withdrawable_vsdc=to_number(data.get("withdrawableVSDC")),
            ee_vsdc=to_number(data.get("eeVSDC")),
            spread_margin_ssi=to_number(data.get("spreadMarginSSI")),
            delivery_margin_ssi=to_number(data.get("deliveryMarginSSI")),
            margin_req_ssi=to_number(data.get("marginReqSSI")),
            account_ratio_ssi=to_number(data.get("accountRatioSSI")),
            used_limit_warning_level1_ssi=to_number(data.get("usedLimitWarningLevel1SSI")),
            used_limit_warning_level2_ssi=to_number(data.get("usedLimitWarningLevel2SSI")),
            used_limit_warning_level3_ssi=to_number(data.get("usedLimitWarningLevel3SSI")),
            margin_call_ssi=to_number(data.get("marginCallSSI")),
            spread_margin_vsdc=to_number(data.get("spreadMarginVSDC")),
            delivery_margin_vsdc=to_number(data.get("deliveryMarginVSDC")),
            margin_req_vsdc=to_number(data.get("marginReqVSDC")),
            account_ratio_vsdc=to_number(data.get("accountRatioVSDC")),
            used_limit_warning_level1_vsdc=to_number(data.get("usedLimitWarningLevel1VSDC")),
            used_limit_warning_level2_vsdc=to_number(data.get("usedLimitWarningLevel2VSDC")),
            used_limit_warning_level3_vsdc=to_number(data.get("usedLimitWarningLevel3VSDC")),
            margin_call_vsdc=to_number(data.get("marginCallVSDC")),
            total_equity=to_number(data.get("totalEquity")),
            ext_interest=to_number(data.get("extInterest")),
        )


@dataclass
class PPMMR:
    """PPMMR information."""

    equity: EquityPPMMR | None = None
    derivative: DerivativePPMMR | None = None

    @classmethod
    def from_dict(cls, data: dict) -> PPMMR:
        """Create a PPMMR from an API response dictionary.

        Args:
            data: Payload with optional ``equity`` and ``derivative`` sub-objects;
                absent or empty sections yield ``None`` for that side.
        Returns:
            PPMMR wrapping the parsed equity and derivative purchasing-power data.
        """
        return cls(
            equity=EquityPPMMR.from_dict(data.get("equity", {})) if data.get("equity") else None,
            derivative=DerivativePPMMR.from_dict(data.get("derivative", {}))
            if data.get("derivative")
            else None,
        )


@dataclass
class OrderBookRequest:
    """Order book request."""

    account_no: str
    from_date: str | None = None
    to_date: str | None = None
    page: int = DEFAULT_PAGE
    size: int = DEFAULT_SIZE

    def to_dict(self) -> dict:
        """Convert the request to an API query-parameter dictionary.

        Returns:
            Dictionary with ``accountNo``, ``from``, ``to``, ``pageIndex`` and ``pageSize`` keys.
        """
        return {
            "accountNo": self.account_no,
            "from": self.from_date,
            "to": self.to_date,
            "pageIndex": self.page,
            "pageSize": self.size,
        }


@dataclass
class Order:
    """Order information."""

    account_no: str = ""
    client_request_id: str = ""
    order_id: str = ""
    symbol: str = ""
    side: OrderSide | None = None
    order_type: OrderType | None = None
    price: int | float | OrderSide = 0
    avg_price: int | float = 0
    quantity: int = 0
    os_quantity: int = 0
    filled_quantity: int = 0
    cancel_quantity: int = 0
    status: OrderStatus | None = None
    input_time: str = ""
    modify_time: str = ""
    message: str = ""

    @classmethod
    def from_dict(cls, data: dict, account_no: str) -> Order:
        """Create an Order from an API response dictionary.

        Args:
            data: Order payload with camelCase keys (e.g. ``orderId``, ``side``,
                ``orderStatus``); missing keys default to empty or ``0``.
            account_no: Trading account number to attach to the order.
        Returns:
            Populated Order instance with enum side, type and status fields parsed.
        """
        return cls(
            account_no=account_no,
            client_request_id=data.get("clientRequestId", ""),
            order_id=data.get("orderId", ""),
            symbol=data.get("symbol", ""),
            side=OrderSide(data.get("side")) if data.get("side") else None,
            order_type=OrderType(data.get("orderType")) if data.get("orderType") else None,
            price=to_price(data.get("price")),
            avg_price=to_number(data.get("avgPrice")),
            quantity=to_int(data.get("quantity", 0)),
            os_quantity=to_int(data.get("osQuantity", 0)),
            filled_quantity=to_int(data.get("filledQuantity", 0)),
            cancel_quantity=to_int(data.get("cancelQuantity", 0)),
            status=OrderStatus(data.get("orderStatus")) if data.get("orderStatus") else None,
            input_time=data.get("inputTime", ""),
            modify_time=data.get("modifiedTime", ""),
            message=data.get("message", ""),
        )


@dataclass
class OrderBook:
    """Order book information."""

    orders: list[Order] = field(default_factory=list)
    total_orders: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> OrderBook:
        """Create an OrderBook from an API response dictionary.

        Args:
            data: Payload with an ``orderList`` array, an ``accountNo`` applied to each
                order, and a ``totalRecord`` count; absent keys yield an empty book.
        Returns:
            OrderBook holding the parsed orders and total record count.
        """
        return cls(
            orders=[
                Order.from_dict(order, account_no=data.get("accountNo", ""))
                for order in data.get("orderList", [])
            ],
            total_orders=to_int(data.get("totalRecord", 0)),
        )
