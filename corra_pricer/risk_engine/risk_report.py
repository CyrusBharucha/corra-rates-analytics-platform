"""
RiskReport: the structured output of the risk engine - the object a
dashboard page or a trader-facing script would consume directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RiskReport:
    notional: float
    pay_fixed: bool
    fixed_rate_pct: float
    curve_label: str

    dv01: float          # $ change in NPV for a +1bp parallel shift
    pv01: float           # $ value of 1bp on the fixed-leg annuity (always positive)
    krd: dict[str, float] = field(default_factory=dict)  # {"2Y": ..., "5Y": ..., ...}
    convexity: float = 0.0  # $ second-order sensitivity (dollar gamma per bp^2)

    def krd_sum(self) -> float:
        return sum(self.krd.values())

    def to_dict(self) -> dict:
        return {
            "notional": self.notional,
            "direction": "Pay Fixed" if self.pay_fixed else "Receive Fixed",
            "fixed_rate_pct": self.fixed_rate_pct,
            "curve": self.curve_label,
            "dv01": self.dv01,
            "pv01": self.pv01,
            **{f"krd_{k}": v for k, v in self.krd.items()},
            "krd_sum": self.krd_sum(),
            "convexity": self.convexity,
        }

    def summary(self) -> str:
        direction = "PAY FIXED" if self.pay_fixed else "RECEIVE FIXED"
        lines = [
            f"=== Risk Report: {direction} {self.notional:,.0f} @ {self.fixed_rate_pct:.4f}% ===",
            f"Curve: {self.curve_label}",
            f"DV01:        {self.dv01:>14,.2f}   (NPV change per +1bp parallel shift)",
            f"PV01:        {self.pv01:>14,.2f}   (value of 1bp on the fixed-leg annuity)",
            "Key-Rate DV01:",
        ]
        for bucket, val in self.krd.items():
            lines.append(f"  {bucket:>5}:     {val:>14,.2f}")
        lines.append(f"  Sum:       {self.krd_sum():>14,.2f}   (should be close to DV01 above)")
        lines.append(f"Convexity:   {self.convexity:>14,.4f}   ($ per (1bp)^2, second-order effect)")
        return "\n".join(lines)
