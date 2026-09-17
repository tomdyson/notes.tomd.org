import json
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase

from notes.models import Comment, Note, NoteApiToken


User = get_user_model()
ALL_SCOPES = "notes:create comments:read comments:write"


class TokenScopeCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tom", password="pw")

    def test_create_command_accepts_scopes(self):
        call_command(
            "create_note_api_token", username="tom", name="Agent", scopes=ALL_SCOPES, stdout=StringIO()
        )
        token = NoteApiToken.objects.get()
        self.assertTrue(token.permits("comments:read"))
        self.assertTrue(token.permits("comments:write"))

    def test_create_command_defaults_to_note_creation_only(self):
        call_command("create_note_api_token", username="tom", stdout=StringIO())
        token = NoteApiToken.objects.get()
        self.assertTrue(token.permits("notes:create"))
        self.assertFalse(token.permits("comments:read"))

    def test_create_command_rejects_unknown_scope(self):
        with self.assertRaises(CommandError):
            call_command("create_note_api_token", username="tom", scopes="notes:delete", stdout=StringIO())
        self.assertFalse(NoteApiToken.objects.exists())

    def test_set_scopes_command_updates_existing_token_without_reissuing(self):
        token, secret = NoteApiToken.issue(user=self.user, name="Codex")
        out = StringIO()
        call_command("set_note_api_token_scopes", prefix=token.prefix, scopes=ALL_SCOPES, stdout=out)
        token.refresh_from_db()
        self.assertTrue(token.permits("comments:write"))
        self.assertEqual(NoteApiToken.authenticate(secret).pk, token.pk)
        self.assertNotIn(secret, out.getvalue())

    def test_set_scopes_command_rejects_unknown_prefix_scope_and_revoked_token(self):
        token, _ = NoteApiToken.issue(user=self.user, name="Codex")
        with self.assertRaises(CommandError):
            call_command("set_note_api_token_scopes", prefix="nt_nope", scopes=ALL_SCOPES, stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("set_note_api_token_scopes", prefix=token.prefix, scopes="bogus", stdout=StringIO())
        token.revoke()
        with self.assertRaises(CommandError):
            call_command("set_note_api_token_scopes", prefix=token.prefix, scopes=ALL_SCOPES, stdout=StringIO())


class CommentsApiBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tom", password="pw")
        self.token, self.secret = NoteApiToken.issue(user=self.user, name="Agent", scopes=ALL_SCOPES)
        self.note = Note.objects.create(
            slug="talk", title="Talk", markdown="Some **text** to discuss.", comments_enabled=True
        )
        self.endpoint = "/api/v1/notes/talk/comments"

    def auth(self, secret=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {secret or self.secret}"}

    def get(self, endpoint=None):
        return self.client.get(endpoint or self.endpoint, **self.auth())

    def post(self, payload, endpoint=None, **extra):
        return self.client.post(
            endpoint or self.endpoint,
            data=json.dumps(payload),
            content_type="application/json",
            **self.auth(),
            **extra,
        )

    def set_scopes(self, scopes):
        self.token.scopes = scopes
        self.token.save(update_fields=["scopes"])


class ListCommentsApiTests(CommentsApiBase):
    def test_requires_bearer_token(self):
        r = self.client.get(self.endpoint)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r["WWW-Authenticate"], "Bearer")

    def test_requires_read_scope(self):
        self.set_scopes("notes:create comments:write")
        r = self.get()
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"]["code"], "insufficient_scope")
        self.assertIn("comments:read", r.json()["error"]["message"])

    def test_unknown_note_is_a_json_404(self):
        r = self.get("/api/v1/notes/nope/comments")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["error"]["code"], "not_found")

    def test_unsupported_method(self):
        r = self.client.put(self.endpoint, data="{}", content_type="application/json", **self.auth())
        self.assertEqual(r.status_code, 405)
        self.assertEqual(r.json()["error"]["code"], "method_not_allowed")
        self.assertIn("GET", r["Allow"])

    def test_empty_thread(self):
        r = self.get()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["comments"], [])
        self.assertEqual(body["note"]["slug"], "talk")
        self.assertEqual(body["note"]["title"], "Talk")
        self.assertTrue(body["note"]["comments_enabled"])
        self.assertFalse(body["note"]["password_protected"])
        self.assertTrue(body["note"]["url"].endswith("/talk/"))

    def test_lists_threads_with_nested_replies_and_anchors(self):
        top = Comment.objects.create(
            note=self.note, author_name="Ann", body="Typo?", quote="text to",
            prefix="Some ", suffix=" discuss.", start_offset=5,
        )
        reply = Comment.objects.create(
            note=self.note, parent=top, author_name="tom", body="Fixed.", is_owner=True
        )
        plain = Comment.objects.create(note=self.note, author_name="Bob", body="Nice note")

        comments = self.get().json()["comments"]

        self.assertEqual([c["id"] for c in comments], [top.pk, plain.pk])
        first = comments[0]
        self.assertEqual(first["author_name"], "Ann")
        self.assertEqual(first["body"], "Typo?")
        self.assertFalse(first["is_owner"])
        self.assertIsNone(first["parent"])
        self.assertEqual(first["created_at"], top.created_at.isoformat())
        self.assertEqual(
            first["anchor"],
            {"quote": "text to", "prefix": "Some ", "suffix": " discuss.",
             "start_offset": 5, "quote_in_note": True},
        )
        self.assertEqual(len(first["replies"]), 1)
        self.assertEqual(first["replies"][0]["id"], reply.pk)
        self.assertEqual(first["replies"][0]["parent"], top.pk)
        self.assertTrue(first["replies"][0]["is_owner"])
        self.assertNotIn("replies", first["replies"][0])
        self.assertIsNone(comments[1]["anchor"])
        self.assertEqual(comments[1]["replies"], [])

    def test_never_exposes_the_commenter_key(self):
        Comment.objects.create(note=self.note, author_name="Ann", body="x", author_key="secret-key")
        self.assertNotIn("secret-key", self.get().content.decode())

    def test_quote_in_note_is_false_once_the_text_is_gone(self):
        Comment.objects.create(note=self.note, author_name="Ann", body="x", quote="vanished words")
        anchor = self.get().json()["comments"][0]["anchor"]
        self.assertFalse(anchor["quote_in_note"])

    def test_quote_is_matched_against_rendered_text_not_markdown(self):
        # "Some **text** to" renders as "Some text to".
        Comment.objects.create(note=self.note, author_name="Ann", body="x", quote="Some text to")
        Comment.objects.create(note=self.note, author_name="Ann", body="y", quote="**text**")
        anchors = [c["anchor"]["quote_in_note"] for c in self.get().json()["comments"]]
        self.assertEqual(anchors, [True, False])

    def test_owner_token_reads_password_protected_and_disabled_notes(self):
        Comment.objects.create(note=self.note, author_name="Ann", body="hello")
        self.note.set_password("pw")
        self.note.comments_enabled = False
        self.note.save()
        body = self.get().json()
        self.assertEqual(len(body["comments"]), 1)
        self.assertTrue(body["note"]["password_protected"])
        self.assertFalse(body["note"]["comments_enabled"])


