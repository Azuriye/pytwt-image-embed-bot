"""Small formatting helpers."""
from datetime import datetime, timezone


def human_format(num: int | float) -> str:
    """1000 -> '1K', 1500000 -> '1.5M'. For reply/retweet/like counts."""
    num = float(f"{float(num):.3g}")
    for suffix in ("", "K", "M", "B", "T"):
        if abs(num) < 1000:
            text = f"{num:f}".rstrip("0").rstrip(".")
            return f"{text}{suffix}"
        num /= 1000.0
    return f"{num:f}P"


def utc_to_local(utc_dt: datetime) -> datetime:
    """gallery-dl gives naive UTC. Discord embeds want aware local."""
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(tz=None)
