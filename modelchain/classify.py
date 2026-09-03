"""Deciding what a failure means, and how long to stay away.

Three kinds, because three different things happen next:

``temporary``  overload, timeouts, plain rate limits. A short cooldown so one
               conversation does not hammer a struggling endpoint. Comes back
               on its own; not worth telling anyone about.
``capped``     the free tier's usage window is spent. Self-heals when the
               window rolls over, so benching it "until a human looks" would
               leave a channel dead all day for no reason. If the provider
               says how long, believe it.
``gone``       the model is withdrawn, or the key is refused. Nothing about
               waiting will fix it, so it is benched until a person decides.

Unknown errors are ``temporary`` on purpose: disabling a channel on evidence
we do not understand is worse than retrying it.
"""

from __future__ import annotations

import re

_TEMPORARY_FAILURE_RE = re.compile(
    r"timed? ?out|overload|temporar|bad gateway|\b50[234]\b|too many requests|"
    r"rate.?limit|connection (reset|refused|error)|proxy",
    re.I,
)

# CamelCase matters: providers emit FreeUsageLimitError, not three plain words.
_CAP_WALL_RE = re.compile(
    r"freeusage|free usage exceeded|usage.?limit|requires available credits|"
    r"add credits|insufficient|quota|payment",
    re.I,
)

# A retry hint in the error is the provider telling us exactly how long to stay
# away. Honour it rather than guessing.
_CAP_RETRY_RE = re.compile(r"retrying in\s*(\d+)\s*h(?:ours?)?(?:\s*(\d+)\s*m(?!s))?", re.I)

_REVIEW_FAILURE_RE = re.compile(
    r"404|not found|no such model|does not exist|deprecat|decommission|"
    r"unauthorized|forbidden|invalid.{0,20}key",
    re.I,
)

#: One conversation should not keep hitting an endpoint that just failed.
TEMP_COOLDOWN_SECONDS = 120
#: How long a spent free-tier window is assumed to last, absent a hint.
CAP_DEFAULT_SECONDS = 86400


def classify_failure(error) -> str:
    """``"temporary"``, ``"capped"`` or ``"gone"``."""
    text = str(error or "")
    if _REVIEW_FAILURE_RE.search(text):
        return "gone"
    if _CAP_WALL_RE.search(text):
        return "capped"
    return "temporary"


def bench_seconds_for(error, kind: str) -> int | None:
    """How long to bench a model. ``None`` means until a human clears it."""
    if kind == "temporary":
        return TEMP_COOLDOWN_SECONDS
    if kind != "capped":
        return None

    match = _CAP_RETRY_RE.search(str(error or ""))
    if match:
        # Plus ten minutes, because a window that has just rolled over is
        # still being hammered by everyone else who was waiting for it.
        hinted = int(match.group(1)) * 3600 + int(match.group(2) or 0) * 60 + 600
        return min(hinted, CAP_DEFAULT_SECONDS)
    return CAP_DEFAULT_SECONDS


def bench_reason(why) -> str:
    """A raw provider error reduced to something a person can read."""
    text = str(why or "")
    if "503" in text:
        return "provider outage (503)"
    if "429" in text or "FreeUsageLimit" in text or "Rate limit" in text:
        return "free-tier rate limit (429)"
    if "empty content" in text:
        return "returned empty content"
    if "404" in text or "not supported" in text:
        return "model withdrawn (404)"
    return text[:50] + ("…" if len(text) > 50 else "")
