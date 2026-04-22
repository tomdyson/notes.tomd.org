import io
import json
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from notes.models import Image

User = get_user_model()


def _jpeg_bytes(size=(10, 10)):
    from PIL import Image as PImage
    buf = io.BytesIO()
    PImage.new("RGB", size, "blue").save(buf, format="JPEG")
    return buf.getvalue()


def _png_bytes(size=(10, 10)):
    from PIL import Image as PImage
    buf = io.BytesIO()
    PImage.new("RGBA", size, (0, 128, 0, 255)).save(buf, format="PNG")
    return buf.getvalue()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="upload-tests-"))
class UploadAuthTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="tom", password="pw")

    def test_anonymous_gets_login_redirect(self):
        jpeg = SimpleUploadedFile("x.jpg", _jpeg_bytes(), content_type="image/jpeg")
        r = self.client.post("/upload/", {"file": jpeg})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])

    def test_get_method_not_allowed(self):
        self.client.login(username="tom", password="pw")
        r = self.client.get("/upload/")
        self.assertEqual(r.status_code, 405)

    def test_authed_happy_path(self):
        self.client.login(username="tom", password="pw")
        jpeg = SimpleUploadedFile("hello.jpg", _jpeg_bytes(), content_type="image/jpeg")
        r = self.client.post("/upload/", {"file": jpeg})
        self.assertEqual(r.status_code, 200)
        body = json.loads(r.content)
        self.assertTrue(body["url"].startswith("/i/"))
        self.assertTrue(body["url"].endswith(".webp"))
        self.assertIn("![", body["markdown"])
        self.assertIn(body["url"], body["markdown"])
        self.assertEqual(Image.objects.count(), 1)

    def test_missing_file_returns_400(self):
        self.client.login(username="tom", password="pw")
        r = self.client.post("/upload/", {})
        self.assertEqual(r.status_code, 400)
        body = json.loads(r.content)
        self.assertIn("error", body)

    def test_png_accepted(self):
        self.client.login(username="tom", password="pw")
        png = SimpleUploadedFile("p.png", _png_bytes(), content_type="image/png")
        r = self.client.post("/upload/", {"file": png})
        self.assertEqual(r.status_code, 200)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="upload-csrf-tests-"))
class UploadCsrfTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="tom", password="pw")

    def test_missing_csrf_token_returns_403(self):
        c = Client(enforce_csrf_checks=True)
        c.login(username="tom", password="pw")
        jpeg = SimpleUploadedFile("x.jpg", _jpeg_bytes(), content_type="image/jpeg")
        r = c.post("/upload/", {"file": jpeg})
        self.assertEqual(r.status_code, 403)
