from django.contrib.auth import get_user_model
from django.test import TestCase

from notes.models import Note

User = get_user_model()


class EditorMarkupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="tom", password="pw")

    def setUp(self):
        self.client.login(username="tom", password="pw")

    def test_editor_has_textarea_and_preview_pane(self):
        r = self.client.get("/new/")
        self.assertContains(r, 'id="id_markdown"')
        self.assertContains(r, 'id="preview"')

    def test_editor_loads_marked_dompurify_mermaid_highlight_and_editor_js(self):
        r = self.client.get("/new/")
        self.assertContains(r, "marked")
        self.assertContains(r, "dompurify")
        self.assertContains(r, "mermaid")
        self.assertContains(r, "highlight.min.js")
        self.assertContains(r, "editor.js")

    def test_comments_toggle_lives_in_footer_and_submits_with_editor_form(self):
        r = self.client.get("/new/")
        html = r.content.decode()
        # Attribute order is irrelevant; what matters is that the checkbox is
        # bound to the editor form, since it renders outside <form>.
        self.assertRegex(
            html,
            r'<input(?=[^>]*\bform="editor-form")(?=[^>]*\bname="comments_enabled")'
            r'(?=[^>]*\btype="checkbox")[^>]*>',
        )

    def test_existing_note_has_copy_link_feedback_control(self):
        note = Note.objects.create(title="Copy me", markdown="Body")

        r = self.client.get(f"/{note.slug}/edit/")

        self.assertContains(r, "data-copy-link")
        self.assertContains(r, f'data-copy-url="/{note.slug}/"')
        self.assertContains(r, "data-copy-icon")
        self.assertContains(r, "data-copy-label")
