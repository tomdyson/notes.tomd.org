import re
import secrets
import string

ALPHABET = string.ascii_letters + string.digits
SLUG_LEN = 6
MAX_SLUG_LEN = 64

RESERVED = frozenset({
    "admin",
    "login",
    "logout",
    "new",
    "static",
    "favicon.ico",
    "robots.txt",
    "healthz",
    "_",
    "api",
})

_SHAPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def generate_slug() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(SLUG_LEN))


def is_reserved(slug: str) -> bool:
    return slug.lower() in RESERVED


def is_valid_slug_shape(slug: str) -> bool:
    if not slug or len(slug) > MAX_SLUG_LEN:
        return False
    return bool(_SHAPE_RE.match(slug))
