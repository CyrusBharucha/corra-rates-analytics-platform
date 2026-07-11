"""
Risk engine for CorraOISSwap: DV01, PV01, key-rate DV01, and convexity, all
via manual bump-and-reprice (no analytic-derivative shortcuts, no QuantLib).

--- Interview notes, kept inline because this module exists to be explained ---

DV01 ("dollar value of a basis point"): how much a swap's NPV changes for a
1bp parallel move in the discounting curve. It's the primary hedge ratio a
rates desk uses -- if you're short $X of DV01, you buy enough of an offsetting
instrument (a bond, a swap, a future) with +$X of DV01 to flatten your P&L
sensitivity to small rate moves. Traders hedge DV01 because unhedged, a
single-basis-point-a-day move on a large notional swap book is real P&L,
and desks are typically mandated to run near-flat rate risk intraday.

Sign convention here: DV01 = NPV(curve +1bp) - NPV(curve). A pay-fixed swap
gains value when rates rise (you're locked into paying a below-market fixed
rate), so its DV01 is POSITIVE under this convention. A receive-fixed swap's
DV01 is NEGATIVE by the same convention -- it behaves like a long bond
(gains when rates fall), so on the standard bond convention (duration = "how
much you lose when yields rise") a payer swap has *negative* duration: it is
economically short a bond (short duration), a receiver swap is economically
long a bond (positive duration, same as duration convention for a bond
holder). This directly answers "why does a pay-fixed swap have negative
duration": because paying fixed is equivalent to being short a fixed-coupon
bond and long floating-rate cash.

Key-rate duration (KRD): a single parallel DV01 hides *where* on the curve
the risk sits. Two swaps can have identical total DV01 (e.g. a 2Y payer and
a 10Y payer sized to match) but completely different curve exposure -- the
2Y swap is exposed to front-end/policy-rate moves, the 10Y to term-premium
moves. A steepener or flattener will P&L them oppositely even with equal
DV01. KRD buckets that risk by tenor using triangular ("tent") shocks
(see corra_pricer/curve_builder/shocked_curve.py) that partition a parallel
shift exactly across buckets, which is why summing all KRD buckets recovers
(approximately) the total parallel DV01.

Convexity: DV01 is a first-order (linear) approximation of a nonlinear
price/rate relationship. Convexity captures the curvature -- how much DV01
itself changes as rates move. It matters because a hedge sized on DV01 alone
will be well-hedged for a 1bp move but increasingly mis-hedged for larger
moves; desks with large convexity exposure re-hedge more frequently ("gamma
trading") and convexity carries its own P&L in volatile markets.
"""
from __future__ import annotations

from corra_pricer.curve_builder.shocked_curve import key_rate_shift, parallel_shift
from corra_pricer.risk_engine.risk_report import RiskReport

DEFAULT_KRD_BUCKETS = [2.0, 5.0, 10.0, 30.0]
DEFAULT_KRD_LABELS = {2.0: "2Y", 5.0: "5Y", 10.0: "10Y", 30.0: "30Y"}


def compute_dv01(swap, curve, bump_bp: float = 1.0) -> float:
    """DV01 = NPV(curve shifted +bump_bp) - NPV(base curve).
    Positive for a pay-fixed swap, negative for receive-fixed, per the sign
    convention documented at the top of this module.
    """
    base_npv = swap.npv(curve)
    shifted_curve = parallel_shift(curve, bump_bp)
    shifted_npv = swap.npv(shifted_curve)
    return shifted_npv - base_npv


def compute_pv01(swap, curve) -> float:
    """PV01: the dollar value of 1bp on the fixed leg's annuity alone,
    independent of pay/receive direction and independent of how far the
    swap's fixed rate is from the fair rate. This is distinct from DV01:
    DV01 is the *net* swap sensitivity (both legs, at the swap's actual
    moneyness), PV01 is a leg-level building block traders use to convert a
    rate/spread move into a dollar amount (e.g. "5Y swap spread moved 2bp,
    PV01 is $4,850/bp -> ~$9,700 P&L"). At the fair rate (NPV = 0), |DV01|
    and PV01 are close but not identical, since DV01 also picks up the
    floating leg's sensitivity.
    """
    return swap.notional * swap.annuity(curve) * 0.0001


def compute_krd(swap, curve, buckets: list[float] | None = None, bump_bp: float = 1.0) -> dict[str, float]:
    """Key-rate DV01 for each bucket: shock only that bucket's tent, reprice, diff."""
    buckets = buckets or DEFAULT_KRD_BUCKETS
    base_npv = swap.npv(curve)
    krd = {}
    for bucket_time in buckets:
        shocked = key_rate_shift(curve, bucket_time, bump_bp, buckets)
        shocked_npv = swap.npv(shocked)
        label = DEFAULT_KRD_LABELS.get(bucket_time, f"{bucket_time:g}Y")
        krd[label] = shocked_npv - base_npv
    return krd


