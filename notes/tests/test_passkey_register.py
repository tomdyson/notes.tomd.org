import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from notes.models import Passkey

User = get_user_model()


class RegisterBeginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="tom", password="pw")

    def test_requires_login(self):
        r = self.client.post("/passkeys/register/begin/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])

    def test_returns_options_with_rp_id_notes_tomd_org(self):
        self.client.login(username="tom", password="pw")
        r = self.client.post("/passkeys/register/begin/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"].split(";")[0], "application/json")
        data = json.loads(r.content)
        self.assertEqual(data["rp"]["id"], "notes.tomd.org")
        self.assertTrue(data["challenge"])
        self.assertTrue(data["user"]["id"])
        self.assertEqual(data["user"]["name"], "tom")

    def test_stores_challenge_in_session(self):
        self.client.login(username="tom", password="pw")
        r = self.client.post("/passkeys/register/begin/")
        data = json.loads(r.content)
        self.assertEqual(
            self.client.session["passkey_register_challenge"],
            data["challenge"],
        )

    def test_excludes_already_registered_credentials(self):
        self.client.login(username="tom", password="pw")
        Passkey.objects.create(
            user=self.user, credential_id=b"already-here", public_key=b"k", sign_count=0
        )
        r = self.client.post("/passkeys/register/begin/")
        data = json.loads(r.content)
        self.assertEqual(len(data["excludeCredentials"]), 1)


class RegisterFinishTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="tom", password="pw")

    def _prime(self):
        self.client.login(username="tom", password="pw")
        self.client.post("/passkeys/register/begin/")

    def test_requires_login(self):
        r = self.client.post(
            "/passkeys/register/finish/",
            data=json.dumps({"credential": {}, "name": ""}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 302)

    def test_requires_challenge_in_session(self):
        self.client.login(username="tom", password="pw")
        r = self.client.post(
            "/passkeys/register/finish/",
            data=json.dumps({"credential": {"id": "x"}, "name": ""}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_stores_passkey_on_verified_response(self):
        self._prime()

        class _Verified:
            credential_id = b"my-credential-id"
            credential_public_key = b"my-public-key"
            sign_count = 5

        with patch("notes.passkey_views.verify_registration_response", return_value=_Verified):
            r = self.client.post(
                "/passkeys/register/finish/",
                data=json.dumps({"credential": {"id": "x"}, "name": "Yubikey"}),
                content_type="application/json",
            )
        self.assertEqual(r.status_code, 200, r.content)
        p = Passkey.objects.get()
        self.assertEqual(bytes(p.credential_id), b"my-credential-id")
        self.assertEqual(bytes(p.public_key), b"my-public-key")
        self.assertEqual(p.sign_count, 5)
        self.assertEqual(p.name, "Yubikey")
        self.assertEqual(p.user, self.user)

    def test_rejects_unverified_response(self):
        self._prime()
        from webauthn.helpers.exceptions import InvalidRegistrationResponse

        with patch(
            "notes.passkey_views.verify_registration_response",
            side_effect=InvalidRegistrationResponse("nope"),
        ):
            r = self.client.post(
                "/passkeys/register/finish/",
                data=json.dumps({"credential": {"id": "x"}, "name": ""}),
                content_type="application/json",
            )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Passkey.objects.count(), 0)

    def test_clears_challenge_after_use(self):
        self._prime()

        class _Verified:
            credential_id = b"c"
            credential_public_key = b"k"
            sign_count = 0

        with patch("notes.passkey_views.verify_registration_response", return_value=_Verified):
            self.client.post(
                "/passkeys/register/finish/",
                data=json.dumps({"credential": {"id": "x"}, "name": ""}),
                content_type="application/json",
            )
        self.assertNotIn("passkey_register_challenge", self.client.session)
