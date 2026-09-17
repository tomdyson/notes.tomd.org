#!/usr/bin/env python3
"""Read, post and delete comments on notes.tomd.org notes through the API."""

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

# Reuse the publishing client's HTTP, retry and error handling.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from share_note import DEFAULT_API_URL, ShareNoteError, api_request, read_input  # noqa: E402


SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def slug_from(value):
    """Accept a bare slug or any URL of the note, and return the slug."""
    value = (value or "").strip()
    if "://" in value:
        segments = [part for part in urlsplit(value).path.split("/") if part]
        value = segments[0] if segments else ""
    value = value.strip("/")
    if not SLUG_RE.match(value):
        raise ShareNoteError("Give the note as its slug or its notes.tomd.org URL.")
    return value


def comments_url(api_url, slug):
    return f"{api_url.rstrip('/')}/{slug}/comments"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Work with the comments on a notes.tomd.org note. Prints JSON."
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("note", help="Note slug or URL.")
    common.add_argument("--api-url", help="Override NOTES_TOMD_API_URL for local testing.")
    common.add_argument("--timeout", type=float, default=30.0)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list", parents=[common], help="Print the note's comment threads.")

    add = commands.add_parser("add", parents=[common], help="Post a comment as the note's author.")
    add.add_argument(
        "source", nargs="?", default="-",
        help="File holding the comment text, or - to read stdin (default: -).",
    )
    add.add_argument("--reply-to", type=int, metavar="ID", help="Reply within thread ID.")
    add.add_argument("--quote", help="Anchor to this exact passage of the rendered note.")
    add.add_argument("--prefix", help="Text just before the quote, to tell repeats apart.")
    add.add_argument("--suffix", help="Text just after the quote, to tell repeats apart.")
    add.add_argument("--author-name", help="Display name (default: the account's name).")
    add.add_argument("--idempotency-key", help="Override the generated retry-safe identifier.")

    delete = commands.add_parser("delete", parents=[common], help="Delete a comment and its replies.")
    delete.add_argument("comment_id", type=int)
    return parser.parse_args(argv)


def add_payload(args):
    if args.reply_to is not None and (args.quote or args.prefix or args.suffix):
        raise ShareNoteError("A reply belongs to its thread's passage; drop --quote when replying.")
    if (args.prefix or args.suffix) and not args.quote:
        raise ShareNoteError("--prefix and --suffix only make sense with --quote.")
    payload = {"body": read_input(args.source, "Comment")}
    if args.reply_to is not None:
        payload["parent"] = args.reply_to
    for field in ("quote", "prefix", "suffix", "author_name"):
        value = getattr(args, field)
        if value is not None:
            payload[field] = value
    return payload


def main(argv=None):
    args = parse_args(argv)
    token = os.environ.get("NOTES_TOMD_TOKEN", "").strip()
    if not token:
        raise ShareNoteError("NOTES_TOMD_TOKEN is not configured.")
    slug = slug_from(args.note)
    url = comments_url(
        args.api_url or os.environ.get("NOTES_TOMD_API_URL", DEFAULT_API_URL), slug
    )

    if args.command == "list":
        result = api_request("GET", url, token=token, timeout=args.timeout)
    elif args.command == "add":
        result = api_request(
            "POST",
            url,
            token=token,
            payload=add_payload(args),
            idempotency_key=args.idempotency_key or str(uuid.uuid4()),
            timeout=args.timeout,
        )
    else:
        api_request("DELETE", f"{url}/{args.comment_id}", token=token, timeout=args.timeout)
        result = {"deleted": args.comment_id, "slug": slug}

    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    try:
        main()
    except ShareNoteError as exc:
        json.dump({"error": str(exc)}, sys.stderr)
        sys.stderr.write("\n")
        raise SystemExit(1)
