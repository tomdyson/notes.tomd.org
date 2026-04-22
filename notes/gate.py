import time
from collections import defaultdict


_MAX_ATTEMPTS = 3
_WINDOW_SECONDS = 60
_attempts: dict[tuple[str, str], list[float]] = defaultdict(list)


def reset_rate_limiter() -> None:
    _attempts.clear()


def _client_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def is_rate_limited(request, slug: str) -> bool:
    now = time.monotonic()
    key = (_client_ip(request), slug)
    _attempts[key] = [t for t in _attempts[key] if now - t < _WINDOW_SECONDS]
    return len(_attempts[key]) >= _MAX_ATTEMPTS


def record_failed_attempt(request, slug: str) -> None:
    _attempts[(_client_ip(request), slug)].append(time.monotonic())


def is_unlocked(request, slug: str) -> bool:
    return bool(request.session.get("unlocked_notes", {}).get(slug))


def mark_unlocked(request, slug: str) -> None:
    unlocked = request.session.get("unlocked_notes", {})
    unlocked[slug] = True
    request.session["unlocked_notes"] = unlocked
