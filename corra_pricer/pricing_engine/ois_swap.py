"""
Vanilla Canadian CORRA OIS pricer.

Floating leg pricing note (important interview talking point):
Under single-curve OIS discounting - where the same curve is used to both
forecast the compounded CORRA rate over each period AND discount the
cashflows - the floating leg's present value telescopes:

    PV_float = notional * (DF(t_start) - DF(t_end))

This holds because, absent any spread, the forecast compounded rate for a
period [t_a, t_b] is exactly (DF(t_a)/DF(t_b) - 1)/accrual, so each floating
cashflow's PV is notional * (DF(t_a) - DF(t_b)); summing over consecutive
periods telescopes to notional * (DF(t_start) - DF(t_end)). No cashflow
projection loop is actually needed for a single-curve OIS floating leg --
this is *the* reason OIS swaps are simple to value.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from corra_pricer.curve_builder.curve import YieldCurve
from corra_pricer.pricing_engine.conventions import (
    DAYCOUNT_CONVENTIONS,
    generate_payment_schedule,
    year_fraction,
)


@dataclass
class CorraOISSwap:
    trade_date: dt.date
    effective_date: dt.date
    maturity_date: dt.date
    notional: float
    fixed_rate: float  # decimal, e.g. 0.03 for 3%
    pay_fixed: bool = True
    payments_per_year: int = 1

    # Convention parameters. Every default reproduces the platform's
    # original ACT/365F, unadjusted, short-first-stub behavior exactly --
    # existing callers are unaffected unless they opt into these.
    fixed_leg_daycount: str = "ACT/365F"
    business_day_convention: str = "None"
    calendar_name: str = "Weekend Only"
    stub: str = "short_first"

    payment_dates: list[dt.date] = field(init=False)

    def __post_init__(self):
        self.payment_dates = generate_payment_schedule(
            self.effective_date, self.maturity_date, self.payments_per_year,
            stub=self.stub, business_day_convention=self.business_day_convention,
            calendar_name=self.calendar_name,
        )

    def _t(self, date: dt.date) -> float:
        """Discounting time-to-cashflow is always ACT/365F - the curve's
        own time convention, independent of the fixed leg's accrual
        day count (see conventions.py module docstring)."""
        return year_fraction(self.trade_date, date)

    def fixed_leg_cashflows(self) -> list[dict]:
        daycount_fn = DAYCOUNT_CONVENTIONS[self.fixed_leg_daycount]
        cashflows = []
        prev_date = self.effective_date
        for pay_date in self.payment_dates:
            accrual = daycount_fn(prev_date, pay_date)
            amount = self.notional * self.fixed_rate * accrual
            cashflows.append({
                "start": prev_date, "end": pay_date, "accrual": accrual, "amount": amount,
            })
            prev_date = pay_date
        return cashflows

    def fixed_leg_pv(self, curve: YieldCurve) -> float:
        pv = 0.0
        for cf in self.fixed_leg_cashflows():
            df = curve.discount_factor(self._t(cf["end"]))
            pv += cf["amount"] * df
        return pv

    def floating_leg_pv(self, curve: YieldCurve) -> float:
        """Telescoping single-curve OIS floating leg PV: notional * (DF(start) - DF(end))."""
        df_start = curve.discount_factor(self._t(self.effective_date))
        df_end = curve.discount_factor(self._t(self.maturity_date))
        return self.notional * (df_start - df_end)

    def annuity(self, curve: YieldCurve) -> float:
        """Sum of accrual_i * DF(t_i) for the fixed leg - the denominator of the fair rate."""
        total = 0.0
        for cf in self.fixed_leg_cashflows():
            total += cf["accrual"] * curve.discount_factor(self._t(cf["end"]))
        return total

    def fair_rate(self, curve: YieldCurve) -> float:
        df_start = curve.discount_factor(self._t(self.effective_date))
        df_end = curve.discount_factor(self._t(self.maturity_date))
        return self.notional * (df_start - df_end) / (self.notional * self.annuity(curve))

    def npv(self, curve: YieldCurve) -> float:
        fixed_pv = self.fixed_leg_pv(curve)
        float_pv = self.floating_leg_pv(curve)
        if self.pay_fixed:
            return float_pv - fixed_pv
        return fixed_pv - float_pv

    def summary(self, curve: YieldCurve) -> dict:
        return {
            "fixed_leg_pv": self.fixed_leg_pv(curve),
            "floating_leg_pv": self.floating_leg_pv(curve),
            "npv": self.npv(curve),
            "fair_rate_pct": self.fair_rate(curve) * 100,
            "fixed_rate_pct": self.fixed_rate * 100,
            "num_payments": len(self.payment_dates),
        }
