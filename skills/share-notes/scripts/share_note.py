#!/usr/bin/env python3
"""Publish Markdown through the notes.tomd.org API."""

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_API_URL = "https://notes.tomd.org/api/v1/notes"
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class ShareNoteError(Exception):
    pass


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Publish Markdown and print the created note as JSON."
    )
    parser.add_argument(
        "source",
        nargs="?",
        default="-",
        help="Markdown file to publish, or - to read stdin (default: -).",
    )
    parser.add_argument("--title", help="Optional note title.")
    parser.add_argument("--slug", help="Optional custom URL slug.")
    parser.add_argument(
        "--password-env",
        metavar="NAME",
        help="Read an optional note password from environment variable NAME.",
    )
    parser.add_argument(
        "--comments",
        action="store_true",
        help="Let readers comment on the published note.",
    )
    parser.add_argument(
        "--api-url",
        help="Override NOTES_TOMD_API_URL for local testing.",
    )
    parser.add_argument(
        "--idempotency-key",
        help="Override the generated retry-safe request identifier.",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args(argv)


def read_input(source, label):
    """Read text from a file, or stdin when source is "-"."""
    if source == "-":
        text = sys.stdin.read()
    else:
        try:
            text = Path(source).read_text(encoding="utf-8")
        except OSError as exc:
            raise ShareNoteError(f"Could not read {label} file: {exc}") from exc
    if not text.strip():
        raise ShareNoteError(f"{label} input is empty.")
    return text


def read_markdown(source):
    return read_input(source, "Markdown")


def error_message(body, fallback):
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return fallback
    error = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return error["message"]
    return fallback


def api_request(
    method, url, *, token, payload=None, idempotency_key=None, timeout=30.0, attempts=3
):
    """Call the notes API and return its JSON response ({} when it has no body)."""
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "notes.tomd.org-share-skill/1",
    }
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    request = Request(url, data=body, method=method, headers=headers)

    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw.strip() else {}
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            if exc.code in RETRYABLE_STATUSES and attempt + 1 < attempts:
                time.sleep(2**attempt)
                continue
            raise ShareNoteError(
                error_message(response_body, f"API request failed with HTTP {exc.code}.")
            ) from exc
        except URLError as exc:
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
                continue
            raise ShareNoteError(f"Could not reach the notes API: {exc.reason}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ShareNoteError("The notes API returned an invalid JSON response.") from exc

    raise ShareNoteError("The notes API request failed.")


def publish(*, api_url, token, payload, idempotency_key, timeout, attempts=3):
    return api_request(
        "POST",
        api_url,
        token=token,
        payload=payload,
        idempotency_key=idempotency_key,
        timeout=timeout,
        attempts=attempts,
    )


def main(argv=None):
    args = parse_args(argv)
    token = os.environ.get("NOTES_TOMD_TOKEN", "").strip()
    if not token:
        raise ShareNoteError("NOTES_TOMD_TOKEN is not configured.")

    payload = {"markdown": read_markdown(args.source)}
    if args.title is not None:
        payload["title"] = args.title
    if args.slug is not None:
        payload["slug"] = args.slug
    if args.password_env:
        if args.password_env not in os.environ:
            raise ShareNoteError(
                f"Password environment variable {args.password_env} is not configured."
            )
        payload["password"] = os.environ[args.password_env]
    if args.comments:
        payload["comments_enabled"] = True

    result = publish(
        api_url=args.api_url
        or os.environ.get("NOTES_TOMD_API_URL", DEFAULT_API_URL),
        token=token,
        payload=payload,
        idempotency_key=args.idempotency_key or str(uuid.uuid4()),
        timeout=args.timeout,
    )
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    try:
        main()
    except ShareNoteError as exc:
        json.dump({"error": str(exc)}, sys.stderr)
        sys.stderr.write("\n")
        raise SystemExit(1)
