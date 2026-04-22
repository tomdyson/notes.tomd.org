import re
import string

from django.test import SimpleTestCase

from notes.slugs import RESERVED, generate_slug, is_reserved, is_valid_slug_shape


SLUG_RE = re.compile(r"^[A-Za-z0-9]{6}$")


class GenerateSlugTests(SimpleTestCase):
    def test_generate_slug_is_6_chars_base62(self):
        for _ in range(100):
            s = generate_slug()
            self.assertIsNotNone(SLUG_RE.match(s), f"bad slug: {s!r}")

    def test_generate_slug_is_random(self):
        samples = {generate_slug() for _ in range(1000)}
        self.assertGreater(len(samples), 990, "too many duplicates in 1000 samples")
        chars_seen = set("".join(samples))
        alphabet = set(string.ascii_letters + string.digits)
        self.assertGreater(
            len(chars_seen & alphabet),
            40,
            f"only saw chars {chars_seen} - generator may be limited",
        )


class ReservedSlugTests(SimpleTestCase):
    def test_core_reserved_words(self):
        for word in ("admin", "login", "logout", "new", "static", "api"):
            self.assertTrue(is_reserved(word), f"{word!r} should be reserved")

    def test_reserved_is_case_insensitive(self):
        self.assertTrue(is_reserved("Admin"))
        self.assertTrue(is_reserved("LOGIN"))

    def test_normal_slug_not_reserved(self):
        self.assertFalse(is_reserved("hello"))
        self.assertFalse(is_reserved("aB3kLm"))

    def test_reserved_set_contains_expected_entries(self):
        for entry in (
            "admin", "login", "logout", "new", "static",
            "favicon.ico", "robots.txt", "healthz", "api",
        ):
            self.assertIn(entry, RESERVED)


class ValidShapeTests(SimpleTestCase):
    def test_allows_normal_slug(self):
        self.assertTrue(is_valid_slug_shape("hello"))
        self.assertTrue(is_valid_slug_shape("my-note_1"))
        self.assertTrue(is_valid_slug_shape("aB3kLm"))

    def test_rejects_empty(self):
        self.assertFalse(is_valid_slug_shape(""))

    def test_rejects_leading_non_alnum(self):
        self.assertFalse(is_valid_slug_shape("-hello"))
        self.assertFalse(is_valid_slug_shape("_hello"))

    def test_rejects_disallowed_chars(self):
        self.assertFalse(is_valid_slug_shape("hello world"))
        self.assertFalse(is_valid_slug_shape("hello/world"))
        self.assertFalse(is_valid_slug_shape("hello.world"))
        self.assertFalse(is_valid_slug_shape("hello?"))

    def test_rejects_too_long(self):
        self.assertFalse(is_valid_slug_shape("a" * 65))

    def test_allows_64_chars(self):
        self.assertTrue(is_valid_slug_shape("a" * 64))
