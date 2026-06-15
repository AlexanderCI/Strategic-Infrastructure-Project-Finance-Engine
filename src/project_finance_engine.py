"""
Deterministic project finance underwriting and credit sizing engine.

The model is built around a secure deepwater maritime logistics hub with a
three-year construction period and a twenty-year operating period. It keeps the
logic deterministic on purpose: no vague scenario generator, no black-box debt
sizing, and no random capital stack outputs. The point is to show how the debt
capacity, covenant path, cash waterfall, and stress cases mechanically talk to
each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple
import math

import numpy as np
import pandas as pd


Number = float


class ModelInputError(ValueError):
    """Raised when transaction assumptions are internally inconsistent."""


@dataclass(frozen=True)
class TransactionConfig:
    """Core deal assumptions for the maritime logistics hub financing."""

    project_name: str = "Secure Deepwater Maritime Logistics Hub"
    total_horizon_years: int = 23
    construction_years: Tuple[int, ...] = (1, 2, 3)
    operational_years: Tuple[int, ...] = tuple(range(4, 24))

    total_capex: Number = 2_500_000_000.0
    capex_draw_schedule: Dict[int, Number] = field(
        default_factory=lambda: {1: 0.30, 2: 0.40, 3: 0.30}
    )

    starting_revenue: Number = 375_000_000.0
    revenue_escalation: Number = 0.025
    base_opex_pct_of_revenue: Number = 0.35
    maintenance_capex_pct_of_revenue: Number = 0.035
    working_capital_reserve_pct_of_revenue: Number = 0.010

    senior_interest_rate: Number = 0.050
    senior_risk_free_rate: Number = 0.030
    senior_credit_spread: Number = 0.020
    senior_amortization_years: int = 15
    senior_amortization_start_year: int = 4
    senior_maturity_year: int = 18
    dscr_floor: Number = 1.30

    mezzanine_pct_of_capex: Number = 0.15
    mezzanine_interest_rate: Number = 0.075
    sponsor_target_equity_return: Number = 0.12

    guarantee_pct_of_senior_debt: Number = 0.10
    guarantee_spread_reduction_factor: Number = 0.50

    def validate(self) -> None:
        if self.total_horizon_years <= 0:
            raise ModelInputError("model horizon must be positive")
        if set(self.construction_years).intersection(self.operational_years):
            raise ModelInputError("construction and operational years cannot overlap")
        if min(self.construction_years) != 1:
            raise ModelInputError("construction period must start at year 1")
        if max(self.operational_years) != self.total_horizon_years:
            raise ModelInputError("operating period must run through the model horizon")
        if not math.isclose(sum(self.capex_draw_schedule.values()), 1.0, rel_tol=1e-9):
            raise ModelInputError("capex draw schedule must sum to 100%")
        if any(v < 0 for v in self.capex_draw_schedule.values()):
            raise ModelInputError("capex draw schedule cannot contain negative weights")
        if self.total_capex <= 0:
            raise ModelInputError("total capex must be positive")
        if self.dscr_floor <= 1.0:
            raise ModelInputError("dscr floor should be above 1.0x for a senior debt sizing test")
        if self.mezzanine_pct_of_capex < 0 or self.mezzanine_pct_of_capex >= 1:
            raise ModelInputError("mezzanine percentage must sit between 0% and 100%")
        if self.senior_amortization_start_year not in self.operational_years:
            raise ModelInputError("senior amortization must start inside the operating period")
        if self.senior_maturity_year < self.senior_amortization_start_year:
            raise ModelInputError("senior maturity cannot come before amortization starts")
        if self.senior_amortization_years != (
            self.senior_maturity_year - self.senior_amortization_start_year + 1
        ):
            raise ModelInputError("senior amortization years must match start and maturity years")

    @property
    def mezzanine_commitment(self) -> Number:
        return self.total_capex * self.mezzanine_pct_of_capex

    @property
    def years(self) -> Tuple[int, ...]:
        return tuple(range(1, self.total_horizon_years + 1))

    @property
    def senior_amortization_year_range(self) -> Tuple[int, ...]:
        return tuple(range(self.senior_amortization_start_year, self.senior_maturity_year + 1))


@dataclass(frozen=True)
class Scenario:
    """A deterministic operating case. Stress is applied by year, not by random path."""

    name: str
    revenue_multipliers: Dict[int, Number] = field(default_factory=dict)
    opex_pct_overrides: Dict[int, Number] = field(default_factory=dict)
    use_first_loss_guarantee: bool = False
    reduce_senior_spread: bool = False

    def revenue_multiplier(self, year: int) -> Number:
        return self.revenue_multipliers.get(year, 1.0)

    def opex_pct(self, year: int, config: TransactionConfig) -> Number:
        return self.opex_pct_overrides.get(year, config.base_opex_pct_of_revenue)


@dataclass
class ScenarioResult:
    scenario_name: str
    annual_table: pd.DataFrame
    summary: Dict[str, Number]
    covenant_breaches: pd.DataFrame


class FinancialMath:
    """Small finance helpers kept inside the repo so the engine stays self-contained."""

    @staticmethod
    def npv(rate: Number, cashflows: Iterable[Number]) -> Number:
        cashflows_array = np.asarray(list(cashflows), dtype=float)
        if rate <= -1.0:
            raise ModelInputError("discount rate must be greater than -100%")
        periods = np.arange(len(cashflows_array), dtype=float)
        return float(np.sum(cashflows_array / np.power(1.0 + rate, periods)))

    @staticmethod
    def irr(cashflows: Iterable[Number], lower: Number = -0.95, upper: Number = 2.00) -> Number:
        """
        Compute annual IRR with bisection.

        Numpy no longer ships a built-in IRR function. The implementation here is
        intentionally simple because the cash-flow sign pattern is controlled by
        the model: construction draws first, operating distributions later.
        """

        flows = np.asarray(list(cashflows), dtype=float)
        if flows.size < 2:
            return float("nan")
        if not (np.any(flows < 0) and np.any(flows > 0)):
            return float("nan")

        def f(rate: Number) -> Number:
            return FinancialMath.npv(rate, flows)

        lo, hi = lower, upper
        flo, fhi = f(lo), f(hi)
        expansion_count = 0
        while flo * fhi > 0 and expansion_count < 20:
            hi *= 2.0
            fhi = f(hi)
            expansion_count += 1
        if flo * fhi > 0:
            return float("nan")

        for _ in range(200):
            mid = (lo + hi) / 2.0
            fmid = f(mid)
            if abs(fmid) < 1e-7:
                return float(mid)
            if flo * fmid <= 0:
                hi = mid
                fhi = fmid
            else:
                lo = mid
                flo = fmid
        return float((lo + hi) / 2.0)

    @staticmethod
    def macaulay_duration(rate: Number, cashflows: Iterable[Number]) -> Number:
        flows = np.asarray(list(cashflows), dtype=float)
        periods = np.arange(len(flows), dtype=float)
        positive_flows = np.where(flows > 0, flows, 0.0)
        pv = positive_flows / np.power(1.0 + rate, periods)
        total_pv = float(np.sum(pv))
        if total_pv <= 0:
            return float("nan")
        return float(np.sum(periods * pv) / total_pv)


class OperatingCaseBuilder:
    """Builds deterministic revenues, expenses and CFADS by operating year."""

    def __init__(self, config: TransactionConfig):
        config.validate()
        self.config = config

    def build_base_cfads(self) -> pd.Series:
        values = {}
        for year in self.config.operational_years:
            revenue = self.base_revenue_for_year(year)
            opex = revenue * self.config.base_opex_pct_of_revenue
            values[year] = revenue - opex
        return pd.Series(values, name="base_cfads", dtype=float)

    def base_revenue_for_year(self, year: int) -> Number:
        if year not in self.config.operational_years:
            return 0.0
        periods_from_start = year - self.config.operational_years[0]
        return self.config.starting_revenue * ((1.0 + self.config.revenue_escalation) ** periods_from_start)

    def revenue_for_scenario(self, year: int, scenario: Scenario) -> Number:
        return self.base_revenue_for_year(year) * scenario.revenue_multiplier(year)

    def opex_for_scenario(self, year: int, scenario: Scenario, revenue: Number) -> Number:
        return revenue * scenario.opex_pct(year, self.config)


class SeniorDebtSizer:
    """Sizes senior debt against the binding DSCR period under straight-line amortization."""

    def __init__(self, config: TransactionConfig):
        config.validate()
        self.config = config

    def size_from_base_case(self, cfads: pd.Series) -> Tuple[Number, pd.DataFrame]:
        missing_years = set(self.config.senior_amortization_year_range).difference(cfads.index)
        if missing_years:
            raise ModelInputError(f"missing CFADS for senior amortization years: {sorted(missing_years)}")

        low = 0.0
        high = max(self.config.total_capex, float(cfads.max()) * self.config.senior_amortization_years)
        tolerance = 1.0

        for _ in range(200):
            trial_debt = (low + high) / 2.0
            min_dscr = self._minimum_dscr_for_principal(trial_debt, cfads)
            if min_dscr >= self.config.dscr_floor:
                low = trial_debt
            else:
                high = trial_debt
            if high - low <= tolerance:
                break

        sized_debt = float(low)
        metrics = self.covenant_metrics(sized_debt, cfads)
        return sized_debt, metrics

    def _minimum_dscr_for_principal(self, principal: Number, cfads: pd.Series) -> Number:
        if principal <= 0:
            return float("inf")
        annual_principal = principal / self.config.senior_amortization_years
        dscr_values: List[Number] = []
        opening_balance = principal
        for year in self.config.senior_amortization_year_range:
            interest = opening_balance * self.config.senior_interest_rate
            debt_service = interest + annual_principal
            dscr_values.append(float(cfads.loc[year] / debt_service))
            opening_balance -= annual_principal
        return min(dscr_values)

    def covenant_metrics(self, principal: Number, cfads: pd.Series, senior_rate: Optional[Number] = None) -> pd.DataFrame:
        rate = self.config.senior_interest_rate if senior_rate is None else senior_rate
        annual_principal = principal / self.config.senior_amortization_years if principal > 0 else 0.0
        rows: List[Dict[str, Number]] = []
        opening_balance = principal

        for year in self.config.operational_years:
            if year in self.config.senior_amortization_year_range and opening_balance > 1e-6:
                interest = opening_balance * rate
                principal_due = min(annual_principal, opening_balance)
                debt_service = interest + principal_due
                dscr = float(cfads.loc[year] / debt_service) if debt_service > 0 else float("inf")
                remaining_years = [y for y in self.config.senior_amortization_year_range if y >= year]
                remaining_cfads = [float(cfads.loc[y]) for y in remaining_years]
                llcr_npv = self._discount_remaining_cfads(remaining_cfads, rate)
                llcr = llcr_npv / opening_balance if opening_balance > 0 else float("nan")
                ending_balance = max(0.0, opening_balance - principal_due)
            else:
                interest = 0.0
                principal_due = 0.0
                debt_service = 0.0
                dscr = float("nan")
                llcr = float("nan")
                ending_balance = opening_balance

            rows.append(
                {
                    "year": year,
                    "senior_opening_balance": opening_balance,
                    "senior_interest_due": interest,
                    "senior_principal_due": principal_due,
                    "senior_debt_service": debt_service,
                    "dscr": dscr,
                    "llcr": llcr,
                    "senior_ending_balance": ending_balance,
                }
            )
            opening_balance = ending_balance

        return pd.DataFrame(rows).set_index("year")

    @staticmethod
    def _discount_remaining_cfads(cfads_values: List[Number], rate: Number) -> Number:
        values = np.asarray(cfads_values, dtype=float)
        periods = np.arange(1, len(values) + 1, dtype=float)
        return float(np.sum(values / np.power(1.0 + rate, periods)))


class ProjectFinanceWaterfall:
    """Processes the construction ledger and operating waterfall year by year."""

    def __init__(self, config: TransactionConfig, senior_debt_sized: Number):
        config.validate()
        if senior_debt_sized < 0:
            raise ModelInputError("senior debt cannot be negative")
        if senior_debt_sized + config.mezzanine_commitment > config.total_capex + 1e-6:
            raise ModelInputError("senior debt plus mezzanine debt exceeds total capex")
        self.config = config
        self.senior_debt_sized = float(senior_debt_sized)
        self.mezzanine_commitment = config.mezzanine_commitment
        self.sponsor_equity_commitment = config.total_capex - self.senior_debt_sized - self.mezzanine_commitment
        if self.sponsor_equity_commitment < -1e-6:
            raise ModelInputError("sponsor equity commitment cannot be negative")
        self.case_builder = OperatingCaseBuilder(config)

    def run(self, scenario: Scenario) -> ScenarioResult:
        senior_rate = self._senior_rate_for_scenario(scenario)
        annual_senior_principal = self.senior_debt_sized / self.config.senior_amortization_years
        senior_opening_balance = 0.0
        mezz_opening_balance = 0.0
        construction_account = 0.0
        guarantee_limit = self._guarantee_limit(scenario)
        guarantee_remaining = guarantee_limit

        equity_cashflows = [0.0 for _ in range(self.config.total_horizon_years + 1)]
        mezz_cashflows = [0.0 for _ in range(self.config.total_horizon_years + 1)]
        senior_cashflows = [0.0 for _ in range(self.config.total_horizon_years + 1)]
        rows: List[Dict[str, object]] = []

        for year in self.config.years:
            phase = "construction" if year in self.config.construction_years else "operations"
            row = self._blank_row(year, phase)
            row["senior_rate"] = senior_rate

            if phase == "construction":
                draw_pct = self.config.capex_draw_schedule[year]
                capex_outlay = self.config.total_capex * draw_pct
                senior_draw = self.senior_debt_sized * draw_pct
                mezz_draw = self.mezzanine_commitment * draw_pct
                equity_draw = self.sponsor_equity_commitment * draw_pct

                construction_account += senior_draw + mezz_draw + equity_draw - capex_outlay
                senior_opening_balance += senior_draw
                mezz_opening_balance += mezz_draw
                equity_cashflows[year] = -equity_draw
                mezz_cashflows[year] = -mezz_draw
                senior_cashflows[year] = -senior_draw

                row.update(
                    {
                        "capex_outlay": capex_outlay,
                        "senior_draw": senior_draw,
                        "mezzanine_draw": mezz_draw,
                        "equity_draw": equity_draw,
                        "construction_account": construction_account,
                        "senior_ending_balance": senior_opening_balance,
                        "mezzanine_ending_balance": mezz_opening_balance,
                        "asset_book_value": self._asset_book_value(year),
                    }
                )
                rows.append(row)
                continue

            revenue = self.case_builder.revenue_for_scenario(year, scenario)
            opex = self.case_builder.opex_for_scenario(year, scenario, revenue)
            cfads = revenue - opex
            maintenance_capex = revenue * self.config.maintenance_capex_pct_of_revenue
            working_capital_reserve = revenue * self.config.working_capital_reserve_pct_of_revenue
            cash_available = cfads - maintenance_capex - working_capital_reserve

            senior_interest_due = senior_opening_balance * senior_rate
            senior_principal_due = 0.0
            if year in self.config.senior_amortization_year_range and senior_opening_balance > 1e-6:
                senior_principal_due = min(annual_senior_principal, senior_opening_balance)
            senior_debt_service_due = senior_interest_due + senior_principal_due
            dscr = cfads / senior_debt_service_due if senior_debt_service_due > 0 else float("nan")

            senior_cash_available_before_guarantee = max(cash_available, 0.0)
            senior_shortfall_before_guarantee = max(0.0, senior_debt_service_due - senior_cash_available_before_guarantee)
            guarantee_draw = 0.0
            if scenario.use_first_loss_guarantee and senior_shortfall_before_guarantee > 0:
                guarantee_draw = min(guarantee_remaining, senior_shortfall_before_guarantee)
                guarantee_remaining -= guarantee_draw

            senior_payment_capacity = senior_cash_available_before_guarantee + guarantee_draw
            senior_interest_paid = min(senior_interest_due, senior_payment_capacity)
            senior_payment_capacity -= senior_interest_paid
            senior_principal_paid = min(senior_principal_due, max(senior_payment_capacity, 0.0))
            senior_payment_capacity -= senior_principal_paid
            senior_shortfall = max(
                0.0,
                senior_debt_service_due - senior_interest_paid - senior_principal_paid,
            )
            technical_default = senior_shortfall > 1e-6

            cash_used_for_senior = max(0.0, senior_interest_paid + senior_principal_paid - guarantee_draw)
            cash_after_senior = max(0.0, cash_available - cash_used_for_senior)
            senior_ending_balance = max(0.0, senior_opening_balance - senior_principal_paid)
            senior_cashflows[year] = senior_interest_paid + senior_principal_paid

            mezz_interest_due = mezz_opening_balance * self.config.mezzanine_interest_rate
            mezz_interest_paid = min(mezz_interest_due, cash_after_senior)
            cash_after_mezz_interest = cash_after_senior - mezz_interest_paid
            mezz_pik = max(0.0, mezz_interest_due - mezz_interest_paid)
            mezz_principal_paid = 0.0
            mezz_balance_after_pik = mezz_opening_balance + mezz_pik
            if year == self.config.total_horizon_years:
                mezz_principal_paid = min(mezz_balance_after_pik, max(cash_after_mezz_interest, 0.0))
                cash_after_mezz_interest -= mezz_principal_paid
            mezz_ending_balance = max(0.0, mezz_balance_after_pik - mezz_principal_paid)
            mezz_cashflows[year] = mezz_interest_paid + mezz_principal_paid

            equity_dividend = max(cash_after_mezz_interest, 0.0)
            equity_cashflows[year] = equity_dividend

            llcr = self._llcr_from_year(year, senior_opening_balance, scenario, senior_rate)
            oc_ratio = self._oc_ratio(year, senior_ending_balance, mezz_ending_balance)

            row.update(
                {
                    "revenue": revenue,
                    "opex": opex,
                    "cfads": cfads,
                    "maintenance_capex": maintenance_capex,
                    "working_capital_reserve": working_capital_reserve,
                    "cash_after_tier_1": cash_available,
                    "senior_opening_balance": senior_opening_balance,
                    "senior_interest_due": senior_interest_due,
                    "senior_principal_due": senior_principal_due,
                    "senior_interest_paid": senior_interest_paid,
                    "senior_principal_paid": senior_principal_paid,
                    "senior_shortfall": senior_shortfall,
                    "guarantee_draw": guarantee_draw,
                    "guarantee_remaining": guarantee_remaining,
                    "senior_ending_balance": senior_ending_balance,
                    "mezzanine_opening_balance": mezz_opening_balance,
                    "mezzanine_interest_due": mezz_interest_due,
                    "mezzanine_interest_paid": mezz_interest_paid,
                    "mezzanine_pik": mezz_pik,
                    "mezzanine_principal_paid": mezz_principal_paid,
                    "mezzanine_ending_balance": mezz_ending_balance,
                    "equity_dividend": equity_dividend,
                    "dscr": dscr,
                    "llcr": llcr,
                    "overcollateralization_ratio": oc_ratio,
                    "technical_default": technical_default,
                    "asset_book_value": self._asset_book_value(year),
                    "construction_account": construction_account,
                }
            )

            rows.append(row)
            senior_opening_balance = senior_ending_balance
            mezz_opening_balance = mezz_ending_balance

        annual_table = pd.DataFrame(rows).set_index("year")
        summary = self._build_summary(
            scenario=scenario,
            annual_table=annual_table,
            equity_cashflows=equity_cashflows,
            mezz_cashflows=mezz_cashflows,
            senior_cashflows=senior_cashflows,
            senior_rate=senior_rate,
            guarantee_limit=guarantee_limit,
        )
        breach_log = self._breach_log(annual_table)
        return ScenarioResult(scenario.name, annual_table, summary, breach_log)

    def _blank_row(self, year: int, phase: str) -> Dict[str, object]:
        return {
            "year": year,
            "phase": phase,
            "capex_outlay": 0.0,
            "senior_draw": 0.0,
            "mezzanine_draw": 0.0,
            "equity_draw": 0.0,
            "construction_account": 0.0,
            "revenue": 0.0,
            "opex": 0.0,
            "cfads": 0.0,
            "maintenance_capex": 0.0,
            "working_capital_reserve": 0.0,
            "cash_after_tier_1": 0.0,
            "senior_rate": self.config.senior_interest_rate,
            "senior_opening_balance": 0.0,
            "senior_interest_due": 0.0,
            "senior_principal_due": 0.0,
            "senior_interest_paid": 0.0,
            "senior_principal_paid": 0.0,
            "senior_shortfall": 0.0,
            "guarantee_draw": 0.0,
            "guarantee_remaining": 0.0,
            "senior_ending_balance": 0.0,
            "mezzanine_opening_balance": 0.0,
            "mezzanine_interest_due": 0.0,
            "mezzanine_interest_paid": 0.0,
            "mezzanine_pik": 0.0,
            "mezzanine_principal_paid": 0.0,
            "mezzanine_ending_balance": 0.0,
            "equity_dividend": 0.0,
            "dscr": float("nan"),
            "llcr": float("nan"),
            "overcollateralization_ratio": float("nan"),
            "technical_default": False,
            "asset_book_value": 0.0,
        }

    def _senior_rate_for_scenario(self, scenario: Scenario) -> Number:
        if not scenario.reduce_senior_spread:
            return self.config.senior_interest_rate
        reduced_spread = self.config.senior_credit_spread * (1.0 - self.config.guarantee_spread_reduction_factor)
        return self.config.senior_risk_free_rate + reduced_spread

    def _guarantee_limit(self, scenario: Scenario) -> Number:
        if not scenario.use_first_loss_guarantee:
            return 0.0
        return self.senior_debt_sized * self.config.guarantee_pct_of_senior_debt

    def _llcr_from_year(self, year: int, senior_opening_balance: Number, scenario: Scenario, senior_rate: Number) -> Number:
        if senior_opening_balance <= 1e-6 or year > self.config.senior_maturity_year:
            return float("nan")
        remaining_years = [y for y in self.config.senior_amortization_year_range if y >= year]
        cfads_values = []
        for y in remaining_years:
            revenue = self.case_builder.revenue_for_scenario(y, scenario)
            opex = self.case_builder.opex_for_scenario(y, scenario, revenue)
            cfads_values.append(revenue - opex)
        periods = np.arange(1, len(cfads_values) + 1, dtype=float)
        npv_remaining = float(np.sum(np.asarray(cfads_values) / np.power(1.0 + senior_rate, periods)))
        return npv_remaining / senior_opening_balance

    def _asset_book_value(self, year: int) -> Number:
        cumulative_capex = 0.0
        for draw_year, pct in self.config.capex_draw_schedule.items():
            if year >= draw_year:
                cumulative_capex += self.config.total_capex * pct
        if year <= max(self.config.construction_years):
            return cumulative_capex
        operating_year_index = year - self.config.operational_years[0] + 1
        annual_depreciation = self.config.total_capex / len(self.config.operational_years)
        return max(0.0, self.config.total_capex - annual_depreciation * operating_year_index)

    def _oc_ratio(self, year: int, senior_balance: Number, mezz_balance: Number) -> Number:
        debt_balance = senior_balance + mezz_balance
        if debt_balance <= 1e-6:
            return float("nan")
        return self._asset_book_value(year) / debt_balance

    def _build_summary(
        self,
        scenario: Scenario,
        annual_table: pd.DataFrame,
        equity_cashflows: List[Number],
        mezz_cashflows: List[Number],
        senior_cashflows: List[Number],
        senior_rate: Number,
        guarantee_limit: Number,
    ) -> Dict[str, Number]:
        equity_irr = FinancialMath.irr(equity_cashflows)
        mezz_yield = FinancialMath.irr(mezz_cashflows)
        senior_duration = FinancialMath.macaulay_duration(senior_rate, senior_cashflows)
        ending_senior = float(annual_table["senior_ending_balance"].iloc[-1])
        ending_mezz = float(annual_table["mezzanine_ending_balance"].iloc[-1])
        total_guarantee_draw = float(annual_table["guarantee_draw"].sum())
        min_dscr = float(annual_table["dscr"].dropna().min()) if annual_table["dscr"].notna().any() else float("nan")
        min_llcr = float(annual_table["llcr"].dropna().min()) if annual_table["llcr"].notna().any() else float("nan")
        senior_risk_spread_saving = self.config.senior_interest_rate - senior_rate
        wacc = self._wacc(senior_rate, mezz_yield)
        senior_default_years = int(annual_table["technical_default"].sum())

        return {
            "senior_debt_sized": self.senior_debt_sized,
            "sponsor_equity_commitment": self.sponsor_equity_commitment,
            "mezzanine_commitment": self.mezzanine_commitment,
            "senior_rate": senior_rate,
            "senior_spread_reduction": senior_risk_spread_saving,
            "wacc": wacc,
            "equity_irr": equity_irr,
            "mezzanine_realized_yield": mezz_yield,
            "senior_macaulay_duration": senior_duration,
            "minimum_dscr": min_dscr,
            "minimum_llcr": min_llcr,
            "ending_senior_balance": ending_senior,
            "ending_mezzanine_balance": ending_mezz,
            "guarantee_limit": guarantee_limit,
            "total_guarantee_drawn": total_guarantee_draw,
            "senior_default_year_count": senior_default_years,
        }

    def _wacc(self, senior_rate: Number, mezz_yield: Number) -> Number:
        senior_weight = self.senior_debt_sized / self.config.total_capex
        mezz_weight = self.mezzanine_commitment / self.config.total_capex
        equity_weight = max(0.0, self.sponsor_equity_commitment / self.config.total_capex)
        mezz_cost = mezz_yield if np.isfinite(mezz_yield) else self.config.mezzanine_interest_rate
        return float(
            senior_weight * senior_rate
            + mezz_weight * mezz_cost
            + equity_weight * self.config.sponsor_target_equity_return
        )

    def _breach_log(self, annual_table: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for year, row in annual_table.iterrows():
            dscr = row["dscr"]
            dscr_breach = bool(np.isfinite(dscr) and dscr < self.config.dscr_floor)
            default = bool(row["technical_default"])
            if dscr_breach or default:
                reasons = []
                if dscr_breach:
                    reasons.append(f"DSCR below {self.config.dscr_floor:.2f}x")
                if default:
                    reasons.append("senior shortfall after guarantee support")
                rows.append(
                    {
                        "year": int(year),
                        "dscr": float(dscr) if np.isfinite(dscr) else float("nan"),
                        "llcr": float(row["llcr"]) if np.isfinite(row["llcr"]) else float("nan"),
                        "senior_shortfall": float(row["senior_shortfall"]),
                        "guarantee_draw": float(row["guarantee_draw"]),
                        "reason": "; ".join(reasons),
                    }
                )
        if not rows:
            return pd.DataFrame(columns=["year", "dscr", "llcr", "senior_shortfall", "guarantee_draw", "reason"])
        return pd.DataFrame(rows)


class ScenarioRunner:
    """Coordinates base sizing and the three scenario runs."""

    def __init__(self, config: Optional[TransactionConfig] = None):
        self.config = config or TransactionConfig()
        self.config.validate()
        self.case_builder = OperatingCaseBuilder(self.config)
        self.sizer = SeniorDebtSizer(self.config)

    def base_case_senior_debt(self) -> Tuple[Number, pd.DataFrame]:
        base_cfads = self.case_builder.build_base_cfads()
        return self.sizer.size_from_base_case(base_cfads)

    def scenarios(self) -> List[Scenario]:
        stress_years = range(6, 10)
        stress_revenue_multipliers = {year: 0.75 for year in stress_years}
        stress_opex = {year: 0.45 for year in stress_years}
        return [
            Scenario(name="CASE 1 - BASE CASE"),
            Scenario(
                name="CASE 2 - SUPPLY CHAIN MARGIN COMPRESSION SHOCK",
                revenue_multipliers=stress_revenue_multipliers,
                opex_pct_overrides=stress_opex,
            ),
            Scenario(
                name="CASE 3 - FIRST-LOSS MULTILATERAL GUARANTEE FRAME",
                revenue_multipliers=stress_revenue_multipliers,
                opex_pct_overrides=stress_opex,
                use_first_loss_guarantee=True,
                reduce_senior_spread=True,
            ),
        ]

    def run_all(self) -> Dict[str, ScenarioResult]:
        sized_debt, _ = self.base_case_senior_debt()
        waterfall = ProjectFinanceWaterfall(self.config, sized_debt)
        return {scenario.name: waterfall.run(scenario) for scenario in self.scenarios()}


class TerminalReport:
    """Terminal output helpers. The tables are wide, so the report prints them in blocks."""

    MONEY_COLUMNS = [
        "capex_outlay",
        "senior_draw",
        "mezzanine_draw",
        "equity_draw",
        "revenue",
        "opex",
        "cfads",
        "maintenance_capex",
        "working_capital_reserve",
        "cash_after_tier_1",
        "senior_opening_balance",
        "senior_interest_due",
        "senior_principal_due",
        "senior_interest_paid",
        "senior_principal_paid",
        "senior_shortfall",
        "guarantee_draw",
        "guarantee_remaining",
        "senior_ending_balance",
        "mezzanine_opening_balance",
        "mezzanine_interest_due",
        "mezzanine_interest_paid",
        "mezzanine_pik",
        "mezzanine_principal_paid",
        "mezzanine_ending_balance",
        "equity_dividend",
        "asset_book_value",
    ]

    @staticmethod
    def money(value: Number) -> str:
        if pd.isna(value):
            return "-"
        return f"${value / 1_000_000:,.1f}m"

    @staticmethod
    def ratio(value: Number) -> str:
        if pd.isna(value) or not np.isfinite(value):
            return "-"
        return f"{value:,.2f}x"

    @staticmethod
    def pct(value: Number) -> str:
        if pd.isna(value) or not np.isfinite(value):
            return "-"
        return f"{value * 100:,.2f}%"

    def print_result(self, result: ScenarioResult) -> None:
        print("\n" + "=" * 110)
        print(result.scenario_name)
        print("=" * 110)
        self._print_summary(result.summary)
        self._print_waterfall_blocks(result.annual_table)
        self._print_breach_log(result.covenant_breaches)

    def print_all(self, results: Dict[str, ScenarioResult]) -> None:
        pd.set_option("display.width", 180)
        pd.set_option("display.max_columns", 40)
        pd.set_option("display.max_rows", 50)
        for result in results.values():
            self.print_result(result)

    def _print_summary(self, summary: Dict[str, Number]) -> None:
        summary_rows = [
            ("Total Senior Debt Capital Sized", self.money(summary["senior_debt_sized"])),
            ("Sponsor Equity Commitment", self.money(summary["sponsor_equity_commitment"])),
            ("Mezzanine Commitment", self.money(summary["mezzanine_commitment"])),
            ("Senior Debt Coupon", self.pct(summary["senior_rate"])),
            ("Senior Spread Reduction", self.pct(summary["senior_spread_reduction"])),
            ("Transaction WACC", self.pct(summary["wacc"])),
            ("Sponsor Equity IRR", self.pct(summary["equity_irr"])),
            ("Mezzanine Realized Yield", self.pct(summary["mezzanine_realized_yield"])),
            ("Senior Macaulay Duration", f"{summary['senior_macaulay_duration']:.2f} yrs"),
            ("Minimum DSCR", self.ratio(summary["minimum_dscr"])),
            ("Minimum LLCR", self.ratio(summary["minimum_llcr"])),
            ("Guarantee Limit", self.money(summary["guarantee_limit"])),
            ("Total Guarantee Drawn", self.money(summary["total_guarantee_drawn"])),
            ("Senior Default Year Count", f"{int(summary['senior_default_year_count'])}"),
        ]
        table = pd.DataFrame(summary_rows, columns=["metric", "value"])
        print("\nSummary")
        print(table.to_string(index=False))

    def _print_waterfall_blocks(self, table: pd.DataFrame) -> None:
        construction_cols = [
            "phase",
            "capex_outlay",
            "senior_draw",
            "mezzanine_draw",
            "equity_draw",
            "construction_account",
            "asset_book_value",
        ]
        operations_cols = [
            "revenue",
            "opex",
            "cfads",
            "maintenance_capex",
            "working_capital_reserve",
            "cash_after_tier_1",
            "equity_dividend",
        ]
        debt_cols = [
            "senior_opening_balance",
            "senior_interest_due",
            "senior_principal_due",
            "senior_shortfall",
            "guarantee_draw",
            "senior_ending_balance",
            "mezzanine_ending_balance",
        ]
        covenant_cols = ["dscr", "llcr", "overcollateralization_ratio", "technical_default"]

        print("\nConstruction ledger")
        print(self._format_table(table[construction_cols]).to_string())
        print("\nOperating cash flow waterfall")
        print(self._format_table(table[operations_cols]).to_string())
        print("\nDebt balances and protection layer")
        print(self._format_table(table[debt_cols]).to_string())
        print("\nCovenant path")
        print(self._format_table(table[covenant_cols]).to_string())

    def _print_breach_log(self, breach_log: pd.DataFrame) -> None:
        print("\nCovenant breach log")
        if breach_log.empty:
            print("No covenant breaches or senior technical defaults logged.")
            return
        formatted = breach_log.copy()
        if "dscr" in formatted:
            formatted["dscr"] = formatted["dscr"].map(self.ratio)
        if "llcr" in formatted:
            formatted["llcr"] = formatted["llcr"].map(self.ratio)
        for col in ["senior_shortfall", "guarantee_draw"]:
            if col in formatted:
                formatted[col] = formatted[col].map(self.money)
        print(formatted.to_string(index=False))

    def _format_table(self, table: pd.DataFrame) -> pd.DataFrame:
        formatted = table.copy()
        for col in formatted.columns:
            if col in self.MONEY_COLUMNS:
                formatted[col] = formatted[col].map(self.money)
            elif col in {"dscr", "llcr", "overcollateralization_ratio"}:
                formatted[col] = formatted[col].map(self.ratio)
            elif col == "senior_rate":
                formatted[col] = formatted[col].map(self.pct)
        return formatted


def run_terminal_model() -> Dict[str, ScenarioResult]:
    runner = ScenarioRunner()
    results = runner.run_all()
    TerminalReport().print_all(results)
    return results


if __name__ == "__main__":
    run_terminal_model()
