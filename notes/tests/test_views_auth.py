from django.contrib.auth import get_user_model
from django.test import TestCase

from notes.models import Note

User = get_user_model()


class AuthBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="tom", password="pw", is_staff=True, is_superuser=True
        )

    def login(self):
        self.client.login(username="tom", password="pw")


class NewNoteTests(AuthBase):
    def test_new_requires_login(self):
        r = self.client.get("/new/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])

    def test_authed_get_renders_editor(self):
        self.login()
        r = self.client.get("/new/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'name="markdown"')
        self.assertContains(r, 'name="slug"')

    def test_authed_post_blank_slug_creates_note_with_random_slug(self):
        self.login()
        r = self.client.post(
            "/new/",
            {"slug": "", "title": "", "markdown": "# hi", "password": "", "clear_password": ""},
        )
        self.assertEqual(r.status_code, 302)
        n = Note.objects.get()
        self.assertEqual(len(n.slug), 6)
        self.assertEqual(r["Location"], f"/{n.slug}/")

    def test_authed_post_custom_slug_creates_note(self):
        self.login()
        r = self.client.post(
            "/new/",
            {"slug": "hello", "title": "Hi", "markdown": "x", "password": "", "clear_password": ""},
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/hello/")
        self.assertTrue(Note.objects.filter(slug="hello").exists())

    def test_rejects_reserved_slug(self):
        self.login()
        r = self.client.post(
            "/new/",
            {"slug": "admin", "title": "", "markdown": "x", "password": "", "clear_password": ""},
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "reserved")
        self.assertFalse(Note.objects.filter(slug="admin").exists())

    def test_rejects_invalid_slug_chars(self):
        self.login()
        r = self.client.post(
            "/new/",
            {"slug": "has space", "title": "", "markdown": "x", "password": "", "clear_password": ""},
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Note.objects.filter(slug="has space").exists())

    def test_rejects_duplicate_slug(self):
        self.login()
        Note.objects.create(slug="dup", markdown="x")
        r = self.client.post(
            "/new/",
            {"slug": "dup", "title": "", "markdown": "x", "password": "", "clear_password": ""},
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "already")


class EditNoteTests(AuthBase):
    def setUp(self):
        self.note = Note.objects.create(slug="n1", markdown="original")

    def test_edit_requires_login(self):
        r = self.client.get("/n1/edit/")
        self.assertEqual(r.status_code, 302)

    def test_edit_get_renders_existing_content(self):
        self.login()
        r = self.client.get("/n1/edit/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "original")

    def test_edit_post_updates_markdown_and_rerenders_html(self):
        self.login()
        r = self.client.post(
            "/n1/edit/",
            {"slug": "n1", "title": "", "markdown": "# new body", "password": "", "clear_password": ""},
        )
        self.assertEqual(r.status_code, 302)
        self.note.refresh_from_db()
        self.assertEqual(self.note.markdown, "# new body")
        self.assertIn("new body", self.note.html)

    def test_edit_can_change_slug(self):
        self.login()
        r = self.client.post(
            "/n1/edit/",
            {"slug": "n1-renamed", "title": "", "markdown": "x", "password": "", "clear_password": ""},
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/n1-renamed/")
        self.assertTrue(Note.objects.filter(slug="n1-renamed").exists())


class DeleteNoteTests(AuthBase):
    def setUp(self):
        self.note = Note.objects.create(slug="del", markdown="x")

    def test_delete_requires_login(self):
        r = self.client.post("/del/delete/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])

    def test_delete_requires_post(self):
        self.login()
        r = self.client.get("/del/delete/")
        self.assertIn(r.status_code, (302, 405))
        self.assertTrue(Note.objects.filter(slug="del").exists())

    def test_delete_post_removes_note(self):
        self.login()
        r = self.client.post("/del/delete/")
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Note.objects.filter(slug="del").exists())

    def test_delete_frees_slug_for_reuse(self):
        self.login()
        self.client.post("/del/delete/")
        Note.objects.create(slug="del", markdown="reborn")
        self.assertTrue(Note.objects.filter(slug="del").exists())


class DashboardTests(AuthBase):
    def test_dashboard_lists_notes_when_authed(self):
        Note.objects.create(slug="a", title="Alpha", markdown="x")
        Note.objects.create(slug="b", title="Beta", markdown="y")
        self.login()
        r = self.client.get("/")
        self.assertContains(r, "Alpha")
        self.assertContains(r, "Beta")

    def test_home_anonymous_404s_and_does_not_leak_notes(self):
        Note.objects.create(slug="a", title="Alpha", markdown="x")
        r = self.client.get("/")
        self.assertEqual(r.status_code, 404)
        self.assertNotContains(r, "Alpha", status_code=404)


class ToggleTaskTests(AuthBase):
    def setUp(self):
        self.note = Note.objects.create(
            slug="t1", markdown="- [ ] one\n- [x] two\n"
        )

    def test_toggle_requires_login(self):
        r = self.client.post("/t1/toggle/", {"index": "0"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])
        self.note.refresh_from_db()
        self.assertEqual(self.note.markdown, "- [ ] one\n- [x] two\n")

    def test_toggle_requires_post(self):
        self.login()
        r = self.client.get("/t1/toggle/")
        self.assertEqual(r.status_code, 405)

    def test_toggle_flips_unchecked_to_checked(self):
        self.login()
        r = self.client.post("/t1/toggle/", {"index": "0"})
        self.assertEqual(r.status_code, 200)
        self.note.refresh_from_db()
        self.assertEqual(self.note.markdown, "- [x] one\n- [x] two\n")

    def test_toggle_flips_checked_to_unchecked(self):
        self.login()
        r = self.client.post("/t1/toggle/", {"index": "1"})
        self.assertEqual(r.status_code, 200)
        self.note.refresh_from_db()
        self.assertEqual(self.note.markdown, "- [ ] one\n- [ ] two\n")

    def test_toggle_re_renders_html(self):
        self.login()
        self.client.post("/t1/toggle/", {"index": "0"})
        self.note.refresh_from_db()
        self.assertEqual(self.note.html.count("checked"), 2)

    def test_toggle_invalid_index_returns_400(self):
        self.login()
        r = self.client.post("/t1/toggle/", {"index": "abc"})
        self.assertEqual(r.status_code, 400)

    def test_toggle_missing_index_returns_400(self):
        self.login()
        r = self.client.post("/t1/toggle/", {})
        self.assertEqual(r.status_code, 400)

    def test_toggle_out_of_range_returns_404(self):
        self.login()
        r = self.client.post("/t1/toggle/", {"index": "99"})
        self.assertEqual(r.status_code, 404)
        self.note.refresh_from_db()
        self.assertEqual(self.note.markdown, "- [ ] one\n- [x] two\n")

    def test_toggle_unknown_slug_404(self):
        self.login()
        r = self.client.post("/no-such-note/toggle/", {"index": "0"})
        self.assertEqual(r.status_code, 404)


class PasswordOnEditorTests(AuthBase):
    def test_setting_password_on_create(self):
        self.login()
        self.client.post(
            "/new/",
            {"slug": "p1", "title": "", "markdown": "x", "password": "secret", "clear_password": ""},
        )
        n = Note.objects.get(slug="p1")
        self.assertTrue(n.has_password)
        self.assertTrue(n.check_password("secret"))

    def test_blank_password_on_edit_does_not_change_it(self):
        self.login()
        n = Note.objects.create(slug="p2", markdown="x")
        n.set_password("orig")
        n.save()
        self.client.post(
            "/p2/edit/",
            {"slug": "p2", "title": "", "markdown": "y", "password": "", "clear_password": ""},
        )
        n.refresh_from_db()
        self.assertTrue(n.check_password("orig"))

    def test_clear_password_checkbox_removes_password(self):
        self.login()
        n = Note.objects.create(slug="p3", markdown="x")
        n.set_password("orig")
        n.save()
        self.client.post(
            "/p3/edit/",
            {"slug": "p3", "title": "", "markdown": "y", "password": "", "clear_password": "on"},
        )
        n.refresh_from_db()
        self.assertFalse(n.has_password)

    def test_new_password_on_edit_replaces(self):
        self.login()
        n = Note.objects.create(slug="p4", markdown="x")
        n.set_password("orig")
        n.save()
        self.client.post(
            "/p4/edit/",
            {"slug": "p4", "title": "", "markdown": "y", "password": "different", "clear_password": ""},
        )
        n.refresh_from_db()
        self.assertFalse(n.check_password("orig"))
        self.assertTrue(n.check_password("different"))
