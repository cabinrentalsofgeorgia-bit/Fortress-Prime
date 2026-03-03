#!/usr/bin/env python3
"""
Fortress Legal Command Center — Application runner
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8200,
        reload=True,
        log_level="info",
    )
