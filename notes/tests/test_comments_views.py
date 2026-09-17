from django.contrib.auth import get_user_model
from django.test import TestCase

from notes import gate
from notes.models import Comment, Note

User = get_user_model()


class CommentsBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="tom", password="pw", is_staff=True, is_superuser=True
        )

    def setUp(self):
        gate.reset_rate_limiter()
        self.note = Note.objects.create(
            slug="talk", markdown="Some text to discuss.", comments_enabled=True
        )

    def login(self):
        self.client.login(username="tom", password="pw")

    def post_comment(self, **data):
        payload = {"name": "Ann", "body": "Hello"}
        payload.update(data)
        return self.client.post("/talk/comments/", payload)


class CommentThreadRenderingTests(CommentsBase):
    def test_no_thread_when_comments_disabled(self):
        Note.objects.filter(pk=self.note.pk).update(comments_enabled=False)
        r = self.client.get("/talk/")
        self.assertNotContains(r, 'id="comments"')
        self.assertNotContains(r, "/talk/comments/")

    def test_empty_thread_shows_form_and_placeholder(self):
        r = self.client.get("/talk/")
        self.assertContains(r, 'id="comments"')
        self.assertContains(r, "No comments yet")
        self.assertContains(r, 'action="/talk/comments/"')
        self.assertContains(r, 'hx-post="/talk/comments/"')
        self.assertContains(r, 'hx-target="#comments"')
        self.assertContains(r, 'name="body"')

    def test_first_time_visitor_is_asked_for_a_name(self):
        r = self.client.get("/talk/")
        self.assertRegex(r.content.decode(), r'<input[^>]*name="name"[^>]*required')
        self.assertNotContains(r, "Commenting as")

    def test_returning_commenter_sees_their_name(self):
        self.post_comment(name="Ann", body="first")
        r = self.client.get("/talk/")
        self.assertContains(r, "Commenting as")
        self.assertContains(r, 'value="Ann"')
        self.assertNotRegex(r.content.decode(), r'<input[^>]*name="name"[^>]*required')

    def test_owner_is_not_asked_for_a_name(self):
        self.login()
        r = self.client.get("/talk/")
        self.assertNotContains(r, 'name="name"')

    def test_renders_comments_with_replies_nested(self):
        top = Comment.objects.create(note=self.note, author_name="Ann", body="Question?")
        Comment.objects.create(note=self.note, parent=top, author_name="Bob", body="Answer.")
        r = self.client.get("/talk/")
        html = r.content.decode()
        self.assertContains(r, f'id="comment-{top.pk}"')
        self.assertContains(r, "Ann")
        self.assertContains(r, "Question?")
        self.assertContains(r, "Bob")
        self.assertContains(r, "Answer.")
        # The reply sits inside the parent's list item.
        parent_start = html.index(f'id="comment-{top.pk}"')
        reply_pos = html.index("Answer.")
        self.assertGreater(reply_pos, parent_start)
        self.assertContains(r, f'name="parent" value="{top.pk}"')

    def test_body_is_escaped_and_linebreaks_and_links_rendered(self):
        Comment.objects.create(
            note=self.note,
            author_name="<b>Ann</b>",
            body="<script>alert(1)</script>\nsee https://example.com",
        )
        r = self.client.get("/talk/")
        self.assertNotContains(r, "<script>alert(1)</script>")
        self.assertContains(r, "&lt;script&gt;")
        self.assertContains(r, "&lt;b&gt;Ann&lt;/b&gt;")
        self.assertContains(r, "<br>")
        self.assertContains(r, 'href="https://example.com"')

    def test_anchored_comment_exposes_selector_and_quote(self):
        c = Comment.objects.create(
            note=self.note,
            author_name="Ann",
            body="Typo",
            quote="text to",
            prefix="Some ",
            suffix=" discuss.",
            start_offset=5,
        )
        r = self.client.get("/talk/")
        html = r.content.decode()
        self.assertRegex(
            html,
            rf'<li[^>]*id="comment-{c.pk}"[^>]*data-quote="text to"',
        )
        self.assertContains(r, 'data-prefix="Some "')
        self.assertContains(r, 'data-suffix=" discuss."')
        self.assertContains(r, 'data-offset="5"')
        self.assertContains(r, "<blockquote")

    def test_owner_comment_gets_author_badge(self):
        Comment.objects.create(note=self.note, author_name="tom", body="Thanks", is_owner=True)
        r = self.client.get("/talk/")
        self.assertContains(r, "author")

    def test_delete_button_only_for_own_comments(self):
        self.post_comment(name="Ann", body="mine")
        mine = Comment.objects.get(body="mine")
        other = Comment.objects.create(note=self.note, author_name="Bob", body="theirs", author_key="zzz")
        r = self.client.get("/talk/")
        self.assertContains(r, f"/talk/comments/{mine.pk}/delete/")
        self.assertNotContains(r, f"/talk/comments/{other.pk}/delete/")

    def test_owner_sees_delete_on_every_comment(self):
        c = Comment.objects.create(note=self.note, author_name="Bob", body="x", author_key="zzz")
        self.login()
        r = self.client.get("/talk/")
        self.assertContains(r, f"/talk/comments/{c.pk}/delete/")

    def test_thread_is_gated_with_the_note(self):
        self.note.set_password("pw")
        self.note.save()
        r = self.client.get("/talk/")
        self.assertEqual(r.status_code, 302)


    def test_anchoring_scripts_load_only_when_comments_enabled(self):
        r = self.client.get("/talk/")
        self.assertContains(r, "notes/anchors.js")
        self.assertContains(r, "notes/comments.js")
        Note.objects.filter(pk=self.note.pk).update(comments_enabled=False)
        r = self.client.get("/talk/")
        self.assertNotContains(r, "notes/anchors.js")
        self.assertNotContains(r, "notes/comments.js")

    def test_only_the_new_comment_form_carries_anchor_fields(self):
        Comment.objects.create(note=self.note, author_name="Ann", body="Q")
        r = self.client.get("/talk/")
        html = r.content.decode()
        for field in ("quote", "prefix", "suffix", "start_offset"):
            self.assertRegex(
                html,
                rf'<input(?=[^>]*\btype="hidden")(?=[^>]*\bname="{field}")[^>]*>',
            )
            self.assertEqual(html.count(f'name="{field}"'), 1, field)
        self.assertContains(r, "data-anchor-chip")

    def test_anchor_survives_a_failed_submission(self):
        r = self.post_comment(
            name="", body="x", quote="text to", prefix="Some ", suffix=" discuss.", start_offset="5"
        )
        self.assertEqual(r.status_code, 400)
        html = r.content.decode()
        self.assertRegex(html, r'name="quote"[^>]*value="text to"')
        self.assertRegex(html, r'name="prefix"[^>]*value="Some "')
        self.assertRegex(html, r'name="suffix"[^>]*value=" discuss."')
        self.assertRegex(html, r'name="start_offset"[^>]*value="5"')

    def test_anchored_comment_has_a_hidden_orphan_badge(self):
        Comment.objects.create(
            note=self.note, author_name="Ann", body="x", quote="text to", start_offset=5
        )
        Comment.objects.create(note=self.note, author_name="Bob", body="plain")
        r = self.client.get("/talk/")
        html = r.content.decode()
        self.assertEqual(html.count("data-orphan-badge"), 1)
        self.assertRegex(html, r'<span[^>]*data-orphan-badge[^>]*\bhidden')


