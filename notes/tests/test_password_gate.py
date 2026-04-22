from django.test import TestCase

from notes.models import Note
from notes import gate


class PasswordGateTests(TestCase):
    def setUp(self):
        gate.reset_rate_limiter()
        self.note = Note(slug="secret", markdown="# hidden")
        self.note.set_password("opensesame")
        self.note.save()

    def test_view_protected_note_redirects_to_unlock(self):
        r = self.client.get("/secret/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/secret/unlock/?next=/secret/")

    def test_raw_protected_note_redirects_to_unlock(self):
        r = self.client.get("/secret/raw")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/secret/unlock/", r["Location"])

    def test_unlock_page_get_renders_form(self):
        r = self.client.get("/secret/unlock/?next=/secret/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "password")

    def test_wrong_password_stays_on_form(self):
        r = self.client.post("/secret/unlock/?next=/secret/", {"password": "nope"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Incorrect")

    def test_correct_password_unlocks_and_redirects(self):
        r = self.client.post(
            "/secret/unlock/?next=/secret/", {"password": "opensesame"}
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/secret/")
        r2 = self.client.get("/secret/")
        self.assertEqual(r2.status_code, 200)
        self.assertContains(r2, "hidden")

    def test_correct_password_unlocks_raw_too(self):
        self.client.post("/secret/unlock/?next=/secret/raw", {"password": "opensesame"})
        r = self.client.get("/secret/raw")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content.decode(), "# hidden")

    def test_unlock_does_not_leak_to_other_notes(self):
        other = Note(slug="other", markdown="x")
        other.set_password("other-pw")
        other.save()
        self.client.post("/secret/unlock/?next=/secret/", {"password": "opensesame"})
        r = self.client.get("/other/")
        self.assertEqual(r.status_code, 302)

    def test_remove_password_clears_gate(self):
        self.note.clear_password()
        self.note.save()
        r = self.client.get("/secret/")
        self.assertEqual(r.status_code, 200)

    def test_rate_limit_after_three_wrong_attempts(self):
        for _ in range(3):
            self.client.post("/secret/unlock/?next=/secret/", {"password": "nope"})
        r = self.client.post("/secret/unlock/?next=/secret/", {"password": "nope"})
        self.assertEqual(r.status_code, 429)

    def test_unprotected_note_passes_through(self):
        Note.objects.create(slug="open", markdown="hi")
        r = self.client.get("/open/")
        self.assertEqual(r.status_code, 200)