def compute_convexity(swap, curve, bump_bp: float = 1.0) -> float:
    """Dollar convexity via central second difference:
        convexity = NPV(+bump) + NPV(-bump) - 2 * NPV(base)
    This is left un-normalized (dollars per (1bp)^2) rather than divided by
    NPV(base), because a swap's NPV can be at or near zero (e.g. when priced
    at the fair rate) -- dividing by price, the textbook bond-convexity
    formula, blows up or is undefined for an at-par swap. The dollar/notional
    form is the version that's actually usable for a swap book.
    """
    base_npv = swap.npv(curve)
    up_curve = parallel_shift(curve, bump_bp)
    down_curve = parallel_shift(curve, -bump_bp)
    up_npv = swap.npv(up_curve)
    down_npv = swap.npv(down_curve)
    return up_npv + down_npv - 2 * base_npv


def compute_dollar_duration(swap, curve, bump_bp: float = 100.0) -> float:
    """'Dollar duration' here is DV01 scaled to a 100bp ('1%') move rather
    than 1bp -- same bump-and-reprice as compute_dv01, just a different
    move size, since "dollar duration" and "DV01" are the same underlying
    concept quoted at different conventional magnitudes on different desks.
    """
    return compute_dv01(swap, curve, bump_bp=bump_bp)


def compute_gamma_dv01(swap, curve, bump_bp: float = 50.0) -> float:
    """How much DV01 itself changes for a bump_bp move -- i.e. gamma
    expressed in DV01 terms rather than dollar-convexity terms
    (compute_convexity). Useful because 'my DV01 hedge is off by $X per
    50bp of rates moving' is a more directly actionable risk-management
    statement than a raw dollar-convexity number.
    """
    base_dv01 = compute_dv01(swap, curve, bump_bp=1.0)
    shifted_curve = parallel_shift(curve, bump_bp)
    shifted_dv01 = compute_dv01(swap, shifted_curve, bump_bp=1.0)
    return shifted_dv01 - base_dv01


def compute_leg_dv01(swap, curve, bump_bp: float = 1.0) -> dict[str, float]:
    """DV01 of the fixed leg and floating leg separately (each leg's own
    PV bumped and repriced in isolation), which sum to the net swap DV01.
    Splits out where a swap's rate sensitivity actually lives -- useful
    when, e.g., explaining why a deep-in-the-money swap's net DV01 looks
    smaller than either leg's DV01 alone (the legs are partially offsetting).
    """
    base_fixed = swap.fixed_leg_pv(curve)
    base_float = swap.floating_leg_pv(curve)
    shifted = parallel_shift(curve, bump_bp)
    shifted_fixed = swap.fixed_leg_pv(shifted)
    shifted_float = swap.floating_leg_pv(shifted)
    return {
        "fixed_leg_dv01": shifted_fixed - base_fixed,
        "floating_leg_dv01": shifted_float - base_float,
    }


def compute_fixed_leg_macaulay_duration(swap, curve) -> float:
    """Macaulay duration (PV-weighted average time to cashflow) of the
    FIXED LEG only -- not the net swap. A net swap's NPV can sit at or
    near zero (e.g. priced at its own fair rate), which makes a
    price-weighted "duration" for the whole swap ill-defined (same
    divide-by-near-zero problem documented on compute_convexity). The
    fixed leg alone is a straightforward bond-like positive cashflow
    stream, so its Macaulay duration is always well-defined.
    """
    from corra_pricer.pricing_engine.conventions import year_fraction

    total_pv = 0.0
    weighted_time = 0.0
    for cf in swap.fixed_leg_cashflows():
        t = year_fraction(swap.trade_date, cf["end"])
        pv = cf["amount"] * curve.discount_factor(t)
        total_pv += pv
        weighted_time += t * pv
    if total_pv == 0:
        return 0.0
    return weighted_time / total_pv


def compute_extended_risk_metrics(swap, curve) -> dict:
    """Bundles the additional risk views above into one call -- kept
    separate from RiskReport/build_risk_report (Module 4's original,
    stable output) so existing callers are unaffected; this is purely
    additive."""
    leg_dv01 = compute_leg_dv01(swap, curve)
    return {
        "dollar_duration_100bp": compute_dollar_duration(swap, curve),
        "gamma_dv01_50bp": compute_gamma_dv01(swap, curve),
        "fixed_leg_dv01": leg_dv01["fixed_leg_dv01"],
        "floating_leg_dv01": leg_dv01["floating_leg_dv01"],
        "fixed_leg_macaulay_duration_years": compute_fixed_leg_macaulay_duration(swap, curve),
    }


def build_risk_report(swap, curve, buckets: list[float] | None = None, bump_bp: float = 1.0) -> RiskReport:
    return RiskReport(
        notional=swap.notional,
        pay_fixed=swap.pay_fixed,
        fixed_rate_pct=swap.fixed_rate * 100,
        curve_label=curve.label,
        dv01=compute_dv01(swap, curve, bump_bp),
        pv01=compute_pv01(swap, curve),
        krd=compute_krd(swap, curve, buckets, bump_bp),
        convexity=compute_convexity(swap, curve, bump_bp),
    )