class CommentCreateTests(CommentsBase):
    def test_get_not_allowed(self):
        self.assertEqual(self.client.get("/talk/comments/").status_code, 405)

    def test_404_when_comments_disabled(self):
        Note.objects.filter(pk=self.note.pk).update(comments_enabled=False)
        self.assertEqual(self.post_comment().status_code, 404)
        self.assertEqual(Comment.objects.count(), 0)

    def test_locked_note_redirects_to_unlock(self):
        self.note.set_password("pw")
        self.note.save()
        r = self.post_comment()
        self.assertEqual(r.status_code, 302)
        self.assertIn("/talk/unlock/", r["Location"])
        self.assertEqual(Comment.objects.count(), 0)

    def test_unlocked_note_accepts_comment(self):
        self.note.set_password("pw")
        self.note.save()
        self.client.post("/talk/unlock/?next=/talk/", {"password": "pw"})
        r = self.post_comment()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Comment.objects.count(), 1)

    def test_creates_comment_without_a_scroll_fragment(self):
        r = self.post_comment(name="Ann", body="Hello there")
        c = Comment.objects.get()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/talk/")
        self.assertEqual(c.author_name, "Ann")
        self.assertEqual(c.body, "Hello there")
        self.assertIsNone(c.parent)
        self.assertFalse(c.is_owner)
        self.assertFalse(c.is_anchored)

    def test_htmx_create_returns_updated_comment_rail(self):
        r = self.client.post(
            "/talk/comments/",
            {"name": "Ann", "body": "Hello via HTMX"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="comments"')
        self.assertContains(r, 'data-has-comments="true"')
        self.assertContains(r, "Hello via HTMX")
        self.assertNotContains(r, "<!doctype html>")

    def test_htmx_validation_error_returns_form_fragment(self):
        r = self.client.post(
            "/talk/comments/",
            {"name": "", "body": "Hello"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="comments"')
        self.assertContains(r, "Please add your name.")
        self.assertEqual(Comment.objects.count(), 0)

    def test_first_comment_remembers_name_and_issues_key(self):
        self.post_comment(name="Ann")
        c = Comment.objects.get()
        session = self.client.session
        self.assertEqual(session["commenter_name"], "Ann")
        self.assertTrue(session["commenter_key"])
        self.assertEqual(c.author_key, session["commenter_key"])

    def test_second_comment_uses_remembered_name_and_same_key(self):
        self.post_comment(name="Ann", body="one")
        self.post_comment(name="", body="two")
        names = list(Comment.objects.values_list("author_name", flat=True))
        keys = set(Comment.objects.values_list("author_key", flat=True))
        self.assertEqual(names, ["Ann", "Ann"])
        self.assertEqual(len(keys), 1)

    def test_supplying_a_new_name_updates_the_remembered_one(self):
        self.post_comment(name="Ann", body="one")
        self.post_comment(name="Annie", body="two")
        self.assertEqual(self.client.session["commenter_name"], "Annie")

    def test_name_required_the_first_time(self):
        r = self.post_comment(name="   ")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Comment.objects.count(), 0)
        self.assertContains(r, "name", status_code=400)

    def test_name_is_capped(self):
        r = self.post_comment(name="x" * 81)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Comment.objects.count(), 0)

    def test_body_required(self):
        r = self.post_comment(body="  \n ")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Comment.objects.count(), 0)

    def test_body_is_capped(self):
        r = self.post_comment(body="x" * 5001)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Comment.objects.count(), 0)

    def test_reply_to_top_level_comment(self):
        top = Comment.objects.create(note=self.note, author_name="Ann", body="Q")
        r = self.post_comment(name="Bob", body="A", parent=top.pk)
        self.assertEqual(r.status_code, 302)
        reply = Comment.objects.get(body="A")
        self.assertEqual(reply.parent, top)

    def test_reply_inherits_thread_anchor_and_drops_its_own(self):
        top = Comment.objects.create(
            note=self.note, author_name="Ann", body="Q", quote="text to"
        )
        self.post_comment(name="Bob", body="A", parent=top.pk, quote="Some", prefix="x")
        reply = Comment.objects.get(body="A")
        self.assertFalse(reply.is_anchored)
        self.assertEqual(reply.prefix, "")

    def test_reply_to_a_reply_is_rejected(self):
        top = Comment.objects.create(note=self.note, author_name="Ann", body="Q")
        reply = Comment.objects.create(note=self.note, parent=top, author_name="Bob", body="A")
        r = self.post_comment(name="Cy", body="B", parent=reply.pk)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Comment.objects.count(), 2)

    def test_reply_to_comment_on_another_note_is_rejected(self):
        other = Note.objects.create(slug="other", markdown="x", comments_enabled=True)
        foreign = Comment.objects.create(note=other, author_name="Ann", body="Q")
        r = self.post_comment(name="Bob", body="A", parent=foreign.pk)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.note.comments.count(), 0)

    def test_anchored_comment_stores_selector(self):
        self.post_comment(
            name="Ann",
            body="Typo",
            quote="text to",
            prefix="Some ",
            suffix=" discuss.",
            start_offset="5",
        )
        c = Comment.objects.get()
        self.assertTrue(c.is_anchored)
        self.assertEqual((c.quote, c.prefix, c.suffix, c.start_offset), ("text to", "Some ", " discuss.", 5))

    def test_quote_is_capped(self):
        r = self.post_comment(quote="x" * 2001)
        self.assertEqual(r.status_code, 400)

    def test_negative_offset_is_rejected(self):
        r = self.post_comment(quote="text", start_offset="-1")
        self.assertEqual(r.status_code, 400)

    def test_owner_comment_uses_account_name_and_is_marked(self):
        self.login()
        r = self.post_comment(name="", body="Thanks!")
        self.assertEqual(r.status_code, 302)
        c = Comment.objects.get()
        self.assertEqual(c.author_name, "tom")
        self.assertTrue(c.is_owner)
        self.assertEqual(c.author_key, "")

    def test_rate_limited_after_ten_comments_in_a_minute(self):
        for i in range(10):
            self.assertEqual(self.post_comment(body=f"c{i}").status_code, 302)
        r = self.post_comment(body="one too many")
        self.assertEqual(r.status_code, 429)
        self.assertEqual(Comment.objects.count(), 10)

    def test_comment_rate_limit_is_separate_from_unlock_attempts(self):
        for _ in range(3):
            gate.record_failed_attempt(self.client.get("/talk/").wsgi_request, "talk")
        self.assertEqual(self.post_comment().status_code, 302)

    def test_unknown_note_404(self):
        self.assertEqual(self.client.post("/nope/comments/", {"body": "x"}).status_code, 404)


