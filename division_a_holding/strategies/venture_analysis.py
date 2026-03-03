"""
Venture Analysis — Verses in Bloom & DGX Cost Intelligence
============================================================
Monitors and analyzes venture capital investments and compute asset costs.

Focus areas:
    - Verses in Bloom portfolio performance
    - DGX Spark cluster depreciation & operating costs
    - Market investment performance tracking
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger("division_a.strategies.venture")


@dataclass
class VenturePosition:
    """A single venture capital position."""
    name: str
    invested_amount: float
    current_value: float
    inception_date: str
    status: str = "active"          # active, exited, written_off
    notes: str = ""

    @property
    def unrealized_gain(self) -> float:
        return self.current_value - self.invested_amount

    @property
    def return_multiple(self) -> float:
        return self.current_value / self.invested_amount if self.invested_amount > 0 else 0


@dataclass
class AssetCostTracker:
    """Tracks ongoing costs for a hardware asset (e.g., DGX Spark cluster)."""
    asset_name: str
    purchase_price: float
    purchase_date: str
    useful_life_years: float = 5.0
    monthly_costs: List[Dict[str, float]] = field(default_factory=list)

    @property
    def monthly_depreciation(self) -> float:
        return self.purchase_price / (self.useful_life_years * 12)

    @property
    def total_operating_cost(self) -> float:
        return sum(sum(m.values()) for m in self.monthly_costs)


def analyze_venture_portfolio(
    positions: List[VenturePosition],
) -> Dict[str, Any]:
    """
    Aggregate analysis of the venture portfolio.

    Returns portfolio-level metrics for Sovereign health monitoring.
    """
    total_invested = sum(p.invested_amount for p in positions)
    total_value = sum(p.current_value for p in positions)
    active = [p for p in positions if p.status == "active"]

    return {
        "total_positions": len(positions),
        "active_positions": len(active),
        "total_invested": total_invested,
        "total_current_value": total_value,
        "unrealized_gain": total_value - total_invested,
        "portfolio_multiple": total_value / total_invested if total_invested > 0 else 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def analyze_compute_costs(
    tracker: AssetCostTracker,
) -> Dict[str, Any]:
    """
    Analyze DGX Spark cluster cost profile for the Sovereign.
    """
    return {
        "asset": tracker.asset_name,
        "purchase_price": tracker.purchase_price,
        "monthly_depreciation": tracker.monthly_depreciation,
        "total_operating_cost": tracker.total_operating_cost,
        "cost_per_month": tracker.monthly_depreciation + (
            tracker.total_operating_cost / max(len(tracker.monthly_costs), 1)
        ),
    }
