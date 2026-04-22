import io
import json
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image as PImage

from notes.images import ImageError, process_upload

User = get_user_model()


def _jpeg(size=(10, 10)):
    buf = io.BytesIO()
    PImage.new("RGB", size, "red").save(buf, format="JPEG")
    return buf.getvalue()


SVG_BYTES = (
    b'<?xml version="1.0"?>\n'
    b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    b'<circle cx="5" cy="5" r="4" fill="red"/></svg>'
)

SVG_NO_XML_DECL = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    b'<circle cx="5" cy="5" r="4" fill="red"/></svg>'
)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="reject-tests-"))
class ImageRejectionUnitTests(TestCase):
    def test_svg_with_xml_decl_rejected(self):
        upload = SimpleUploadedFile("evil.svg", SVG_BYTES, content_type="image/svg+xml")
        with self.assertRaises(ImageError):
            process_upload(upload)

    def test_svg_without_xml_decl_rejected(self):
        upload = SimpleUploadedFile("evil.svg", SVG_NO_XML_DECL, content_type="image/svg+xml")
        with self.assertRaises(ImageError):
            process_upload(upload)

    def test_plain_text_rejected(self):
        upload = SimpleUploadedFile("x.txt", b"hello world, not an image", content_type="text/plain")
        with self.assertRaises(ImageError):
            process_upload(upload)

    def test_empty_file_rejected(self):
        upload = SimpleUploadedFile("x.jpg", b"", content_type="image/jpeg")
        with self.assertRaises(ImageError):
            process_upload(upload)

    @override_settings(IMAGE_MAX_UPLOAD_BYTES=1024)
    def test_oversized_file_rejected(self):
        big = _jpeg(size=(500, 500))  # much larger than 1KB
        self.assertGreater(len(big), 1024)
        upload = SimpleUploadedFile("big.jpg", big, content_type="image/jpeg")
        with self.assertRaises(ImageError):
            process_upload(upload)

    def test_truncated_jpeg_rejected(self):
        data = _jpeg()
        upload = SimpleUploadedFile("x.jpg", data[:10], content_type="image/jpeg")
        with self.assertRaises(ImageError):
            process_upload(upload)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="reject-endpoint-tests-"))
class ImageRejectionEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="tom", password="pw")

    def setUp(self):
        self.client.login(username="tom", password="pw")

    def _post(self, name, data, content_type):
        return self.client.post(
            "/upload/",
            {"file": SimpleUploadedFile(name, data, content_type=content_type)},
        )

    def test_svg_returns_400(self):
        r = self._post("evil.svg", SVG_BYTES, "image/svg+xml")
        self.assertEqual(r.status_code, 400)
        body = json.loads(r.content)
        self.assertIn("error", body)
        self.assertIn("SVG", body["error"])

    def test_plain_text_returns_400(self):
        r = self._post("x.txt", b"not an image", "text/plain")
        self.assertEqual(r.status_code, 400)

    @override_settings(IMAGE_MAX_UPLOAD_BYTES=1024)
    def test_oversized_returns_400(self):
        big = _jpeg(size=(500, 500))
        r = self._post("big.jpg", big, "image/jpeg")
        self.assertEqual(r.status_code, 400)
        body = json.loads(r.content)
        self.assertIn("too large", body["error"].lower())