class CommentDeleteTests(CommentsBase):
    def setUp(self):
        super().setUp()
        self.post_comment(name="Ann", body="mine")
        self.mine = Comment.objects.get(body="mine")
        self.other = Comment.objects.create(
            note=self.note, author_name="Bob", body="theirs", author_key="someone-else"
        )

    def test_get_not_allowed(self):
        r = self.client.get(f"/talk/comments/{self.mine.pk}/delete/")
        self.assertEqual(r.status_code, 405)

    def test_commenter_can_delete_own_comment(self):
        r = self.client.post(f"/talk/comments/{self.mine.pk}/delete/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/talk/#comments")
        self.assertFalse(Comment.objects.filter(pk=self.mine.pk).exists())

    def test_htmx_delete_returns_updated_comment_rail(self):
        r = self.client.post(
            f"/talk/comments/{self.mine.pk}/delete/", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="comments"')
        self.assertNotContains(r, "mine")
        self.assertContains(r, "theirs")

    def test_commenter_cannot_delete_someone_elses_comment(self):
        r = self.client.post(f"/talk/comments/{self.other.pk}/delete/")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Comment.objects.filter(pk=self.other.pk).exists())

    def test_stranger_without_key_cannot_delete(self):
        self.client.logout()  # fresh session
        r = self.client.post(f"/talk/comments/{self.mine.pk}/delete/")
        self.assertEqual(r.status_code, 403)

    def test_owner_can_delete_any_comment(self):
        self.login()
        r = self.client.post(f"/talk/comments/{self.other.pk}/delete/")
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Comment.objects.filter(pk=self.other.pk).exists())

    def test_deleting_thread_removes_replies(self):
        Comment.objects.create(note=self.note, parent=self.mine, author_name="Bob", body="re")
        self.client.post(f"/talk/comments/{self.mine.pk}/delete/")
        self.assertEqual(Comment.objects.filter(body="re").count(), 0)

    def test_locked_note_redirects_to_unlock(self):
        self.note.set_password("pw")
        self.note.save()
        r = self.client.post(f"/talk/comments/{self.mine.pk}/delete/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/talk/unlock/", r["Location"])
        self.assertTrue(Comment.objects.filter(pk=self.mine.pk).exists())

    def test_404_when_comments_disabled(self):
        Note.objects.filter(pk=self.note.pk).update(comments_enabled=False)
        self.login()
        r = self.client.post(f"/talk/comments/{self.mine.pk}/delete/")
        self.assertEqual(r.status_code, 404)

    def test_404_for_comment_on_another_note(self):
        other = Note.objects.create(slug="other", markdown="x", comments_enabled=True)
        self.login()
        r = self.client.post(f"/other/comments/{self.mine.pk}/delete/")
        self.assertEqual(r.status_code, 404)
        self.assertTrue(Comment.objects.filter(pk=self.mine.pk).exists())
