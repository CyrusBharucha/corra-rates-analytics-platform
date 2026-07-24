import sys
from pathlib import Path


def _ensure_project_root_on_path() -> None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "corra_pricer").is_dir() and (parent / "requirements.txt").exists():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return
    raise RuntimeError("Could not locate the project root (expected a 'corra_pricer' package "
                        "and requirements.txt in a parent directory).")


_ensure_project_root_on_path()

import streamlit as st

from corra_pricer.dashboard.components import styling

styling.apply_page_config("Documentation")
styling.render_header("Documentation", "Architecture, methodology, and known limitations")

tab_arch, tab_price, tab_curve, tab_risk, tab_limits = st.tabs(
    ["Architecture", "Pricing Methodology", "Curve & Bootstrap", "Risk Methodology",
     "Assumptions & Limitations"]
)

# ---------------------------------------------------------------------------
with tab_arch:
    st.markdown("### System Architecture")
    st.markdown(
        "Six backend modules, each independently testable, feeding a Streamlit dashboard that "
        "contains **no pricing or risk logic of its own**, every number displayed is computed by "
        "calling the backend directly."
    )
    st.markdown(
        """
<div style="font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; line-height: 1.9;
            background: var(--bg-card); border: 1px solid var(--border-subtle); border-radius: 10px;
            padding: 1.5rem; white-space: pre;">
<span style="color:#3FA9F5">market_data</span>          Bank of Canada Valet API (CORRA + GoC benchmark yields)
     |
     v
<span style="color:#3FA9F5">curve_builder</span>        Manual bootstrap (root-find), 3 interpolation methods
     |
     +-----------------+-----------------+
     v                 v                 v
<span style="color:#3FA9F5">pricing_engine</span>   <span style="color:#3DDC84">risk_engine</span>      <span style="color:#B48EF0">scenario_engine</span>
CorraOISSwap     DV01/PV01/KRD    41 scenarios,
fair rate, NPV   duration/gamma   custom shocks,
                                  Monte Carlo
     |                 |                 |
     +-----------------+-----------------+
                        v
                <span style="color:#F5C242">analytics.historical_replay</span>
                Prices the same swap on real historical dates
                        |
                        v
                <span style="color:#E8EAED">dashboard/</span>  (Streamlit, presentation only)
                components/data_access.py  <-- the ONLY file that
                                                imports backend modules
                pages/  1 Market  2 Pricing  3 Risk
                        4 Scenarios  5 Historical Replay  6 Documentation
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown("#### Why this structure")
    st.markdown(
        """
- **`data_access.py` is the only boundary.** Every page imports from it (plus pure-presentation
  `charts.py`/`tables.py`); nothing in `pages/` calls `market_data`, `curve_builder`,
  `pricing_engine`, `risk_engine`, `scenario_engine`, or `analytics` directly. This means the
  entire pricing/risk logic can be exercised and tested with zero UI code involved, which is
  exactly how the 270-test suite works.
- **No QuantLib.** Curve bootstrapping, discounting, risk, and scenario math are all original
  code, so every formula can be explained and defended in an interview rather than treated as a
  black box.
- **Caching boundary.** `st.cache_data` is used for plain dict/DataFrame-returning network calls;
  `st.cache_resource` is used for anything returning a `YieldCurve`, since `YieldCurve` stores its
  interpolator as a closure, which the standard `pickle` module (used by `st.cache_data`) cannot
  serialize.
"""
    )

# ---------------------------------------------------------------------------
with tab_price:
    st.markdown("### Vanilla CORRA OIS Pricing")
    st.markdown(
        """
A `CorraOISSwap` is defined by trade date, effective date, maturity date, notional, fixed rate,
direction (pay/receive fixed), and payment frequency, plus convention parameters (day count, stub,
business day convention, calendar) that default to the platform's baseline behavior.

**Fixed leg**: standard, for each period, `notional x fixed_rate x accrual x DF(t)`, summed.
Accrual uses whichever day count is selected (ACT/365F, ACT/360, 30/360, or ACT/ACT).

**Floating leg: the telescoping identity.** Under single-curve OIS discounting (the same curve
forecasts the compounded CORRA rate *and* discounts the cashflows), the floating leg's PV
collapses to:
"""
    )
    st.code("PV_float = notional * (DF(t_effective) - DF(t_maturity))", language=None)
    st.markdown(
        """
No cashflow projection loop is needed. This holds because the forecast compounded rate for any
period `[t_a, t_b]` is exactly implied by `(DF(t_a)/DF(t_b) - 1) / accrual`; each floating
cashflow's PV is therefore `notional * (DF(t_a) - DF(t_b))`, and summing consecutive periods
telescopes to the single expression above. This is *the* reason OIS floating legs are cheap to
value, and it's the platform's answer to "how does your floating leg work" in an interview.

**Fair rate**: solving NPV = 0 for the fixed rate gives
"""
    )
    st.code("fair_rate = (DF(t_effective) - DF(t_maturity)) / annuity", language=None)
    st.markdown(
        "where `annuity = sum(accrual_i * DF(t_i))` over the fixed leg, the same denominator "
        "used to convert a rate difference into a dollar PV01."
    )
    st.write("")
    st.markdown("#### Day count consistency (verified)")
    st.markdown(
        """
The selected fixed-leg day count (`fixed_leg_daycount`) is read in exactly **one** place,
`fixed_leg_cashflows()` - and every downstream calculation (`fixed_leg_pv`, `annuity`,
`fair_rate`, `npv`) derives from that same cashflow list, so there is no risk of the day count
being applied inconsistently across the pricer.

**Discounting time-to-cashflow is always ACT/365 Fixed**, regardless of the fixed leg's accrual
day count, this is the curve's own time convention (a separate concept from leg accrual) and is
not user-selectable. The floating leg's day count is likewise not separately selectable: the
telescoping identity is a pure discount-factor relationship with no explicit compounding
calculation to apply a convention to.
"""
    )
    st.write("")
    st.markdown("#### Forward-starting and IMM-dated swaps, integration status")
    st.success(
        "**Supported on both the Pricing page and Historical Replay.** "
        "`analytics.historical_replay.price_swap_as_of()` accepts the same convention and "
        "start-date parameters as the Pricing page's swap builder (day count, business day "
        "convention, calendar, stub, spot lag, and IMM start), applied identically across every "
        "checkpoint in a multi-date comparison. `as_of_date` always remains the market-data "
        "reference date, these parameters only move the swap's own effective date, exactly as "
        "the Pricing page lets trade date and effective date diverge without changing which "
        "curve prices the swap. IMM start resolves the next IMM date separately for each "
        "historical checkpoint, since a single shared IMM date wouldn't be meaningful across "
        "different historical dates."
    )

# ---------------------------------------------------------------------------
with tab_curve:
    st.markdown("### Curve Construction: Manual Bootstrap")
    st.markdown(
        """
The discounting curve is bootstrapped from two live Bank of Canada Valet API sources:
- **CORRA fixing** (`AVG.INTWO`) anchors the very short end.
- **GoC benchmark bond yields** (2Y/3Y/5Y/7Y/10Y/30Y), treated as semi-annual-pay par bond yields,
  bootstrap the rest of the curve.

For each bond node, the bootstrap **root-finds** (via `scipy.optimize.brentq`, not a closed-form
formula) the discount factor that makes a par bond with that coupon and maturity price back to
exactly 100, given the discount factors already solved for at shorter maturities.

**The subtlety**: coupon dates don't line up with quoted maturities, e.g. building the 10Y node
needs coupons at 7.5Y, 8.5Y, 9.5Y, but only nodes up to 7Y exist yet at that point. The unknown
zero rate at the new node is used *simultaneously* for linearly interpolating those gap coupons
**and** discounting the final cashflow, solved so the bond reprices to exactly par, the standard
self-consistent single-pass bootstrap.

**Verified correctness**: `reprice_par_bonds()` independently reprices every input bond off the
*final* curve (through whichever interpolation method was chosen) and reports the residual vs.
par. For linear interpolation this residual is ~1e-9 (floating-point noise). For log-linear-DF or
cubic-spline curves, a small but real residual (up to ~$0.67 per $100 face at the 30Y node) shows
up, because the bootstrap's internal gap-solver always assumes linear-on-zero-rate, so switching
the curve's *final* interpolation method can reintroduce a small repricing error. This is shown
live on the Market page's Bootstrap Diagnostics tab, not hidden.
"""
    )
    st.write("")
    st.markdown("#### Interpolation methods")
    st.markdown(
        """
- **Linear** on zero rate (default).
- **Log-linear on discount factor**, equivalent to piecewise-constant instantaneous forward rates.
- **Cubic spline** (natural boundary conditions).

All three are built from scratch (no QuantLib) and can be compared directly on the Market page.
"""
    )
    st.write("")
    st.markdown("#### GoC yields as an OIS proxy, the central methodological caveat")
    st.info(
        "Live CORRA OIS swap quotes are not publicly available anywhere (Bloomberg/Refinitiv "
        "only), so this platform bootstraps its discounting curve from the Bank of Canada's "
        "published GoC benchmark bond yields, used and documented as an OIS proxy throughout. "
        "In practice, OIS curves trade at a small spread to the GoC bond curve (the swap spread) "
        "reflecting funding, repo, and balance-sheet dynamics, this platform does not attempt to "
        "model that spread; it prices directly off the bond-curve proxy."
    )

# ---------------------------------------------------------------------------
with tab_risk:
    st.markdown("### Risk Engine: Bump-and-Reprice, No Analytic Derivatives")
    st.markdown(
        """
Every risk number is computed by literally shocking the curve and re-running the pricer, no
closed-form Greeks, no QuantLib. This is slower than analytic derivatives but every number is
directly explainable as "the NPV before and after a specific curve move."

| Metric | Definition |
|---|---|
| **DV01** | `NPV(curve +1bp) - NPV(curve)`. Positive for pay-fixed (gains when rates rise), negative for receive-fixed. |
| **PV01** | `notional x annuity x 0.0001` - the fixed leg's own sensitivity, independent of moneyness. Distinct from DV01, which is the *net* swap sensitivity. |
| **Convexity** | `NPV(+1bp) + NPV(-1bp) - 2*NPV(base)`, left in **unnormalized dollar terms** rather than divided by price, because a swap's NPV can sit at/near zero at its own fair rate, which would make a price-normalized convexity blow up. |
| **KRD (Key-Rate DV01)** | DV01 broken out per curve bucket (2Y/5Y/10Y/30Y) using triangular ("tent") shocks that partition to exactly 1 at every point on the curve, which is *why* `sum(KRD) ~= total DV01`. |
| **Dollar Duration** | DV01 at a 100bp move instead of 1bp, same bump-and-reprice, different magnitude. |
| **Gamma DV01** | How much DV01 itself changes for a 50bp move, gamma expressed in DV01 terms rather than dollar-convexity terms. |
| **Leg DV01** | Fixed leg and floating leg DV01 computed separately; verified to sum exactly to net DV01. |
| **Fixed-Leg Macaulay Duration** | PV-weighted average time of the fixed leg's cashflows *only*, not the net swap, since a near-par swap's NPV can be ~0, making a price-weighted duration for the whole swap ill-defined. |
"""
    )
    st.write("")
    st.markdown("#### Why pay-fixed has \"negative duration\"")
    st.markdown(
        """
A pay-fixed swap gains value when rates rise (you're locked into paying a below-market fixed
rate), so its DV01 is positive under this platform's convention. On the standard bond convention
("duration = how much you lose when yields rise"), that means a payer swap has *negative*
duration, it is economically short a bond (short duration, long floating-rate cash), while a
receiver swap is economically long a bond.
"""
    )
    st.write("")
    st.markdown("#### Scenario engine")
    st.markdown(
        """
41 named scenarios (parallel shifts at 7 magnitudes, 12 curve-shape trades, 15 macro events),
built entirely on the same key-rate bucket-shock infrastructure as KRD, a scenario is just a
custom-shaped set of simultaneous key-rate bumps. Macro scenario shapes are explicitly documented
as illustrative/stylized, not calibrated forecasts, and are distinct from Module 8 (Historical
Replay), which prices swaps on real dates with real Bank of Canada data.

**P&L attribution**: a linear (first-order) estimate of a scenario's P&L is
`sum(KRD_bucket * scenario_shock_bucket_bp)`, reported alongside the true, fully-repriced NPV
change. The gap between them is the convexity/cross-term residual the linear estimate misses.

**Custom shocks and Monte Carlo**: `run_custom_scenario()` accepts an arbitrary user-defined
bucket-shock dict (not limited to the named catalog). `run_monte_carlo_scenarios()` draws
independent Normal(0, std) shocks per bucket and fully reprices under each draw, **this is a
stress-testing tool for exploring unstructured curve noise, not a calibrated Value-at-Risk
engine**: buckets are shocked independently, with no correlation structure across tenors, which
is a real simplification (actual curve moves are correlated, especially between adjacent tenors)
and is stated on the page itself, not just here.
"""
    )

# ---------------------------------------------------------------------------
with tab_limits:
    st.markdown("### Assumptions and Known Limitations")
    st.markdown(
        """
This section exists because a platform that hides its own simplifications is less credible than
one that states them plainly. Every item below is a deliberate, documented scope decision, not an
oversight discovered after the fact.

**Discounting curve**
- Bootstrapped from GoC benchmark bond yields as an **OIS proxy**, real CORRA OIS swap quotes are
  not publicly available. No swap-spread model is applied.
- **Single-curve** framework: the same curve forecasts and discounts. A production multi-curve
  (separate discount/forecast curves, e.g. CORRA-discounted, term-SOFR-style forecast) framework
  was deliberately not built, it would break the telescoping-identity floating-leg valuation that
  is one of this platform's clearest interview talking points, and isn't necessary for a
  single-currency, single-index CORRA OIS.
- Bootstrap gap-handling always assumes linear-on-zero-rate internally, even when the *final*
  curve uses a different interpolation method, see the Bootstrap Diagnostics tab for the
  resulting (small, real, disclosed) residual on non-linear curves.

**Calendars and conventions**
- Canada and TARGET holiday calendars are **approximations** (Easter algorithm + weekday rules),
  not sourced from an official Payments Canada or ECB feed.
- No irregular/broken-date schedules beyond the four stub variants (short/long, first/last).

**Risk**
- Carry, roll-down, and theta (time-decay valuation) are **not implemented**, they require a
  different valuation mechanism (repricing as of a *later* date, either statically or against the
  curve's own forward-implied shape) than the bump-and-reprice approach used throughout. Explicitly
  scoped out rather than rushed.
- CS01 is not applicable: this is a single-curve OIS with no credit-spread component.

**Scenarios**
- Monte Carlo shocks are drawn **independently per bucket** with no correlation structure, a
  stress-testing exploration tool, not a calibrated Value-at-Risk model.
- Macro scenario shock shapes (recession, inflation shock, etc.) are illustrative/stylized,
  grounded in standard rates intuition, not calibrated to any specific forecast or historical
  regression.

**Market data**
- BoC Valet API publishes once per business day; there is no intraday updating, and the ~1-hour
  cache TTL means the dashboard can lag the very latest publication by up to that long.
"""
    )
