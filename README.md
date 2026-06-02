# notes.tomd.org

Self-hosted, gist-like markdown notes. Paste markdown, get a clean shareable
URL, optionally protect a note with a password.

Live at https://notes.tomd.org/.

## Features

- Single-user authoring (Django superuser), public/anonymous viewing
- Custom slugs or auto-generated 6-char base62 IDs (`notes.tomd.org/aB3kLm`)
- Optional per-note passwords, session-scoped unlock, with IP+slug rate limiting
- Live markdown preview in the editor (client-side `marked` + `DOMPurify` +
  Mermaid + Highlight.js); server-side `markdown` + `pygments` + `bleach` is
  canonical
- Mermaid diagrams from fenced `mermaid` code blocks
- Drag or paste images into the editor — Pillow re-encodes to WebP, caps the
  longest edge at 2000px, strips EXIF, and stores on the persistent volume
- Rendered images are wrapped in click-to-expand links
- Raw source view at `/<slug>/raw`
- Passkey (WebAuthn) auth alongside username/password, with RP ID hardcoded
  to `notes.tomd.org`
- Deployed on Coolify with SQLite on a persistent volume

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DEBUG=1 python manage.py migrate
DEBUG=1 python manage.py createsuperuser
DEBUG=1 python manage.py runserver
```

## Tests

```bash
python manage.py test notes
```

195 tests cover slug generation, markdown rendering + XSS sanitisation,
Mermaid fence detection (including CRLF-submitted textareas), the `Note`
model, public read views, URL-shadowing guards, auth-gated authoring,
password gating, rate limiting, editor markup, UI structure, the `Passkey`
model, both WebAuthn flows (register + login, with crypto verification
mocked), the `Image` model + cascade/signal cleanup, the upload endpoint
(auth + CSRF), the Pillow pipeline (resize, WebP, EXIF-stripping), upload
rejection (SVG / oversized / non-image), image→expand-link wrapping, and the
orphan-image sweep command.

## URL map

| Path | Who | Purpose |
|---|---|---|
| `/` | authed | Dashboard (anonymous GET returns 404) |
| `/login/` | anon | Django login; also exposes passkey login |
| `/new/` | authed | Editor for a new note |
| `/upload/` | authed | POST-only image upload (multipart), returns JSON `{url, markdown}` |
| `/i/<short_id>.webp` | public | Serve a stored image |
| `/<slug>/` | public | Rendered note (password-gated if set) |
| `/<slug>/raw` | public | Markdown source (password-gated if set) |
| `/<slug>/edit/` | authed | Editor for existing note |
| `/<slug>/unlock/` | public | Password prompt |
| `/<slug>/delete/` | authed | POST-only delete |
| `/passkeys/` | authed | List + register passkeys |
| `/passkeys/register/{begin,finish}/` | authed | WebAuthn register ceremony |
| `/passkeys/login/{begin,finish}/` | anon | WebAuthn auth ceremony |
| `/passkeys/<pk>/delete/` | authed | POST-only delete a passkey |
| `/admin/` | authed | Django admin |

Slugs `admin`, `login`, `logout`, `new`, `static`, `favicon.ico`, `robots.txt`,
`healthz`, `_`, `api`, `i`, `upload` are reserved. `/passkeys/` is also
effectively reserved because the literal `/passkeys/` path is registered
before the `<slug>/` catch-all.

## Deployment

Deployed on [Coolify](https://admin.co.tomd.org). Pushes to `main` are built and
deployed automatically by Coolify's GitHub App. There is **no CI** — the old
Fly GitHub Action was removed when the site migrated off Fly, so nothing runs
the test suite on push; run `python manage.py test notes` locally first.

Manual deploy: the Coolify UI, or the `coolify` CLI. (It previously ran on Fly;
`fly.toml` remains in the repo but is unused.)

### Coolify configuration

- App `notes-tomd-org`, UUID `xok61kj0vasx16hv3xkv9qj9`, a single
  `dockerfile`-build container
- Persistent volume mounted at `/app/data`, SQLite DB at `/app/data/db.sqlite3`
- Uploaded images live alongside the DB at `/app/data/media/images/` —
  `MEDIA_ROOT` defaults to `dirname(DB_PATH)/media`, so setting `DB_PATH`
  pins the media dir onto the same volume automatically
- Migrations run inside the app container at startup via `entrypoint.sh`; keep
  them there (a build/release step that doesn't mount the volume would migrate
  an empty DB — see CLAUDE.md)
- `entrypoint.sh` also creates/updates the superuser idempotently from
  `DJANGO_SUPERUSER_*` env vars

### Required environment variables

Set in the Coolify app's Environment Variables (UI or `coolify app env`), then
restart the app:

- `SECRET_KEY` — Django secret key
- `DB_PATH` — `/app/data/db.sqlite3`
- `ALLOWED_HOSTS` — `notes.tomd.org,notes-tomd-org.co.tomd.org`
- `CSRF_TRUSTED_ORIGINS` — `https://notes.tomd.org,https://notes-tomd-org.co.tomd.org`
- `DJANGO_SUPERUSER_USERNAME` / `DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD`

