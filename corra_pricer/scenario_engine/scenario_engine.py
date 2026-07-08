"""
Scenario engine: answers "what happens if rates move?" for a given swap,
against the named scenario catalog in scenarios.py, an arbitrary
user-defined key-rate shock, or a Monte Carlo distribution of random shocks.

Every scenario is built by stacking key-rate bucket shocks (see
curve_builder/shocked_curve.py), so scenario curves are continuous shocks
just like the risk engine's KRD shocks -- a scenario is really just a
custom-shaped set of simultaneous key-rate bumps.

PnL attribution: because the risk engine already computes each bucket's
DV01 (dollars per 1bp at that bucket), a *linear* (first-order) estimate of
a scenario's P&L is just sum(KRD_bucket * scenario_shock_bucket_bp). The
engine reports this alongside the true, fully repriced NPV change; the gap
between them is the convexity/cross-term residual the linear estimate
misses -- itself a useful risk number (large residual = the position has
meaningful convexity, so DV01-based hedges alone won't track well through
this scenario).

Monte Carlo note: shocks are drawn independently per bucket from a Normal
distribution (mean 0, user-specified standard deviation in bp) -- a
simplification (real curve moves are correlated across buckets, most
strongly between adjacent tenors), documented here rather than silently
assumed. It's still a legitimate way to explore the *distribution* of P&L
outcomes under random, unstructured curve noise, distinct from the
deterministic named scenarios above.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from corra_pricer.curve_builder.shocked_curve import key_rate_shift
from corra_pricer.risk_engine.risk_engine import DEFAULT_KRD_BUCKETS, compute_dv01, compute_krd
from corra_pricer.scenario_engine.scenarios import SCENARIO_CATALOG, Scenario

BUCKET_LABELS = {2.0: "2Y", 5.0: "5Y", 10.0: "10Y", 30.0: "30Y"}


def build_scenario_curve(curve, scenario: Scenario, buckets: list[float] | None = None):
    return _apply_bucket_shocks(curve, scenario.bucket_shocks_bp, buckets)


def _apply_bucket_shocks(curve, bucket_shocks_bp: dict, buckets: list[float] | None = None):
    buckets = buckets or DEFAULT_KRD_BUCKETS
    shocked = curve
    for bucket_time in buckets:
        bump = bucket_shocks_bp.get(bucket_time, 0.0)
        if bump != 0.0:
            shocked = key_rate_shift(shocked, bucket_time, bump, buckets)
    return shocked


@dataclass
class ScenarioResult:
    scenario_name: str
    description: str
    category: str
    bucket_shocks_bp: dict

    npv_before: float
    npv_after: float
    npv_change: float

    dv01_before: float
    dv01_after: float
    dv01_change: float

    pnl_attribution_bp: dict = field(default_factory=dict)  # linear, per-bucket KRD-based estimate
    attribution_total: float = 0.0
    attribution_residual: float = 0.0  # npv_change - attribution_total (convexity/cross-term effect)

    def to_dict(self) -> dict:
        return {
            "scenario": self.scenario_name,
            "category": self.category,
            "npv_before": self.npv_before,
            "npv_after": self.npv_after,
            "npv_change": self.npv_change,
            "dv01_before": self.dv01_before,
            "dv01_after": self.dv01_after,
            "dv01_change": self.dv01_change,
            "attribution_total": self.attribution_total,
            "attribution_residual": self.attribution_residual,
        }


def _run_bucket_shock_scenario(
    swap, curve, bucket_shocks_bp: dict, name: str, description: str, category: str,
    buckets: list[float] | None = None,
) -> ScenarioResult:
    buckets = buckets or DEFAULT_KRD_BUCKETS

    npv_before = swap.npv(curve)
    dv01_before = compute_dv01(swap, curve)
    krd_before = compute_krd(swap, curve, buckets)

    scenario_curve = _apply_bucket_shocks(curve, bucket_shocks_bp, buckets)
    npv_after = swap.npv(scenario_curve)
    dv01_after = compute_dv01(swap, scenario_curve)

    pnl_attribution_bp = {}
    for bucket_time in buckets:
        label = BUCKET_LABELS.get(bucket_time, f"{bucket_time:g}Y")
        shock_bp = bucket_shocks_bp.get(bucket_time, 0.0)
        pnl_attribution_bp[label] = krd_before[label] * shock_bp

    attribution_total = sum(pnl_attribution_bp.values())
    npv_change = npv_after - npv_before

    return ScenarioResult(
        scenario_name=name,
        description=description,
        category=category,
        bucket_shocks_bp=dict(bucket_shocks_bp),
        npv_before=npv_before,
        npv_after=npv_after,
        npv_change=npv_change,
        dv01_before=dv01_before,
        dv01_after=dv01_after,
        dv01_change=dv01_after - dv01_before,
        pnl_attribution_bp=pnl_attribution_bp,
        attribution_total=attribution_total,
        attribution_residual=npv_change - attribution_total,
    )


def run_scenario(swap, curve, scenario_name: str, buckets: list[float] | None = None) -> ScenarioResult:
    if scenario_name not in SCENARIO_CATALOG:
        raise KeyError(f"Unknown scenario '{scenario_name}'. Available: {sorted(SCENARIO_CATALOG)}")
    scenario = SCENARIO_CATALOG[scenario_name]
    return _run_bucket_shock_scenario(
        swap, curve, scenario.bucket_shocks_bp, scenario.name, scenario.description,
        scenario.category, buckets,
    )


def run_custom_scenario(
    swap, curve, bucket_shocks_bp: dict, name: str = "custom", buckets: list[float] | None = None,
) -> ScenarioResult:
    """Same engine as run_scenario(), but for an arbitrary user-supplied
    {bucket_time: shock_bp} dict instead of a named catalog entry -- the
    "user-defined shock" capability."""
    description = ", ".join(
        f"{BUCKET_LABELS.get(b, f'{b:g}Y')} {v:+g}bp" for b, v in sorted(bucket_shocks_bp.items())
    )
    return _run_bucket_shock_scenario(swap, curve, bucket_shocks_bp, name, description, "user_defined", buckets)


def run_all_scenarios(swap, curve, buckets: list[float] | None = None) -> list[ScenarioResult]:
    return [run_scenario(swap, curve, name, buckets) for name in SCENARIO_CATALOG]


def scenario_summary_table(swap, curve, buckets: list[float] | None = None):
    import pandas as pd
    results = run_all_scenarios(swap, curve, buckets)
    return pd.DataFrame([r.to_dict() for r in results])


def run_monte_carlo_scenarios(
    swap, curve, n_simulations: int = 200, shock_std_bp: float = 25.0,
    buckets: list[float] | None = None, seed: int | None = None,
):
    """Draws n_simulations independent random key-rate shocks (Normal(0,
    shock_std_bp) per bucket, buckets uncorrelated -- see module docstring)
    and fully reprices the swap under each one. Returns a DataFrame with one
    row per simulation: the shock applied at each bucket, plus the
    resulting NPV change and DV01 change. Deliberately skips the KRD-based
    linear attribution computed for named/custom scenarios (4 extra
    reprices per call) to stay fast across hundreds of simulations -- the
    point of a Monte Carlo run is the P&L *distribution*, not per-draw
    attribution detail.
    """
    import pandas as pd

    buckets = buckets or DEFAULT_KRD_BUCKETS
    rng = np.random.default_rng(seed)

    npv_before = swap.npv(curve)
    dv01_before = compute_dv01(swap, curve)

    rows = []
    for i in range(n_simulations):
        shocks = {b: float(rng.normal(0.0, shock_std_bp)) for b in buckets}
        shocked_curve = _apply_bucket_shocks(curve, shocks, buckets)
        npv_after = swap.npv(shocked_curve)
        dv01_after = compute_dv01(swap, shocked_curve)
        row = {"simulation": i, "npv_change": npv_after - npv_before, "dv01_change": dv01_after - dv01_before}
        for b in buckets:
            row[f"{BUCKET_LABELS.get(b, f'{b:g}Y')}_shock_bp"] = shocks[b]
        rows.append(row)

    return pd.DataFrame(rows)
