from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import SimpleTestCase, TestCase

User = get_user_model()


class PasskeySettingsTests(SimpleTestCase):
    def test_rp_id_defaults_to_notes_tomd_org(self):
        self.assertEqual(settings.WEBAUTHN_RP_ID, "notes.tomd.org")

    def test_rp_name_set(self):
        self.assertTrue(settings.WEBAUTHN_RP_NAME)

    def test_origin_matches_rp_id(self):
        self.assertEqual(
            settings.WEBAUTHN_ORIGIN,
            f"https://{settings.WEBAUTHN_RP_ID}",
        )


class PasskeyModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="tom", password="pw")

    def test_create_passkey(self):
        from notes.models import Passkey

        p = Passkey.objects.create(
            user=self.user,
            credential_id=b"cred-1",
            public_key=b"pub",
            sign_count=0,
            name="yubikey",
        )
        self.assertEqual(p.user, self.user)
        self.assertEqual(bytes(p.credential_id), b"cred-1")
        self.assertEqual(p.sign_count, 0)

    def test_credential_id_is_unique(self):
        from notes.models import Passkey

        Passkey.objects.create(
            user=self.user, credential_id=b"dup", public_key=b"k", sign_count=0
        )
        with self.assertRaises(IntegrityError):
            Passkey.objects.create(
                user=self.user, credential_id=b"dup", public_key=b"k", sign_count=0
            )

    def test_str(self):
        from notes.models import Passkey

        p = Passkey.objects.create(
            user=self.user,
            credential_id=b"x",
            public_key=b"k",
            sign_count=0,
            name="macbook",
        )
        self.assertIn("macbook", str(p))