### Running a management command in prod

Coolify's API can't exec ad-hoc commands, so SSH the host and `docker exec`. The
container name is `<uuid>-<digits>` and changes each deploy, so resolve it first:

```sh
ssh root@admin.co.tomd.org \
  "docker exec \$(docker ps --format '{{.Names}}' | grep xok61kj0vasx16hv3xkv9qj9) \
     python manage.py <command>"
```

e.g. `rerender_notes` re-renders every note's stored HTML after a rendering
change (`--dry-run` to preview the count).

Optional image-tuning overrides (defaults fine for most cases):
`MEDIA_ROOT`, `IMAGE_MAX_UPLOAD_BYTES` (default 10 MB),
`IMAGE_MAX_DIMENSION` (default 2000 px), `IMAGE_WEBP_QUALITY` (default 85).

### TODO: schedule the orphan-image sweep

Uploads that never get referenced by a saved note are left with `note IS NULL`
and swept by a management command:

```
python manage.py sweep_orphan_images           # deletes orphans older than 24h
python manage.py sweep_orphan_images --hours 1 # shorter threshold
python manage.py sweep_orphan_images --dry-run # report only
```

Currently this has to be run manually. Wire it up as a Coolify scheduled task
(daily, command `python manage.py sweep_orphan_images`, container field blank
for this single-container app) so the volume doesn't slowly accumulate dead
uploads. A note-delete already cascades its images, so the sweep only handles
the "uploaded but never saved" case.

## Project layout

```
noteserver/       Django project (settings, root URLs, wsgi)
notes/            App
  models.py         Note + Image + Passkey
  rendering.py      markdown → sanitised HTML (wraps images in expand-links)
  slugs.py          generate_slug(), reserved set, shape validation
  gate.py           password-unlock session + rate limiter
  forms.py          NoteForm, UnlockForm
  views.py          note CRUD, public read, upload_image, serve_image
  images.py         Pillow pipeline: validate, resize, WebP re-encode
  passkey_views.py  WebAuthn register / login / manage
  management/commands/  sweep_orphan_images.py, rerender_notes.py
  static/notes/     editor.js, passkeys.js, site.css, pygments.css
  templates/notes/  base.html + page templates
  tests/            195 unit + integration tests
Dockerfile        Python 3.13 slim; collectstatic at build with manifest storage
entrypoint.sh     migrate + superuser sync + gunicorn
fly.toml          legacy Fly config — unused since the move to Coolify
```

## Security notes

- Bleach allowlists safe tags/attrs after markdown rendering; `<script>` /
  `<style>` bodies are stripped pre-bleach. `javascript:` and other non-safe
  protocols are filtered.
- Links get `rel="nofollow noopener"` via a bleach linker callback.
- Password hashes use Django's `make_password`/`check_password`; raw values
  never stored.
- Unlock throttle: 3 wrong attempts per `(IP, slug, minute)` → 429.
- WebAuthn RP ID is hardcoded to `notes.tomd.org` in `noteserver/settings.py`
  — passkeys registered in prod will not work against any other hostname
  (including the Coolify alt domain `notes-tomd-org.co.tomd.org`).
- Image uploads are validated by Pillow's decoder (not by `Content-Type` or
  filename), re-encoded to WebP, and size-capped; SVG is explicitly rejected
  because bleach does not sanitise image bodies. Re-encoding strips EXIF.
