from django.contrib.auth import get_user_model
from django.test import TestCase

from notes.models import Note

User = get_user_model()


class AnonymousHeaderTests(TestCase):
    def test_anonymous_home_has_header_with_login_link(self):
        r = self.client.get("/")
        self.assertContains(r, "<header")
        self.assertContains(r, 'href="/login/"')

    def test_anonymous_view_note_has_no_header(self):
        Note.objects.create(slug="hi", markdown="# body")
        r = self.client.get("/hi/")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "<header")

    def test_anonymous_view_note_has_no_brand_text(self):
        Note.objects.create(slug="hi", markdown="# body")
        r = self.client.get("/hi/")
        self.assertNotContains(r, "notes.tomd.org")

    def test_login_page_has_no_header(self):
        r = self.client.get("/login/")
        self.assertNotContains(r, "<header")

    def test_anonymous_pages_do_not_contain_login_link(self):
        Note.objects.create(slug="hi", markdown="x")
        r = self.client.get("/hi/")
        body = r.content.decode()
        _, _, after_body = body.partition("<body")
        visible, _, _ = after_body.partition("</body>")
        self.assertNotIn('href="/login/"', visible)

    def test_unlock_page_has_no_header(self):
        n = Note(slug="gated", markdown="x")
        n.set_password("pw")
        n.save()
        r = self.client.get("/gated/unlock/?next=/gated/")
        self.assertNotContains(r, "<header")


class AuthedHeaderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="tom", password="pw")

    def setUp(self):
        self.client.login(username="tom", password="pw")

    def test_header_contains_new_note_passkeys_logout(self):
        Note.objects.create(slug="x", markdown="y")
        r = self.client.get("/")
        self.assertContains(r, "<header")
        self.assertContains(r, "New note")
        self.assertContains(r, "Passkeys")
        self.assertContains(r, "Log out")

    def test_header_does_not_contain_brand_text(self):
        r = self.client.get("/")
        self.assertNotContains(r, ">notes.tomd.org<")

    def test_header_does_not_contain_login_link(self):
        r = self.client.get("/")
        self.assertNotContains(r, 'href="/login/"')


class TitleFallbackTests(TestCase):
    def test_note_without_title_has_no_title_h1_element(self):
        Note.objects.create(slug="a", markdown="# From markdown\n\nbody")
        r = self.client.get("/a/")
        body = r.content.decode()
        # There should be no title <h1> placeholder above the note body.
        # The only h1 should be the one produced by the markdown itself.
        self.assertEqual(body.count("<h1"), 1)

    def test_note_body_first_child_has_no_top_margin_rule(self):
        # CSS rule exists in site.css to avoid the gap.
        from pathlib import Path
        css = Path("notes/static/notes/site.css").read_text()
        self.assertIn(".note-body > :first-child", css)
        self.assertIn("margin-top: 0", css)
