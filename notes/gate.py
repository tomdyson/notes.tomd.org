import time
from collections import defaultdict


_MAX_ATTEMPTS = 3
_WINDOW_SECONDS = 60
# Keyed by (scope, client IP, slug) so unlock attempts and comment posts on
# the same note count separately.
_attempts: dict[tuple[str, str, str], list[float]] = defaultdict(list)


def reset_rate_limiter() -> None:
    _attempts.clear()


def _client_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _bucket(request, slug: str, scope: str) -> tuple[str, str, str]:
    return (scope, _client_ip(request), slug)


def is_rate_limited(
    request, slug: str, *, scope: str = "unlock", limit: int = _MAX_ATTEMPTS
) -> bool:
    now = time.monotonic()
    key = _bucket(request, slug, scope)
    _attempts[key] = [t for t in _attempts[key] if now - t < _WINDOW_SECONDS]
    return len(_attempts[key]) >= limit


def record_attempt(request, slug: str, *, scope: str = "unlock") -> None:
    _attempts[_bucket(request, slug, scope)].append(time.monotonic())


# Unlock attempts only count when they fail; the call site says so.
record_failed_attempt = record_attempt


def is_unlocked(request, slug: str) -> bool:
    return bool(request.session.get("unlocked_notes", {}).get(slug))


def mark_unlocked(request, slug: str) -> None:
    unlocked = request.session.get("unlocked_notes", {})
    unlocked[slug] = True
    request.session["unlocked_notes"] = unlocked
