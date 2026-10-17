"""
Saves traces to disk, one JSON file per request.
failures.md is written from these files.
"""
from __future__ import annotations

import json
import os

from app.trace.trace import Trace


def save_trace(trace: Trace, trace_dir: str) -> str:
    """Write the trace to <dir>/<request_id>.json and return the path."""
    os.makedirs(trace_dir, exist_ok=True)
    path = os.path.join(trace_dir, f"{trace.request_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(trace.to_dict(), f, ensure_ascii=False, indent=2)
    return path