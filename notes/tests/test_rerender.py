from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from notes.models import Note
from notes.rendering import render_markdown


class RerenderNotesCommandTests(TestCase):
    def _stale(self, note, html="<p>stale</p>"):
        """Overwrite html directly, bypassing save()/auto_now."""
        Note.objects.filter(pk=note.pk).update(html=html)

    def test_rerenders_stale_html(self):
        note = Note.objects.create(markdown="- a\n  - b\n")
        self._stale(note)
        call_command("rerender_notes", stdout=StringIO())
        note.refresh_from_db()
        self.assertEqual(note.html, render_markdown(note.markdown))
        # The whole point: the nested item now nests.
        self.assertIn("<ul>", note.html.split("<li>a", 1)[1].split("</li>", 1)[0])

    def test_preserves_updated_at(self):
        note = Note.objects.create(markdown="- a\n  - b\n")
        self._stale(note)
        note.refresh_from_db()
        before = note.updated_at
        call_command("rerender_notes", stdout=StringIO())
        note.refresh_from_db()
        self.assertEqual(note.updated_at, before)

    def test_skips_unchanged_notes(self):
        note = Note.objects.create(markdown="plain text\n")
        out = StringIO()
        call_command("rerender_notes", stdout=out)
        self.assertIn("0 updated", out.getvalue())

    def test_dry_run_does_not_write(self):
        note = Note.objects.create(markdown="- a\n  - b\n")
        self._stale(note)
        out = StringIO()
        call_command("rerender_notes", "--dry-run", stdout=out)
        note.refresh_from_db()
        self.assertEqual(note.html, "<p>stale</p>")
        self.assertIn("Would update 1", out.getvalue())