class CreateCommentApiTests(CommentsApiBase):
    def test_requires_write_scope(self):
        self.set_scopes("notes:create comments:read")
        r = self.post({"body": "hi"})
        self.assertEqual(r.status_code, 403)
        self.assertIn("comments:write", r.json()["error"]["message"])
        self.assertFalse(Comment.objects.exists())

    def test_bearer_auth_does_not_require_csrf_cookie(self):
        client = Client(enforce_csrf_checks=True)
        r = client.post(
            self.endpoint, data=json.dumps({"body": "hi"}),
            content_type="application/json", **self.auth(),
        )
        self.assertEqual(r.status_code, 201)

    def test_creates_comment_as_the_note_owner(self):
        r = self.post({"body": "Thanks all"})
        self.assertEqual(r.status_code, 201)
        c = Comment.objects.get()
        self.assertEqual(c.note, self.note)
        self.assertEqual(c.author_name, "tom")
        self.assertTrue(c.is_owner)
        self.assertEqual(c.author_key, "")
        body = r.json()
        self.assertEqual(body["id"], c.pk)
        self.assertEqual(body["body"], "Thanks all")
        self.assertTrue(body["is_owner"])
        self.assertIsNone(body["anchor"])
        self.assertTrue(body["url"].endswith(f"/talk/#comment-{c.pk}"))

    def test_author_name_can_be_overridden(self):
        self.post({"body": "hi", "author_name": "Tom (via Claude)"})
        self.assertEqual(Comment.objects.get().author_name, "Tom (via Claude)")

    def test_conflict_when_comments_are_disabled(self):
        Note.objects.filter(pk=self.note.pk).update(comments_enabled=False)
        r = self.post({"body": "hi"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"]["code"], "comments_disabled")
        self.assertFalse(Comment.objects.exists())

    def test_reply_to_a_thread(self):
        top = Comment.objects.create(note=self.note, author_name="Ann", body="Q?")
        r = self.post({"body": "A.", "parent": top.pk})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Comment.objects.get(body="A.").parent, top)
        self.assertEqual(r.json()["parent"], top.pk)
        self.assertNotIn("replies", r.json())

    def test_reply_to_reply_or_foreign_comment_is_a_validation_error(self):
        top = Comment.objects.create(note=self.note, author_name="Ann", body="Q?")
        reply = Comment.objects.create(note=self.note, parent=top, author_name="Bob", body="A")
        other = Note.objects.create(slug="other", markdown="x", comments_enabled=True)
        foreign = Comment.objects.create(note=other, author_name="Ann", body="Q")
        for parent in (reply.pk, foreign.pk, 99999):
            r = self.post({"body": "x", "parent": parent})
            self.assertEqual(r.status_code, 422, parent)
            self.assertIn("parent", r.json()["error"]["fields"])
        self.assertEqual(self.note.comments.count(), 2)

    def test_anchored_comment_with_only_a_quote(self):
        r = self.post({"body": "Typo", "quote": "text to"})
        self.assertEqual(r.status_code, 201)
        c = Comment.objects.get()
        self.assertEqual((c.quote, c.prefix, c.suffix, c.start_offset), ("text to", "", "", None))
        self.assertEqual(
            r.json()["anchor"],
            {"quote": "text to", "prefix": "", "suffix": "", "start_offset": None, "quote_in_note": True},
        )

    def test_anchor_context_is_stored_verbatim(self):
        self.post({"body": "x", "quote": "text to", "prefix": "Some ", "suffix": " discuss.", "start_offset": 5})
        c = Comment.objects.get()
        self.assertEqual((c.prefix, c.suffix, c.start_offset), ("Some ", " discuss.", 5))

    def test_response_flags_a_quote_missing_from_the_note(self):
        r = self.post({"body": "x", "quote": "**text**"})
        self.assertEqual(r.status_code, 201)
        self.assertFalse(r.json()["anchor"]["quote_in_note"])

    def test_validation_errors(self):
        cases = [
            ({}, "body"),
            ({"body": "   "}, "body"),
            ({"body": "x" * 5001}, "body"),
            ({"body": 5}, "body"),
            ({"body": "x", "quote": "q" * 2001}, "quote"),
            ({"body": "x", "start_offset": -1}, "start_offset"),
            ({"body": "x", "start_offset": "5"}, "start_offset"),
            ({"body": "x", "parent": "1"}, "parent"),
            ({"body": "x", "parent": True}, "parent"),
            ({"body": "x", "author_name": "n" * 81}, "author_name"),
        ]
        for payload, field in cases:
            r = self.post(payload)
            self.assertEqual(r.status_code, 422, payload)
            self.assertEqual(r.json()["error"]["code"], "validation_error")
            self.assertIn(field, r.json()["error"]["fields"], payload)
        self.assertFalse(Comment.objects.exists())

    def test_rejects_unknown_fields_bad_json_and_wrong_content_type(self):
        r = self.post({"body": "x", "is_owner": False})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "unknown_fields")
        r = self.client.post(self.endpoint, data="{nope", content_type="application/json", **self.auth())
        self.assertEqual(r.json()["error"]["code"], "invalid_json")
        r = self.client.post(self.endpoint, data="body=x", content_type="text/plain", **self.auth())
        self.assertEqual(r.status_code, 415)
        self.assertFalse(Comment.objects.exists())

    def test_idempotency_key_replays_instead_of_duplicating(self):
        first = self.post({"body": "once"}, HTTP_IDEMPOTENCY_KEY="k1")
        again = self.post({"body": "once"}, HTTP_IDEMPOTENCY_KEY="k1")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again["Idempotent-Replay"], "true")
        self.assertEqual(again.json(), first.json())
        self.assertEqual(Comment.objects.count(), 1)

    def test_idempotency_key_reuse_with_different_input_conflicts(self):
        self.post({"body": "once"}, HTTP_IDEMPOTENCY_KEY="k1")
        r = self.post({"body": "different"}, HTTP_IDEMPOTENCY_KEY="k1")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"]["code"], "idempotency_conflict")
        other = Note.objects.create(slug="other", markdown="x", comments_enabled=True)
        r = self.post({"body": "once"}, endpoint="/api/v1/notes/other/comments", HTTP_IDEMPOTENCY_KEY="k1")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(Comment.objects.count(), 1)

    def test_api_posts_are_not_subject_to_the_visitor_rate_limit(self):
        for i in range(12):
            self.assertEqual(self.post({"body": f"c{i}"}).status_code, 201)


