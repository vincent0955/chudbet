import math
import re
from typing import Any

# CDN live box scores use ISO-8601 durations, e.g. ``PT28M03.00S``.
_ISO_PT_DURATION = re.compile(
    r"^PT(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+(?:\.\d+)?)S)?$",
    re.IGNORECASE,
)


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
    if s.upper().startswith("PT"):
        m = _ISO_PT_DURATION.match(s.replace(" ", ""))
        if m:
            h = int(m.group("h") or 0)
            mi = int(m.group("m") or 0)
            sec = float(m.group("s") or 0)
            return h * 60.0 + mi + sec / 60.0
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
