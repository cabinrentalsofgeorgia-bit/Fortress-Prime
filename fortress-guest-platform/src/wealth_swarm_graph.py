from __future__ import annotations


class _WealthSwarm:
    def invoke(self, state: dict) -> dict:
        out = dict(state or {})
        receipt_text = (out.get("receipt_text") or "").strip()
        out.setdefault("audit_trail", [])
        out["audit_trail"].append("SWARM: fallback parser executed")
        out["extracted_data"] = {
            "vendor": "UNKNOWN",
            "total": 0.0,
            "categories": [],
        }
        out["tax_strategy"] = "Needs manual review"
        out["compliance_flags"] = [] if receipt_text else ["empty_receipt_text"]
        out["ready_for_ledger"] = bool(receipt_text)
        return out


wealth_swarm = _WealthSwarm()

