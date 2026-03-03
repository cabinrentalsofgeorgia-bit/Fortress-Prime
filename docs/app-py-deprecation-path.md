# `app.py` Repair and Deprecation Path

## Current State

- `app.py` has been kept operational for backward compatibility with existing Streamlit workflows.
- Canonical long-term entrypoints should move to service-specific dashboards and APIs.

## Deprecation Plan

1. **Now (compatibility phase):** keep `app.py` import-compatible with `config.py`.
2. **Next release:** announce deprecation in release notes and operator docs.
3. **After migration window:** route operators to canonical surfaces:
   - `tools/master_console.py` (command center)
   - `src/dashboard.py` (if retained as Streamlit runtime)
4. **Final step:** remove `app.py` once no automated workflows depend on it.
