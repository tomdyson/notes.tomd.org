---
name: share-notes
description: Publish Markdown as a shareable note on notes.tomd.org. Use when the user explicitly asks to share, publish, post, or turn content into a notes.tomd.org link; do not use for drafting or editing content unless publication is requested.
---

# Share Notes

Publish only after the user explicitly requests sharing or publication. Treat phrases such as “share this as a note” and “put this on notes.tomd.org” as authorization to publish the supplied content.

1. Prepare the final Markdown. Preserve the user's content and structure. Infer a concise title only when helpful; omit the title when none is apparent.
2. Explain that an unpassworded note is accessible to anyone with its URL if the user appears unaware of that fact or the content seems sensitive. Ask before publishing when sensitivity or publication intent is genuinely ambiguous.
3. Run `scripts/share_note`, passing a Markdown file or `-` for stdin. The wrapper loads the user's login environment before starting the client. Add `--title`, `--slug`, or `--password-env` only when requested or already supplied. Never put a password directly on the command line.
4. On success, return the exact `url` from the script's JSON output as a clickable link. Mention password protection without revealing the password.
5. On failure, report the API's error message. Do not claim that a note was published unless the script returns a successful JSON response.

The script reads `NOTES_TOMD_TOKEN` and optionally `NOTES_TOMD_API_URL`. Never print, store, or request the bearer token in chat. If the token is missing, tell the user to configure `NOTES_TOMD_TOKEN` in the agent environment.

Example:

```sh
scripts/share_note /path/to/note.md --title "Release notes"
```
