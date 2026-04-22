import base64
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from notes.models import Passkey

User = get_user_model()


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class LoginBeginTests(TestCase):
    def test_returns_options_and_stores_challenge(self):
        r = self.client.post("/passkeys/login/begin/")
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertEqual(data["rpId"], "notes.tomd.org")
        self.assertTrue(data["challenge"])
        self.assertEqual(
            self.client.session["passkey_login_challenge"], data["challenge"]
        )

    def test_includes_all_registered_credentials(self):
        u1 = User.objects.create_user(username="a", password="x")
        u2 = User.objects.create_user(username="b", password="y")
        Passkey.objects.create(user=u1, credential_id=b"cred-a", public_key=b"k", sign_count=0)
        Passkey.objects.create(user=u2, credential_id=b"cred-b", public_key=b"k", sign_count=0)
        r = self.client.post("/passkeys/login/begin/")
        data = json.loads(r.content)
        self.assertEqual(len(data["allowCredentials"]), 2)


class LoginFinishTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="tom", password="pw")
        cls.passkey = Passkey.objects.create(
            user=cls.user,
            credential_id=b"my-cred-id",
            public_key=b"my-pub-key",
            sign_count=0,
        )

    def _prime(self):
        self.client.post("/passkeys/login/begin/")

    def test_requires_challenge_in_session(self):
        r = self.client.post(
            "/passkeys/login/finish/",
            data=json.dumps({"credential": {"id": b64url(b"my-cred-id")}}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_rejects_unknown_credential_id(self):
        self._prime()
        r = self.client.post(
            "/passkeys/login/finish/",
            data=json.dumps({"credential": {"id": b64url(b"not-registered")}}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_verified_assertion_logs_user_in(self):
        self._prime()

        class _Verified:
            new_sign_count = 42

        with patch(
            "notes.passkey_views.verify_authentication_response", return_value=_Verified
        ):
            r = self.client.post(
                "/passkeys/login/finish/",
                data=json.dumps({"credential": {"id": b64url(b"my-cred-id")}}),
                content_type="application/json",
            )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
        self.passkey.refresh_from_db()
        self.assertEqual(self.passkey.sign_count, 42)
        self.assertIsNotNone(self.passkey.last_used_at)

    def test_invalid_assertion_does_not_log_in(self):
        self._prime()
        from webauthn.helpers.exceptions import InvalidAuthenticationResponse

        with patch(
            "notes.passkey_views.verify_authentication_response",
            side_effect=InvalidAuthenticationResponse("bad"),
        ):
            r = self.client.post(
                "/passkeys/login/finish/",
                data=json.dumps({"credential": {"id": b64url(b"my-cred-id")}}),
                content_type="application/json",
            )
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_clears_challenge_after_success(self):
        self._prime()

        class _Verified:
            new_sign_count = 1

        with patch(
            "notes.passkey_views.verify_authentication_response", return_value=_Verified
        ):
            self.client.post(
                "/passkeys/login/finish/",
                data=json.dumps({"credential": {"id": b64url(b"my-cred-id")}}),
                content_type="application/json",
            )
        self.assertNotIn("passkey_login_challenge", self.client.session)


class PasskeyManagePageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="tom", password="pw")

    def test_requires_login(self):
        r = self.client.get("/passkeys/")
        self.assertEqual(r.status_code, 302)

    def test_lists_user_passkeys(self):
        Passkey.objects.create(
            user=self.user, credential_id=b"c", public_key=b"k", sign_count=0, name="yubi"
        )
        self.client.login(username="tom", password="pw")
        r = self.client.get("/passkeys/")
        self.assertContains(r, "yubi")

    def test_delete_requires_post(self):
        p = Passkey.objects.create(
            user=self.user, credential_id=b"c", public_key=b"k", sign_count=0
        )
        self.client.login(username="tom", password="pw")
        r = self.client.get(f"/passkeys/{p.pk}/delete/")
        self.assertIn(r.status_code, (302, 405))
        self.assertTrue(Passkey.objects.filter(pk=p.pk).exists())

    def test_delete_post_removes_only_own(self):
        p = Passkey.objects.create(
            user=self.user, credential_id=b"c", public_key=b"k", sign_count=0
        )
        other = User.objects.create_user(username="other", password="x")
        q = Passkey.objects.create(
            user=other, credential_id=b"c2", public_key=b"k", sign_count=0
        )
        self.client.login(username="tom", password="pw")
        self.client.post(f"/passkeys/{p.pk}/delete/")
        self.assertFalse(Passkey.objects.filter(pk=p.pk).exists())
        # Should not be allowed to delete someone else's
        self.client.post(f"/passkeys/{q.pk}/delete/")
        self.assertTrue(Passkey.objects.filter(pk=q.pk).exists())
