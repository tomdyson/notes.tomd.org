import io
import os
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from notes.models import Image, Note


def _webp_bytes():
    from PIL import Image as PImage
    buf = io.BytesIO()
    PImage.new("RGB", (4, 4), "red").save(buf, format="WEBP")
    return buf.getvalue()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="img-tests-"))
class ImageModelTests(TestCase):
    def test_create_assigns_short_id(self):
        img = Image.objects.create(
            file=SimpleUploadedFile("x.webp", _webp_bytes(), content_type="image/webp"),
            original_name="x.webp",
            width=4,
            height=4,
        )
        self.assertTrue(img.short_id)
        self.assertEqual(len(img.short_id), 6)

    def test_short_id_is_unique(self):
        img1 = Image.objects.create(
            file=SimpleUploadedFile("a.webp", _webp_bytes(), content_type="image/webp"),
            original_name="a.webp",
            width=4,
            height=4,
        )
        img2 = Image.objects.create(
            file=SimpleUploadedFile("b.webp", _webp_bytes(), content_type="image/webp"),
            original_name="b.webp",
            width=4,
            height=4,
        )
        self.assertNotEqual(img1.short_id, img2.short_id)

    def test_str_uses_short_id(self):
        img = Image.objects.create(
            file=SimpleUploadedFile("x.webp", _webp_bytes(), content_type="image/webp"),
            original_name="x.webp",
            width=4,
            height=4,
        )
        self.assertIn(img.short_id, str(img))

    def test_reverse_url(self):
        img = Image.objects.create(
            file=SimpleUploadedFile("x.webp", _webp_bytes(), content_type="image/webp"),
            original_name="x.webp",
            width=4,
            height=4,
        )
        url = reverse("notes:image_serve", kwargs={"short_id": img.short_id})
        self.assertEqual(url, f"/i/{img.short_id}.webp")

    def test_note_fk_is_nullable(self):
        img = Image.objects.create(
            file=SimpleUploadedFile("x.webp", _webp_bytes(), content_type="image/webp"),
            original_name="x.webp",
            width=4,
            height=4,
        )
        self.assertIsNone(img.note)

    def test_delete_removes_file_from_disk(self):
        img = Image.objects.create(
            file=SimpleUploadedFile("x.webp", _webp_bytes(), content_type="image/webp"),
            original_name="x.webp",
            width=4,
            height=4,
        )
        path = img.file.path
        self.assertTrue(os.path.exists(path))
        img.delete()
        self.assertFalse(os.path.exists(path))

    def test_cascade_when_note_deleted(self):
        note = Note.objects.create(markdown="hi")
        img = Image.objects.create(
            note=note,
            file=SimpleUploadedFile("x.webp", _webp_bytes(), content_type="image/webp"),
            original_name="x.webp",
            width=4,
            height=4,
        )
        path = img.file.path
        note.delete()
        self.assertFalse(Image.objects.filter(pk=img.pk).exists())
        self.assertFalse(os.path.exists(path))
