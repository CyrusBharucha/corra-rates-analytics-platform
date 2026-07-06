"""
End-to-end MVP slice: pull live market data -> bootstrap a curve -> price one
vanilla CORRA OIS. Run with: python run_mvp.py
"""
import datetime as dt

from corra_pricer.curve_builder.bootstrap import bootstrap_zero_curve
from corra_pricer.market_data.boc_valet_client import fetch_latest_market_snapshot
from corra_pricer.pricing_engine.ois_swap import CorraOISSwap
from corra_pricer.risk_engine.risk_engine import build_risk_report
from corra_pricer.scenario_engine.scenario_engine import scenario_summary_table
from corra_pricer.analytics.historical_replay import compare_example_dates


def main():
    print("=== Step 1: Pulling live market data from BoC Valet API ===")
    snapshot = fetch_latest_market_snapshot()
    corra_pct = snapshot["corra_rate_pct"]
    yields_pct = snapshot["benchmark_yields_pct"]
    print(f"CORRA fixing ({snapshot['as_of_corra'].date()}): {corra_pct:.2f}%")
    print(f"GoC benchmark yields ({snapshot['as_of_yields'].date()}): {yields_pct}")

    print("\n=== Step 2: Bootstrapping the discounting curve ===")
    curve = bootstrap_zero_curve(corra_pct, yields_pct, interpolation="linear")
    print(curve.as_dataframe().to_string(index=False))

    print("\n=== Step 3: Pricing a 5Y CORRA OIS, $10mm notional, pay fixed ===")
    trade_date = dt.date.today()
    maturity = dt.date(trade_date.year + 5, trade_date.month, min(trade_date.day, 28))
    swap = CorraOISSwap(
        trade_date=trade_date,
        effective_date=trade_date,
        maturity_date=maturity,
        notional=10_000_000,
        fixed_rate=0.03,
        pay_fixed=True,
    )
    fair = swap.fair_rate(curve)
    print(f"Fair swap rate: {fair * 100:.4f}%")
    print(f"Priced at 3.00% fixed -> {swap.summary(curve)}")

    swap.fixed_rate = fair
    print(f"Priced at fair rate -> NPV should be ~0: {swap.npv(curve):.6f}")

    print("\n=== Step 4: Risk report (back to the 3.00% fixed swap) ===")
    swap.fixed_rate = 0.03
    report = build_risk_report(swap, curve)
    print(report.summary())

    print("\n=== Step 5: Scenario engine -- 'what happens if rates move?' ===")
    table = scenario_summary_table(swap, curve)
    cols = ["scenario", "category", "npv_change", "dv01_change", "attribution_residual"]
    print(table[cols].to_string(index=False))

    print("\n=== Step 6: Historical replay -- same 5Y swap struck on real historical dates ===")
    hist = compare_example_dates(tenor_years=5, notional=10_000_000)
    hist_cols = ["label", "requested_date", "data_date", "fair_rate_pct", "dv01",
                 "curve_2Y_pct", "curve_5Y_pct", "curve_10Y_pct", "curve_LONG_pct"]
    print(hist[hist_cols].to_string(index=False))


if __name__ == "__main__":
    main()