class DeleteCommentApiTests(CommentsApiBase):
    def setUp(self):
        super().setUp()
        self.comment = Comment.objects.create(note=self.note, author_name="Ann", body="spam")

    def delete(self, pk=None, slug="talk"):
        return self.client.delete(f"/api/v1/notes/{slug}/comments/{pk or self.comment.pk}", **self.auth())

    def test_requires_write_scope(self):
        self.set_scopes("comments:read")
        self.assertEqual(self.delete().status_code, 403)
        self.assertTrue(Comment.objects.exists())

    def test_deletes_comment_and_its_replies(self):
        Comment.objects.create(note=self.note, parent=self.comment, author_name="Bob", body="re")
        r = self.delete()
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r.content, b"")
        self.assertFalse(Comment.objects.exists())

    def test_works_when_comments_are_disabled(self):
        Note.objects.filter(pk=self.note.pk).update(comments_enabled=False)
        self.assertEqual(self.delete().status_code, 204)

    def test_404_for_unknown_comment_or_wrong_note(self):
        Note.objects.create(slug="other", markdown="x")
        self.assertEqual(self.delete(pk=99999).status_code, 404)
        r = self.delete(slug="other")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["error"]["code"], "not_found")
        self.assertTrue(Comment.objects.filter(pk=self.comment.pk).exists())

    def test_only_delete_is_allowed(self):
        r = self.client.get(f"/api/v1/notes/talk/comments/{self.comment.pk}", **self.auth())
        self.assertEqual(r.status_code, 405)


class CreateNoteWithCommentsApiTests(TestCase):
    endpoint = "/api/v1/notes"

    def setUp(self):
        self.user = User.objects.create_user(username="tom", password="pw")
        self.token, self.secret = NoteApiToken.issue(user=self.user, name="Agent")

    def post(self, payload):
        return self.client.post(
            self.endpoint, data=json.dumps(payload), content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.secret}",
        )

    def test_comments_default_off_and_are_reported(self):
        r = self.post({"markdown": "hello"})
        self.assertEqual(r.status_code, 201)
        self.assertFalse(r.json()["comments_enabled"])
        self.assertFalse(Note.objects.get().comments_enabled)

    def test_comments_can_be_enabled_at_creation(self):
        r = self.post({"markdown": "hello", "comments_enabled": True})
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()["comments_enabled"])
        self.assertTrue(Note.objects.get().comments_enabled)

    def test_comments_enabled_must_be_a_boolean(self):
        r = self.post({"markdown": "hello", "comments_enabled": "yes"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("comments_enabled", r.json()["error"]["fields"])
        self.assertFalse(Note.objects.exists())
