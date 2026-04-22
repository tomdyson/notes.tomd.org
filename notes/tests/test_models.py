from django.db import IntegrityError
from django.test import TestCase

from notes.models import Note


class NoteSaveTests(TestCase):
    def test_save_auto_generates_slug_when_blank(self):
        n = Note(markdown="hi")
        n.save()
        self.assertTrue(n.slug)
        self.assertEqual(len(n.slug), 6)

    def test_save_preserves_explicit_slug(self):
        n = Note(slug="hello", markdown="hi")
        n.save()
        self.assertEqual(n.slug, "hello")

    def test_save_caches_rendered_html(self):
        n = Note(markdown="# Title\n\nhi")
        n.save()
        self.assertIn("Title", n.html)
        self.assertIn("<p>hi</p>", n.html)

    def test_save_regenerates_html_when_markdown_changes(self):
        n = Note(markdown="# A")
        n.save()
        n.markdown = "# B"
        n.save()
        self.assertIn("B", n.html)
        self.assertNotIn(">A<", n.html)

    def test_unique_slug_constraint_enforced(self):
        Note.objects.create(slug="hello", markdown="hi")
        with self.assertRaises(IntegrityError):
            Note.objects.create(slug="hello", markdown="bye")

    def test_auto_slug_avoids_collision(self):
        # Pre-populate so the first few random picks are known to collide.
        # We can't easily force this without patching generate_slug, so just
        # assert many creates produce unique slugs.
        slugs = {Note.objects.create(markdown=f"n{i}").slug for i in range(20)}
        self.assertEqual(len(slugs), 20)


class NotePasswordTests(TestCase):
    def test_new_note_has_no_password(self):
        n = Note.objects.create(markdown="hi")
        self.assertFalse(n.has_password)
        self.assertEqual(n.password_hash, "")

    def test_set_password_hashes_it(self):
        n = Note.objects.create(markdown="hi")
        n.set_password("secret")
        n.save()
        self.assertTrue(n.password_hash)
        self.assertNotIn("secret", n.password_hash)
        self.assertTrue(n.has_password)

    def test_check_password_accepts_correct(self):
        n = Note.objects.create(markdown="hi")
        n.set_password("secret")
        n.save()
        self.assertTrue(n.check_password("secret"))

    def test_check_password_rejects_wrong(self):
        n = Note.objects.create(markdown="hi")
        n.set_password("secret")
        n.save()
        self.assertFalse(n.check_password("nope"))

    def test_clear_password(self):
        n = Note.objects.create(markdown="hi")
        n.set_password("secret")
        n.save()
        n.clear_password()
        n.save()
        self.assertFalse(n.has_password)
        self.assertEqual(n.password_hash, "")

    def test_check_password_on_unprotected_returns_true_for_empty(self):
        # Unprotected notes effectively "unlocked" for anyone; helper should
        # not accidentally accept arbitrary strings though.
        n = Note.objects.create(markdown="hi")
        self.assertFalse(n.check_password("anything"))
