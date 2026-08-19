import hashlib
import json
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from notes.models import Note, NoteApiIdempotencyRecord, NoteApiToken


User = get_user_model()


class NoteApiTokenTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tom", password="pw")

    def test_issue_returns_secret_but_only_stores_digest(self):
        token, secret = NoteApiToken.issue(user=self.user, name="Codex")

        self.assertTrue(secret.startswith("nt_"))
        self.assertNotEqual(token.token_digest, secret)
        self.assertNotIn(secret, token.token_digest)
        self.assertEqual(token.prefix, secret[:12])
        self.assertTrue(token.permits("notes:create"))

    def test_create_token_command_prints_secret_once(self):
        out = StringIO()

        call_command("create_note_api_token", username="tom", name="Codex", stdout=out)

        output = out.getvalue()
        self.assertIn("nt_", output)
        self.assertIn("shown only once", output)
        self.assertEqual(NoteApiToken.objects.count(), 1)


class CreateNoteApiTests(TestCase):
    endpoint = "/api/v1/notes"

    def setUp(self):
        self.user = User.objects.create_user(username="tom", password="pw")
        self.token, self.secret = NoteApiToken.issue(user=self.user, name="Codex")

    def auth(self, secret=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {secret or self.secret}"}

    def post(self, payload, **extra):
        return self.client.post(
            self.endpoint,
            data=json.dumps(payload),
            content_type="application/json",
            **self.auth(),
            **extra,
        )

    def test_requires_bearer_token(self):
        response = self.client.post(
            self.endpoint,
            data=json.dumps({"markdown": "hello"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "unauthorized")
        self.assertEqual(response["WWW-Authenticate"], "Bearer")
        self.assertFalse(Note.objects.exists())

    def test_bearer_auth_does_not_require_csrf_cookie(self):
        client = Client(enforce_csrf_checks=True)

        response = client.post(
            self.endpoint,
            data=json.dumps({"markdown": "hello"}),
            content_type="application/json",
            **self.auth(),
        )

        self.assertEqual(response.status_code, 201)

    def test_rejects_invalid_and_revoked_tokens(self):
        invalid = self.client.post(
            self.endpoint,
            data=json.dumps({"markdown": "hello"}),
            content_type="application/json",
            **self.auth("nt_not-a-real-token"),
        )
        self.assertEqual(invalid.status_code, 401)

        self.token.revoke()
        revoked = self.post({"markdown": "hello"})
        self.assertEqual(revoked.status_code, 401)
        self.assertFalse(Note.objects.exists())

    def test_requires_create_scope_and_active_user(self):
        self.token.scopes = "notes:read"
        self.token.save(update_fields=["scopes"])

        forbidden = self.post({"markdown": "hello"})
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(forbidden.json()["error"]["code"], "insufficient_scope")

        self.token.scopes = "notes:create"
        self.token.save(update_fields=["scopes"])
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        inactive = self.post({"markdown": "hello"})
        self.assertEqual(inactive.status_code, 401)

    def test_creates_note_and_returns_share_urls(self):
        response = self.post(
            {
                "title": "Agent note",
                "markdown": "# Hello\n\nShared by an agent.",
                "slug": "agent-note",
                "password": "secret",
            }
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["slug"], "agent-note")
        self.assertEqual(body["title"], "Agent note")
        self.assertEqual(body["url"], "http://testserver/agent-note/")
        self.assertEqual(body["raw_url"], "http://testserver/agent-note/raw")
        self.assertTrue(body["password_protected"])

        note = Note.objects.get(slug="agent-note")
        self.assertIn(">Hello</h1>", note.html)
        self.assertTrue(note.check_password("secret"))
        self.token.refresh_from_db()
        self.assertIsNotNone(self.token.last_used_at)

    def test_generates_slug_when_omitted(self):
        response = self.post({"markdown": "hello"})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.json()["slug"]), 6)

    def test_reports_json_and_form_validation_errors(self):
        malformed = self.client.post(
            self.endpoint,
            data="{",
            content_type="application/json",
            **self.auth(),
        )
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(malformed.json()["error"]["code"], "invalid_json")

        invalid = self.post({"markdown": "hello", "slug": "admin"})
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json()["error"]["code"], "validation_error")
        self.assertIn("slug", invalid.json()["error"]["fields"])

        unknown = self.post({"markdown": "hello", "surprise": True})
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(unknown.json()["error"]["code"], "unknown_fields")

    def test_rejects_non_json_and_oversized_password(self):
        non_json = self.client.post(
            self.endpoint,
            data="markdown=hello",
            content_type="application/x-www-form-urlencoded",
            **self.auth(),
        )
        self.assertEqual(non_json.status_code, 415)

        long_password = self.post({"markdown": "hello", "password": "x" * 129})
        self.assertEqual(long_password.status_code, 422)
        self.assertFalse(Note.objects.exists())

    def test_idempotency_key_replays_same_response(self):
        headers = {"HTTP_IDEMPOTENCY_KEY": "share-request-1"}
        first = self.post({"markdown": "hello"}, **headers)
        second = self.post({"markdown": "hello"}, **headers)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(Note.objects.count(), 1)
        self.assertEqual(second["Idempotent-Replay"], "true")

    def test_idempotency_record_does_not_expose_or_plain_hash_password(self):
        payload = {"markdown": "hello", "password": "guessable"}
        self.post(payload, HTTP_IDEMPOTENCY_KEY="protected-request")

        record = NoteApiIdempotencyRecord.objects.get()
        plain_digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertNotEqual(record.request_digest, plain_digest)
        self.assertNotIn("password", record.response_body)
        self.assertNotIn("guessable", json.dumps(record.response_body))

    def test_idempotency_key_cannot_be_reused_for_different_input(self):
        headers = {"HTTP_IDEMPOTENCY_KEY": "share-request-1"}
        self.post({"markdown": "first"}, **headers)

        response = self.post({"markdown": "second"}, **headers)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "idempotency_conflict")
        self.assertEqual(Note.objects.count(), 1)

    def test_idempotency_key_has_length_limit(self):
        response = self.post(
            {"markdown": "hello"}, HTTP_IDEMPOTENCY_KEY="x" * 201
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Note.objects.exists())

    @override_settings(NOTE_API_MAX_REQUEST_BYTES=32)
    def test_rejects_request_bodies_over_configured_limit(self):
        response = self.post({"markdown": "x" * 100})

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "request_too_large")
        self.assertFalse(Note.objects.exists())
