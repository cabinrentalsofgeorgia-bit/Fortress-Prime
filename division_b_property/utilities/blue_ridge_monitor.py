"""
Blue Ridge Utility Monitor
============================
Monitors utility costs (electric, water, gas, internet) for Blue Ridge
cabin properties. Detects anomalies by comparing predicted vs. actual
costs and feeds variance data into the OODA loop.

Data sources:
    - Plaid transactions tagged as UTILITY
    - Historical utility cost data from NAS
    - Cabin YAML configs for expected baseline costs
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("division_b.utilities.blue_ridge")


@dataclass
class UtilityReading:
    """A single utility reading/transaction for a cabin."""
    cabin_id: str
    utility_type: str          # electric, water, gas, internet, trash
    amount: float
    date: date
    provider: str = ""
    plaid_txn_id: str = ""
    predicted_amount: float = 0.0

    @property
    def variance_pct(self) -> float:
        if self.predicted_amount == 0:
            return 100.0 if self.amount > 0 else 0.0
        return abs((self.amount - self.predicted_amount) / self.predicted_amount) * 100


@dataclass
class CabinUtilityProfile:
    """Historical utility profile for a single cabin."""
    cabin_id: str
    cabin_name: str
    location: str = "Blue Ridge, GA"
    baseline_monthly: Dict[str, float] = field(default_factory=dict)
    readings: List[UtilityReading] = field(default_factory=list)


def load_cabin_baselines() -> Dict[str, CabinUtilityProfile]:
    """
    Load expected utility baselines from cabin YAML configs.
    Falls back to reasonable defaults for Blue Ridge properties.
    """
    defaults = {
        "electric": 250.0,
        "water": 80.0,
        "gas": 120.0,
        "internet": 100.0,
        "trash": 45.0,
    }

    # Try loading from cabin YAML files
    try:
        from pathlib import Path
        import yaml
        cabins_dir = Path(__file__).parent.parent.parent / "cabins"
        profiles = {}

        if cabins_dir.exists():
            for yaml_file in cabins_dir.glob("*.yaml"):
                with open(yaml_file) as f:
                    data = yaml.safe_load(f) or {}
                cabin_id = yaml_file.stem
                profiles[cabin_id] = CabinUtilityProfile(
                    cabin_id=cabin_id,
                    cabin_name=data.get("name", cabin_id),
                    baseline_monthly=data.get("utility_baselines", defaults),
                )

        if profiles:
            return profiles
    except Exception as e:
        logger.debug(f"Could not load cabin YAML configs: {e}")

    # Return defaults
    return {"default": CabinUtilityProfile(
        cabin_id="default",
        cabin_name="Default Blue Ridge Cabin",
        baseline_monthly=defaults,
    )}


def detect_utility_anomalies(
    readings: List[UtilityReading],
    threshold_pct: float = 5.0,
) -> List[Dict[str, Any]]:
    """
    Detect utility cost anomalies (variance > threshold).

    These feed into the OODA loop's REFLECT phase when the predicted
    utility cost diverges significantly from the actual Plaid transaction.
    """
    anomalies = []

    for reading in readings:
        if reading.variance_pct > threshold_pct:
            anomalies.append({
                "type": "UTILITY_ANOMALY",
                "cabin_id": reading.cabin_id,
                "utility_type": reading.utility_type,
                "predicted": reading.predicted_amount,
                "actual": reading.amount,
                "variance_pct": reading.variance_pct,
                "date": reading.date.isoformat(),
                "severity": "high" if reading.variance_pct > 20 else "medium",
            })

    if anomalies:
        logger.warning(f"Detected {len(anomalies)} utility anomalies (>{threshold_pct}% variance)")

    return anomalies
