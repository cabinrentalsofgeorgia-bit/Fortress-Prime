"""Stable import surface for OpenShell signed audit helpers (alias of ``openshell_audit``)."""

from backend.services.openshell_audit import record_audit_event

__all__ = ["record_audit_event"]
