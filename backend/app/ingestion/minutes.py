import math
from typing import Any


def parse_minutes(raw: Any) -> float:
    """Normalize NBA box score MIN field (MM:SS, numeric, or DNP-style text) to float minutes."""
    if raw is None:
        return 0.0
    if isinstance(raw, float) and math.isnan(raw):
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s or s.upper().startswith("DNP") or s.upper() in {"NWT", "OUT", "DND"}:
        return 0.0
    if ":" in s:
        parts = s.split(":")
        try:
            mm = int(parts[0])
            ss = int(parts[1]) if len(parts) > 1 else 0
            return mm + ss / 60.0
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def normalize_stat_int(raw: Any) -> int:
    if raw is None:
        return 0
    if isinstance(raw, float) and math.isnan(raw):
        return 0
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0
