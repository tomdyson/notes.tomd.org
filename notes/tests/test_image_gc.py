import io
import os
import tempfile
from datetime import timedelta
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from notes.models import Image, Note


def _webp():
    from PIL import Image as PImage
    buf = io.BytesIO()
    PImage.new("RGB", (4, 4), "red").save(buf, format="WEBP")
    return buf.getvalue()


def _mk_image(note=None, created_at=None):
    img = Image.objects.create(
        note=note,
        file=SimpleUploadedFile("x.webp", _webp(), content_type="image/webp"),
        original_name="x.webp",
        width=4,
        height=4,
    )
    if created_at is not None:
        Image.objects.filter(pk=img.pk).update(created_at=created_at)
        img.refresh_from_db()
    return img


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="gc-attach-"))
class NoteSaveAttachesImagesTests(TestCase):
    def test_saving_note_attaches_referenced_images(self):
        img = _mk_image()
        self.assertIsNone(img.note)
        note = Note.objects.create(
            markdown=f"hello ![](/i/{img.short_id}.webp)"
        )
        img.refresh_from_db()
        self.assertEqual(img.note_id, note.pk)

    def test_saving_note_with_no_image_refs_leaves_images_alone(self):
        img = _mk_image()
        Note.objects.create(markdown="no images here")
        img.refresh_from_db()
        self.assertIsNone(img.note)

    def test_editing_note_to_add_new_image_attaches_it(self):
        note = Note.objects.create(markdown="plain text")
        img = _mk_image()
        note.markdown = f"now with image ![](/i/{img.short_id}.webp)"
        note.save()
        img.refresh_from_db()
        self.assertEqual(img.note_id, note.pk)

    def test_unknown_image_ref_is_silently_ignored(self):
        # user writes markdown for an image that doesn't exist
        Note.objects.create(markdown="![](/i/nosuch.webp)")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="gc-sweep-"))
class OrphanSweepCommandTests(TestCase):
    def test_sweeps_orphans_older_than_threshold(self):
        old = _mk_image(created_at=timezone.now() - timedelta(days=2))
        path = old.file.path
        self.assertTrue(os.path.exists(path))

        out = StringIO()
        call_command("sweep_orphan_images", stdout=out)

        self.assertFalse(Image.objects.filter(pk=old.pk).exists())
        self.assertFalse(os.path.exists(path))
        self.assertIn("1", out.getvalue())  # count reported

    def test_does_not_sweep_recent_orphans(self):
        fresh = _mk_image()  # created_at = now
        call_command("sweep_orphan_images", stdout=StringIO())
        self.assertTrue(Image.objects.filter(pk=fresh.pk).exists())

    def test_does_not_sweep_attached_images(self):
        note = Note.objects.create(markdown="hi")
        attached = _mk_image(note=note, created_at=timezone.now() - timedelta(days=10))
        call_command("sweep_orphan_images", stdout=StringIO())
        self.assertTrue(Image.objects.filter(pk=attached.pk).exists())

    def test_hours_argument_controls_threshold(self):
        two_hours_ago = _mk_image(created_at=timezone.now() - timedelta(hours=2))
        call_command("sweep_orphan_images", "--hours", "1", stdout=StringIO())
        self.assertFalse(Image.objects.filter(pk=two_hours_ago.pk).exists())
