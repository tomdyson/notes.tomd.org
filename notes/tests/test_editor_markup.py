from django.contrib.auth import get_user_model
from django.test import TestCase

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
        self.assertContains(r, "highlight.js")
        self.assertContains(r, "editor.js")
