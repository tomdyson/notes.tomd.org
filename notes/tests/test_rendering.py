from django.test import SimpleTestCase

from notes.rendering import render_markdown, toggle_task_in_markdown


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

    def test_renders_mermaid_fence_with_crlf_line_endings(self):
        # Browsers submit <textarea> content with CRLF; the mermaid
        # detector must treat CRLF and LF identically or every diagram
        # authored through the editor silently falls through to pygments.
        src = "```mermaid\r\ngraph TD\r\n    A-->B\r\n```\r\n"
        html = render_markdown(src)
        self.assertIn('<div class="mermaid">', html)
        self.assertNotIn("codehilite", html)

    def test_renders_tables(self):
        src = "| a | b |\n|---|---|\n| 1 | 2 |\n"
        html = render_markdown(src)
        self.assertIn("<table>", html)
        self.assertIn("<td>1</td>", html)

    def test_renders_lists(self):
        html = render_markdown("- one\n- two\n")
        self.assertIn("<ul>", html)
        self.assertIn("<li>one</li>", html)

    def test_paragraph_can_be_followed_immediately_by_list(self):
        html = render_markdown("sentence\n - first list item\n - second item\n")
        self.assertIn("<p>sentence</p>", html)
        self.assertIn("<ul>", html)
        self.assertIn("<li>first list item</li>", html)
        self.assertIn("<li>second item</li>", html)

    def test_list_interruptions_inside_fences_are_unchanged(self):
        src = "```text\nsentence\n - not a rendered list\n```\n"
        html = render_markdown(src)
        self.assertIn("sentence", html)
        self.assertIn("- not a rendered list", html)
        self.assertNotIn("<li>not a rendered list</li>", html)

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


class TaskListRenderingTests(SimpleTestCase):
    def test_unchecked_task_becomes_checkbox(self):
        html = render_markdown("- [ ] todo\n")
        self.assertIn('type="checkbox"', html)
        self.assertNotIn("checked", html)
        self.assertIn("todo", html)
        self.assertNotIn("[ ]", html)

    def test_checked_task_becomes_checked_checkbox(self):
        html = render_markdown("- [x] done\n")
        self.assertIn('type="checkbox"', html)
        self.assertIn("checked", html)
        self.assertIn("done", html)
        self.assertNotIn("[x]", html)

    def test_task_items_carry_zero_based_index(self):
        html = render_markdown("- [ ] one\n- [x] two\n- [ ] three\n")
        self.assertIn('data-task-index="0"', html)
        self.assertIn('data-task-index="1"', html)
        self.assertIn('data-task-index="2"', html)

    def test_task_li_marked_with_class(self):
        html = render_markdown("- [ ] todo\n")
        self.assertRegex(html, r'<li class="[^"]*\btask-item\b')

    def test_non_task_li_unchanged(self):
        html = render_markdown("- alpha\n- [ ] beta\n- gamma\n")
        # Only one task, so only one input.
        self.assertEqual(html.count('type="checkbox"'), 1)
        self.assertEqual(html.count('data-task-index='), 1)
        self.assertIn("<li>alpha</li>", html)
        self.assertIn("<li>gamma</li>", html)

    def test_task_input_disabled_by_default(self):
        # Toggling is enabled via JS for authenticated viewers; the
        # underlying input is disabled so it's inert without JS.
        html = render_markdown("- [ ] todo\n")
        self.assertIn("disabled", html)

    def test_inline_formatting_preserved_in_task_text(self):
        html = render_markdown("- [ ] **bold** task\n")
        self.assertIn("<strong>bold</strong>", html)

    def test_uppercase_x_treated_as_checked(self):
        html = render_markdown("- [X] done\n")
        self.assertIn("checked", html)

    def test_nested_task_list_indices_in_source_order(self):
        src = "- [ ] outer\n    - [x] inner\n- [ ] last\n"
        html = render_markdown(src)
        self.assertIn('data-task-index="0"', html)
        self.assertIn('data-task-index="1"', html)
        self.assertIn('data-task-index="2"', html)
        # outer comes before inner before last in document order
        i0 = html.index('data-task-index="0"')
        i1 = html.index('data-task-index="1"')
        i2 = html.index('data-task-index="2"')
        self.assertLess(i0, i1)
        self.assertLess(i1, i2)

    def test_loose_list_task_items_render(self):
        # Blank lines between items make python-markdown wrap each
        # <li> in a <p>; the checkbox should still appear.
        src = "- [ ] one\n\n- [x] two\n"
        html = render_markdown(src)
        self.assertEqual(html.count('type="checkbox"'), 2)
        self.assertEqual(html.count("checked"), 1)


class ToggleTaskInMarkdownTests(SimpleTestCase):
    def test_toggle_unchecked_to_checked(self):
        self.assertEqual(toggle_task_in_markdown("- [ ] foo", 0), "- [x] foo")

    def test_toggle_checked_to_unchecked(self):
        self.assertEqual(toggle_task_in_markdown("- [x] foo", 0), "- [ ] foo")

    def test_toggle_nth_task_only(self):
        src = "- [ ] one\n- [ ] two\n- [ ] three\n"
        self.assertEqual(
            toggle_task_in_markdown(src, 1),
            "- [ ] one\n- [x] two\n- [ ] three\n",
        )

    def test_skip_non_task_lines_when_indexing(self):
        src = "- alpha\n- [ ] beta\n- gamma\n- [x] delta\n"
        self.assertEqual(
            toggle_task_in_markdown(src, 1),
            "- alpha\n- [ ] beta\n- gamma\n- [ ] delta\n",
        )

    def test_indented_task_items_count(self):
        src = "- [ ] outer\n    - [x] inner\n"
        self.assertEqual(
            toggle_task_in_markdown(src, 1),
            "- [ ] outer\n    - [ ] inner\n",
        )

    def test_uppercase_x_counted_and_lowered(self):
        self.assertEqual(toggle_task_in_markdown("- [X] foo", 0), "- [ ] foo")

    def test_returns_none_for_out_of_range(self):
        self.assertIsNone(toggle_task_in_markdown("- [ ] one", 5))
        self.assertIsNone(toggle_task_in_markdown("no tasks here", 0))
        self.assertIsNone(toggle_task_in_markdown("- [ ] one", -1))

    def test_supports_asterisk_and_plus_bullets(self):
        self.assertEqual(toggle_task_in_markdown("* [ ] foo", 0), "* [x] foo")
        self.assertEqual(toggle_task_in_markdown("+ [x] foo", 0), "+ [ ] foo")

    def test_does_not_match_inline_brackets(self):
        # "[ ]" inside a paragraph (no list marker) is not a task.
        src = "Look at [ ] this!\n"
        self.assertIsNone(toggle_task_in_markdown(src, 0))
