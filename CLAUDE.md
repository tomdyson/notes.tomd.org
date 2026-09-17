# CLAUDE.md

Guidance for Claude working in this repo. Read before making changes.

## What this is

A single-user, self-hosted, gist-like Django app that serves markdown notes at
`notes.tomd.org`. One Django project (`noteserver`), one app (`notes`), SQLite
on a persistent volume, deployed on Coolify (`admin.co.tomd.org`) which
auto-deploys on push to `main` via its GitHub App. (It used to run on Fly;
`fly.toml` and some `fly`-named skills/scripts are now vestigial — see
Deployment below.)

## Commands

- Run tests: `python manage.py test notes` (279 tests, ~20s; the anchoring JS tests need `node`
  on PATH and are skipped without it)
- Run a single test: `python manage.py test notes.tests.test_rendering.RenderMarkdownTests.test_strips_script_tags`
- Dev server: `DEBUG=1 python manage.py runserver`
- Migrations (local): `DEBUG=1 python manage.py migrate`
- Deploy: push to `main` (Coolify's GitHub App builds + deploys). Manual deploy
  via the Coolify UI, or the `coolify` CLI / skill.
- Tail prod logs: `coolify app logs xok61kj0vasx16hv3xkv9qj9 -n 200` (the
  `coolify` skill covers the CLI; that UUID is the `notes-tomd-org` app).
- Run a management command in prod: the Coolify API can't exec ad-hoc commands,
  so SSH the host and `docker exec` (see Deployment).

`DEBUG=1` is needed for any management command that touches settings outside
of `manage.py test` (tests auto-detect `test` in `argv`). Not needed in the
prod container — it already has production settings in its environment.

## Working style

- **Red/green TDD.** New behaviour starts with a failing test. Tests live in
  `notes/tests/test_*.py`, one file per concern: `test_slugs`, `test_rendering`,
  `test_models`, `test_views_public`, `test_views_auth`, `test_password_gate`,
  `test_editor_markup`, `test_ui_reorg`, `test_passkey_model`,
  `test_passkey_register`, `test_passkey_login`, `test_images_model`,
  `test_image_pipeline`, `test_image_rejection`, `test_image_gc`,
  `test_upload`, `test_comments_model`, `test_comments_views`,
  `test_comments_js` (runs `node --test notes/tests/js/anchors.test.mjs`). Django's built-in `TestCase` — not pytest.
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
- **Mermaid fences are pre-processed before markdown.** `render_markdown`
  rewrites ```` ```mermaid ```` blocks into `<div class="mermaid">…</div>`
  *before* handing the source to `markdown` so pygments never sees them.
  The regex must tolerate CRLF (`\r?\n`) — browsers submit `<textarea>`
  contents with CRLF, so a LF-only match silently falls through to
  syntax-highlighted code and every diagram authored through the UI breaks.
  When adding tests, include at least one CRLF fixture.
- **Static files in prod use `CompressedManifestStaticFilesStorage`.** This
  requires `collectstatic` to run at Docker build time in non-DEBUG mode so
  the manifest exists. See `Dockerfile` — that's why the RUN line is
  `SECRET_KEY=build python manage.py collectstatic --noinput` (no DEBUG=1).
- **Anonymous `/` returns 404.** The app is only for viewing individual notes
  (or editing, if logged in). There is no public landing page and no "Log in"
  link anywhere — Tom goes to `/login/` or `/admin/` directly. Anonymous
  pages also render without a header at all; the header only appears for
  authenticated users and contains just New note / Passkeys / Log out.
- **Passkey auth is built on `py_webauthn`, with RP ID hardcoded.**
  `WEBAUTHN_RP_ID = "notes.tomd.org"` in settings — do not swap this for a
  request-derived value. A passkey is bound to the RP ID it was registered
  against, so changing it silently invalidates every existing passkey.
  `notes/passkey_views.py` holds the register/login ceremonies; state
  (challenge) lives in the session; `Passkey` rows belong to a user and
  store `credential_id`, `public_key`, `sign_count`.
- **Layout width: `container_class` template variable.** `base.html`'s header
  nav and main wrapper both render `{{ container_class|default:"max-w-4xl" }}`
  so they line up on every page. The editor also passes
  `container_class="max-w-4xl"` so its markdown pane lines up with the fixed
  footer below. Don't reintroduce per-template `max-w-*` wrappers inside
  content blocks — put the class on the view's context instead.
- **Editor settings live in the footer, outside `<form>`.** Title, slug and
  password render in `{% block after_main %}` — a slot defined in `base.html`
  that sits *outside* the constrained `<main>` so a fixed, full-width footer
  bar can span the viewport. The footer has a hidden `data-settings-panel`
  that expands upwards on toggle. Because those inputs live outside
  `<form id="editor-form">`, each one uses HTML5's `form="editor-form"`
  attribute to submit with the editor form. If you add a new `NoteForm`
  field, render it in the footer panel and include `form="editor-form"`,
  otherwise it will be silently dropped on submit.

- **Comments are gated with the note.** `notes/views.py` has `create_comment`
  and `delete_comment`; both call `_gate` *before* anything else, then 404
  when `note.comments_enabled` is off. Anonymous commenters are identified by
  `commenter_name` and `commenter_key` in the session (same session that
  holds the password unlock); a logged-in user's comments get `is_owner`.
  Rate limiting reuses `notes/gate.py` with `scope="comment"` so comment
  posts and unlock attempts on the same note count separately. Comment
  bodies are plain text rendered with `urlize|linebreaksbr` — never pass
  them through `render_markdown`. The anchor fields (`quote`, `prefix`,
  `suffix`, `start_offset`) are stored verbatim (`strip=False`) and exposed
  as `data-*` attributes on each thread's `<li>` for client-side anchoring.
- **Anchoring is resolved in the browser, never on the server.**
  `notes/static/notes/anchors.js` is a pure-string UMD module (exact at
  offset → exact anywhere, context picks between repeats → approximate match
  within 25% of the quote, which beyond 2 errors must also agree with the
  stored prefix/suffix → orphan). `comments.js` maps offsets over the
  concatenated text nodes of `.note-body`, skipping `.mermaid` (replaced by
  SVG at runtime), captures selections with the same mapping, wraps hits in
  `<mark class="comment-highlight">`, and reveals the `data-orphan-badge` on
  misses. Keep the algorithm in `anchors.js` so it stays testable under node.
  Don't put Tailwind display utilities (`flex`, `inline-block`) on elements
  toggled with the `hidden` attribute — the utility wins and the element
  shows.

## SQLite on a volume — critical

Migrations run inside the app container at startup via `entrypoint.sh`
(`migrate --noinput`), **not** as a separate build/release step. The persistent
data volume is only mounted in the running app container — any migration step
that runs outside it (a build-time `RUN`, a Fly-style `release_command`, a
detached one-off without the volume) would execute against an empty ephemeral
file and silently succeed while doing nothing. Keep migrations in
`entrypoint.sh`.

The SQLite file lives on a Coolify-managed persistent volume mounted at
`/app/data`; `DB_PATH` must point inside it (`/app/data/db.sqlite3`). Back the
volume up at the Coolify/host level — there are no Fly volume snapshots anymore.

## Deployment

Deployed on Coolify (`admin.co.tomd.org`); app `notes-tomd-org`, UUID
`xok61kj0vasx16hv3xkv9qj9`, a single `dockerfile`-build container.

- **No CI.** Coolify's GitHub App builds and deploys on every push to `main`.
  There is **no GitHub Actions workflow anymore** (the old `fly-deploy.yml` was
  removed when the site left Fly), so **nothing runs the tests on push** — run
  `python manage.py test notes` locally *before* pushing.
- **Env / secrets** (`ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SECRET_KEY`,
  `DB_PATH`, superuser vars) live in the Coolify app's Environment Variables
  (Coolify UI, or `coolify app env`), **not** `fly secrets`. After changing
  them, restart the app (`coolify app restart <uuid>`). `ALLOWED_HOSTS` and
  `CSRF_TRUSTED_ORIGINS` must include every domain that serves the site — with
  scheme for CSRF (`https://...`), without for ALLOWED_HOSTS.
- **New domains:** add the FQDN to the Coolify app's Domains and a Cloudflare
  CNAME, then update `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS` and restart. The
  `assign-fly-subdomain` skill is Fly-specific and does **not** apply here.
- **Running a management command in prod** (e.g. the `rerender_notes`
  back-fill): the Coolify API can't exec ad-hoc commands, so SSH the host and
  `docker exec`. The container name is `<uuid>-<digits>` and changes each
  deploy, so resolve it first:
  ```sh
  ssh root@admin.co.tomd.org \
    "docker exec \$(docker ps --format '{{.Names}}' | grep xok61kj0vasx16hv3xkv9qj9) \
       python manage.py <command>"
  ```
  No `DEBUG=1` needed in the container.

## Things NOT to do

- Don't move migrations out of `entrypoint.sh` into a separate build/release
  step that doesn't mount the data volume (see SQLite note above).
- Don't re-add a Fly deploy GitHub Action (the Fly app is stopped; Coolify
  deploys via its GitHub App). If you want CI to run tests on push, add a
  *test-only* workflow — don't resurrect Fly deploys.
- Don't switch `STORAGES` away from `CompressedManifestStaticFilesStorage` in
  prod — if you do, update `Dockerfile` and ensure whitenoise can still serve.
- Don't widen the bleach allowlist (`notes/rendering.py`) without a test that
  justifies it.
- Don't store passwords in plaintext, don't log them, don't serialise them.
  Use `Note.set_password` / `check_password`.
- Don't change the shape of `generate_slug()` (6-char base62) without
  considering URL collisions with already-published notes. If you shorten it,
  collisions get likelier; if you lengthen it, old URLs still work.
- Don't change `WEBAUTHN_RP_ID` away from `notes.tomd.org`, don't derive it
  from the request host, and don't add the Coolify alt domain
  (`notes-tomd-org.co.tomd.org`, or the old `.fly.dev`) as an alt origin —
  every existing passkey would stop working.
