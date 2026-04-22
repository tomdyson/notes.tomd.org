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
- Raw source view at `/<slug>/raw`
- Passkey (WebAuthn) auth alongside username/password, with RP ID hardcoded
  to `notes.tomd.org`
- Deploys to Fly.io with SQLite on a 1 GB volume

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

113 tests cover slug generation, markdown rendering + XSS sanitisation, the
`Note` model, public read views, URL-shadowing guards, auth-gated authoring,
password gating, rate limiting, editor markup, UI structure, the `Passkey`
model, and both WebAuthn flows (register + login, with crypto verification
mocked).

## URL map

| Path | Who | Purpose |
|---|---|---|
| `/` | authed | Dashboard (anonymous GET returns 404) |
| `/login/` | anon | Django login; also exposes passkey login |
| `/new/` | authed | Editor for a new note |
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
`healthz`, `_`, `api` are reserved. `/passkeys/` is also effectively reserved
because the literal `/passkeys/` path is registered before the `<slug>/`
catch-all.

## Deployment

Pushes to `main` trigger `.github/workflows/fly-deploy.yml`: tests run on
Ubuntu, then `flyctl deploy --remote-only` ships to Fly.

Manual deploy: `fly deploy -a notes-tomd-org`.

### Fly configuration

- App: `notes-tomd-org`, region `lhr`
- Volume `data` mounted at `/app/data`, SQLite DB at `/app/data/db.sqlite3`
- Migrations run inside the app container via `entrypoint.sh` (release machines
  don't mount the volume, so a `release_command` would migrate an empty DB)
- `entrypoint.sh` also creates/updates the superuser idempotently from
  `DJANGO_SUPERUSER_*` env vars

### Required Fly secrets

- `SECRET_KEY` — Django secret key
- `DB_PATH` — `/app/data/db.sqlite3`
- `ALLOWED_HOSTS` — `notes-tomd-org.fly.dev,notes.tomd.org`
- `CSRF_TRUSTED_ORIGINS` — `https://notes-tomd-org.fly.dev,https://notes.tomd.org`
- `DJANGO_SUPERUSER_USERNAME` / `DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD`

## Project layout

```
noteserver/       Django project (settings, root URLs, wsgi)
notes/            App
  models.py         Note + Passkey
  rendering.py      markdown → sanitised HTML
  slugs.py          generate_slug(), reserved set, shape validation
  gate.py           password-unlock session + rate limiter
  forms.py          NoteForm, UnlockForm
  views.py          note CRUD + public read
  passkey_views.py  WebAuthn register / login / manage
  static/notes/     editor.js, passkeys.js, site.css, pygments.css
  templates/notes/  base.html + page templates
  tests/            113 unit + integration tests
Dockerfile        Python 3.13 slim; collectstatic at build with manifest storage
entrypoint.sh     migrate + superuser sync + gunicorn
fly.toml          Fly config (region lhr, SQLite volume mount, single 256 MB VM)
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
  (including `notes-tomd-org.fly.dev`).
