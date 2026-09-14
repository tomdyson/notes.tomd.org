from django.test import TestCase

from notes.models import Comment, Note


class NoteCommentsEnabledTests(TestCase):
    def test_comments_disabled_by_default(self):
        n = Note.objects.create(markdown="hi")
        self.assertFalse(n.comments_enabled)

    def test_comments_enabled_persists(self):
        n = Note.objects.create(markdown="hi", comments_enabled=True)
        n.refresh_from_db()
        self.assertTrue(n.comments_enabled)


class CommentModelTests(TestCase):
    def setUp(self):
        self.note = Note.objects.create(markdown="Some text to discuss.")

    def test_create_note_level_comment(self):
        c = Comment.objects.create(note=self.note, author_name="Ann", body="Nice.")
        self.assertEqual(list(self.note.comments.all()), [c])
        self.assertIsNone(c.parent)
        self.assertFalse(c.is_anchored)
        self.assertEqual(c.author_key, "")

    def test_anchored_comment_stores_selector(self):
        c = Comment.objects.create(
            note=self.note,
            author_name="Ann",
            body="Typo here.",
            quote="text to",
            prefix="Some ",
            suffix=" discuss.",
            start_offset=5,
        )
        c.refresh_from_db()
        self.assertTrue(c.is_anchored)
        self.assertEqual(c.quote, "text to")
        self.assertEqual(c.prefix, "Some ")
        self.assertEqual(c.suffix, " discuss.")
        self.assertEqual(c.start_offset, 5)

    def test_reply_links_to_parent(self):
        top = Comment.objects.create(note=self.note, author_name="Ann", body="Q?")
        reply = Comment.objects.create(
            note=self.note, parent=top, author_name="Tom", body="A."
        )
        self.assertEqual(list(top.replies.all()), [reply])
        self.assertEqual(reply.parent, top)

    def test_comments_order_oldest_first(self):
        first = Comment.objects.create(note=self.note, author_name="A", body="1")
        second = Comment.objects.create(note=self.note, author_name="B", body="2")
        third = Comment.objects.create(note=self.note, author_name="C", body="3")
        self.assertEqual(list(Comment.objects.all()), [first, second, third])

    def test_deleting_note_deletes_comments(self):
        Comment.objects.create(note=self.note, author_name="Ann", body="x")
        self.note.delete()
        self.assertEqual(Comment.objects.count(), 0)

    def test_deleting_parent_deletes_replies(self):
        top = Comment.objects.create(note=self.note, author_name="Ann", body="Q?")
        Comment.objects.create(note=self.note, parent=top, author_name="Tom", body="A.")
        top.delete()
        self.assertEqual(Comment.objects.count(), 0)

    def test_author_key_is_stored_for_own_comment_checks(self):
        c = Comment.objects.create(
            note=self.note, author_name="Ann", body="x", author_key="abc123"
        )
        c.refresh_from_db()
        self.assertEqual(c.author_key, "abc123")

    def test_is_owner_defaults_false(self):
        c = Comment.objects.create(note=self.note, author_name="Ann", body="x")
        c.refresh_from_db()
        self.assertFalse(c.is_owner)
