import io
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image as PImage


def _jpeg(size=(10, 10), exif_bytes=None):
    buf = io.BytesIO()
    im = PImage.new("RGB", size, "red")
    kwargs = {"format": "JPEG"}
    if exif_bytes is not None:
        kwargs["exif"] = exif_bytes
    im.save(buf, **kwargs)
    return buf.getvalue()


def _png(size=(10, 10)):
    buf = io.BytesIO()
    PImage.new("RGBA", size, (0, 0, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="pipeline-tests-"))
class PipelineTests(TestCase):
    def _run(self, data, name="x.jpg", content_type="image/jpeg"):
        from notes.images import process_upload
        upload = SimpleUploadedFile(name, data, content_type=content_type)
        return process_upload(upload)

    def test_jpeg_is_reencoded_to_webp(self):
        img = self._run(_jpeg())
        with img.file.open("rb") as fh:
            head = fh.read(12)
        self.assertEqual(head[:4], b"RIFF")
        self.assertEqual(head[8:12], b"WEBP")

    def test_png_with_transparency_is_reencoded_to_webp(self):
        img = self._run(_png(), name="x.png", content_type="image/png")
        with img.file.open("rb") as fh:
            head = fh.read(12)
        self.assertEqual(head[:4], b"RIFF")
        self.assertEqual(head[8:12], b"WEBP")

    def test_large_image_is_resized(self):
        img = self._run(_jpeg(size=(4000, 3000)))
        self.assertLessEqual(img.width, 2000)
        self.assertLessEqual(img.height, 2000)
        self.assertEqual(img.width, 2000)  # longest edge hits the cap

    def test_small_image_is_not_upscaled(self):
        img = self._run(_jpeg(size=(100, 80)))
        self.assertEqual(img.width, 100)
        self.assertEqual(img.height, 80)

    def test_exif_is_stripped(self):
        # Minimal EXIF with a GPS tag we can look for afterwards.
        exif = PImage.Exif()
        # ImageDescription
        exif[0x010E] = "SENSITIVE-MARKER-STRING"
        data = _jpeg(size=(50, 50), exif_bytes=exif.tobytes())
        img = self._run(data)
        with img.file.open("rb") as fh:
            out = fh.read()
        self.assertNotIn(b"SENSITIVE-MARKER-STRING", out)

    def test_webp_upload_is_passed_through(self):
        buf = io.BytesIO()
        PImage.new("RGB", (20, 20), "green").save(buf, format="WEBP")
        img = self._run(buf.getvalue(), name="x.webp", content_type="image/webp")
        self.assertEqual(img.width, 20)

    def test_stored_filename_ends_in_webp(self):
        img = self._run(_jpeg())
        self.assertTrue(img.file.name.endswith(".webp"), img.file.name)

    def test_width_height_are_populated(self):
        img = self._run(_jpeg(size=(120, 80)))
        self.assertEqual(img.width, 120)
        self.assertEqual(img.height, 80)
