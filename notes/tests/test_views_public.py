from django.test import TestCase
from django.urls import reverse

from notes.models import Note


class HomeTests(TestCase):
    def test_home_anonymous_returns_200(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)

    def test_home_has_login_link_for_anonymous(self):
        r = self.client.get("/")
        self.assertContains(r, "/login/")


class ViewNoteTests(TestCase):
    def test_view_note_renders_cached_html(self):
        n = Note.objects.create(slug="hello", markdown="# Hi\n\nbody")
        r = self.client.get("/hello/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Hi")
        self.assertContains(r, "body")

    def test_view_note_renders_title_in_head(self):
        Note.objects.create(slug="hello", title="My Note", markdown="x")
        r = self.client.get("/hello/")
        self.assertContains(r, "<title>My Note")

    def test_view_note_404_for_missing_slug(self):
        r = self.client.get("/nope/")
        self.assertEqual(r.status_code, 404)


class RawNoteTests(TestCase):
    def test_raw_returns_markdown_as_text_plain(self):
        Note.objects.create(slug="hello", markdown="# raw source\n")
        r = self.client.get("/hello/raw")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/plain", r["Content-Type"])
        self.assertEqual(r.content.decode("utf-8"), "# raw source\n")

    def test_raw_404_for_missing_slug(self):
        r = self.client.get("/nope/raw")
        self.assertEqual(r.status_code, 404)


class UrlShadowingTests(TestCase):
    def test_login_not_shadowed_by_note_route(self):
        # GET /login/ must resolve to the login view even if a note has that slug.
        # We bypass form validation by writing directly to the DB.
        Note.objects.create(slug="login", markdown="x")
        r = self.client.get("/login/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "name=\"username\"")

    def test_admin_not_shadowed_by_note_route(self):
        Note.objects.create(slug="admin", markdown="x")
        r = self.client.get("/admin/", follow=False)
        # Django admin redirects anonymous to login
        self.assertIn(r.status_code, (200, 302))
        if r.status_code == 302:
            self.assertIn("login", r["Location"])

    def test_new_not_shadowed_by_note_route(self):
        Note.objects.create(slug="new", markdown="x")
        r = self.client.get("/new/", follow=False)
        # /new/ requires login; expect redirect to /login/, not the note content.
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])
