# CLAUDE.md

Guidance for Claude working in this repo. Read before making changes.

## What this is

A single-user, self-hosted, gist-like Django app that serves markdown notes at
`notes.tomd.org`. One Django project (`noteserver`), one app (`notes`), SQLite
on a Fly volume, CI auto-deploys on push to `main`.

## Commands

- Run tests: `python manage.py test notes` (77 tests, ~8s)
- Run a single test: `python manage.py test notes.tests.test_rendering.RenderMarkdownTests.test_strips_script_tags`
- Dev server: `DEBUG=1 python manage.py runserver`
- Migrations (local): `DEBUG=1 python manage.py migrate`
- Deploy manually: `fly deploy -a notes-tomd-org`
- Tail prod logs: `fly logs -a notes-tomd-org`

`DEBUG=1` is needed for any management command that touches settings outside
of `manage.py test` (tests auto-detect `test` in `argv`).

## Working style

- **Red/green TDD.** New behaviour starts with a failing test. Tests live in
  `notes/tests/test_*.py`, one file per concern (slugs, rendering, models,
  views_public, views_auth, password_gate, editor_markup). Django's built-in
  `TestCase` — not pytest.
- Don't add new abstractions without a test that motivates them.

## Architecture gotchas

- **URL ordering matters.** `noteserver/urls.py` registers `/admin/`,
  `/login/`, `/logout/` before including `notes.urls`; inside `notes/urls.py`
  the literal `/new/` is registered before the `<slug:slug>/` catch-all.
  Breaking this order lets a malicious (or accidental) note shadow those
  paths. There are explicit tests guarding this in `test_views_public.py`.
- **`Note.save()` renders HTML and auto-generates the slug.** Never set
  `html` manually; never bypass `save()` for slug generation. The slug
  generator retries on collision up to 8 times inside atomic savepoints.
- **Markdown rendering is canonical server-side.** The editor's live preview
  is `marked` + `DOMPurify` (client-side), but the stored `html` field is
  what readers see. Always sanitise through `notes/rendering.py`; don't add
  new tag/attr allowances without thinking about XSS.
- **Static files in prod use `CompressedManifestStaticFilesStorage`.** This
  requires `collectstatic` to run at Docker build time in non-DEBUG mode so
  the manifest exists. See `Dockerfile` — that's why the RUN line is
  `SECRET_KEY=build python manage.py collectstatic --noinput` (no DEBUG=1).

## SQLite on Fly — critical

Migrations run inside the app container via `entrypoint.sh`, **not** as a
Fly `release_command`. Release machines don't mount the volume, so a release-
command migration would execute against an empty ephemeral file and silently
succeed while doing nothing. If you ever see someone propose moving migrations
to `release_command`, stop them.

The volume `data` is mounted at `/app/data`. `DB_PATH=/app/data/db.sqlite3`
must stay set. Backups are Fly's automatic volume snapshots.

## Deployment

- CI: `.github/workflows/fly-deploy.yml` runs tests on every push, then
  deploys on pushes to `main` using the `FLY_API_TOKEN` repo secret (scoped
  deploy token for `notes-tomd-org`).
- When `ALLOWED_HOSTS` or `CSRF_TRUSTED_ORIGINS` change, update them via
  `fly secrets set` — both must include any domain that serves the site, with
  scheme for CSRF (`https://...`) and without for ALLOWED_HOSTS.
- New subdomains: use the `assign-fly-subdomain` skill; it handles Fly cert +
  Cloudflare CNAMEs and reminds about `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS`.

## Things NOT to do

- Don't add a `release_command` for migrations (see SQLite note above).
- Don't switch `STORAGES` away from `CompressedManifestStaticFilesStorage` in
  prod — if you do, update `Dockerfile` and ensure whitenoise can still serve.
- Don't widen the bleach allowlist (`notes/rendering.py`) without a test that
  justifies it.
- Don't store passwords in plaintext, don't log them, don't serialise them.
  Use `Note.set_password` / `check_password`.
- Don't change the shape of `generate_slug()` (6-char base62) without
  considering URL collisions with already-published notes. If you shorten it,
  collisions get likelier; if you lengthen it, old URLs still work.
