from django.test import SimpleTestCase

from notes.rendering import render_markdown


class RenderMarkdownTests(SimpleTestCase):
    def test_renders_headings_and_paragraphs(self):
        html = render_markdown("# Title\n\nHello *world*.")
        self.assertRegex(html, r"<h1[^>]*>Title</h1>")
        self.assertIn("<p>Hello <em>world</em>.</p>", html)

    def test_renders_fenced_code_with_pygments_classes(self):
        src = "```python\ndef f():\n    return 1\n```"
        html = render_markdown(src)
        self.assertIn("codehilite", html)
        # pygments wraps tokens in <span class="...">
        self.assertRegex(html, r'<span class=\"[^\"]+\"')

    def test_renders_mermaid_fences_as_mermaid_blocks(self):
        src = '```mermaid\ngraph TD\n    A["Hello"] --> B\n```\n\nAfter'
        html = render_markdown(src)
        self.assertIn('<div class="mermaid">', html)
        self.assertIn("</div>", html)
        self.assertIn('A[&quot;Hello&quot;] --&gt; B', html)
        self.assertIn("<p>After</p>", html)
        self.assertNotIn("codehilite", html)

    def test_renders_mermaid_fence_at_end_of_document(self):
        html = render_markdown("```mermaid\ngraph TD\n    A-->B\n```")
        self.assertIn('<div class="mermaid">graph TD', html)

    def test_renders_tables(self):
        src = "| a | b |\n|---|---|\n| 1 | 2 |\n"
        html = render_markdown(src)
        self.assertIn("<table>", html)
        self.assertIn("<td>1</td>", html)

    def test_renders_lists(self):
        html = render_markdown("- one\n- two\n")
        self.assertIn("<ul>", html)
        self.assertIn("<li>one</li>", html)

    def test_strips_script_tags(self):
        html = render_markdown("hi <script>alert(1)</script> bye")
        self.assertNotIn("<script", html)
        self.assertNotIn("alert(1)", html)

    def test_strips_javascript_hrefs(self):
        html = render_markdown("[x](javascript:alert(1))")
        self.assertNotIn("javascript:", html)

    def test_external_links_get_rel_nofollow_noopener(self):
        html = render_markdown("[hi](https://example.com/)")
        self.assertIn('href="https://example.com/"', html)
        self.assertIn("nofollow", html)
        self.assertIn("noopener", html)

    def test_preserves_inline_code(self):
        html = render_markdown("use `print()` please")
        self.assertIn("<code>print()</code>", html)

    def test_allows_images(self):
        html = render_markdown("![alt](https://example.com/x.png)")
        self.assertIn("<img", html)
        self.assertIn('src="https://example.com/x.png"', html)

    def test_strips_onerror_on_images(self):
        html = render_markdown('<img src=x onerror="alert(1)">')
        self.assertNotIn("onerror", html)

    def test_images_are_wrapped_in_expand_links(self):
        html = render_markdown("![alt](https://example.com/x.png)")
        self.assertRegex(
            html,
            r'<a [^>]*href="https://example.com/x\.png"[^>]*target="_blank"[^>]*>\s*<img',
        )

    def test_image_expand_link_has_noopener(self):
        html = render_markdown("![](/i/abc123.webp)")
        self.assertIn('target="_blank"', html)
        self.assertIn("noopener", html)

    def test_image_already_inside_link_is_not_rewrapped(self):
        html = render_markdown("[![](/i/a.webp)](https://example.com/)")
        # Only the outer link should be present; no nested <a><a>.
        self.assertEqual(html.count("<a "), 1)
