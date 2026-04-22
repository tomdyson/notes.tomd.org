import base64
import json

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .models import Passkey


User = get_user_model()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _user_handle(user) -> bytes:
    return str(user.pk).encode()


@login_required
@require_POST
def register_begin(request):
    existing = list(request.user.passkeys.all())
    options = generate_registration_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        rp_name=settings.WEBAUTHN_RP_NAME,
        user_id=_user_handle(request.user),
        user_name=request.user.get_username(),
        user_display_name=request.user.get_username(),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=bytes(p.credential_id)) for p in existing
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    data = json.loads(options_to_json(options))
    request.session["passkey_register_challenge"] = data["challenge"]
    return JsonResponse(data)


@login_required
@require_POST
def register_finish(request):
    challenge = request.session.get("passkey_register_challenge")
    if not challenge:
        return JsonResponse({"error": "no challenge"}, status=400)
    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "bad json"}, status=400)

    credential = payload.get("credential")
    if not credential:
        return JsonResponse({"error": "missing credential"}, status=400)

    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=base64.urlsafe_b64decode(challenge + "=="),
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
        )
    except InvalidRegistrationResponse as e:
        return JsonResponse({"error": f"invalid registration: {e}"}, status=400)

    Passkey.objects.create(
        user=request.user,
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        name=(payload.get("name") or "").strip()[:80],
    )
    request.session.pop("passkey_register_challenge", None)
    return JsonResponse({"ok": True})


@require_POST
def login_begin(request):
    options = generate_authentication_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        user_verification=UserVerificationRequirement.PREFERRED,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=bytes(p.credential_id))
            for p in Passkey.objects.all()
        ],
    )
    data = json.loads(options_to_json(options))
    request.session["passkey_login_challenge"] = data["challenge"]
    return JsonResponse(data)


@require_POST
def login_finish(request):
    challenge = request.session.get("passkey_login_challenge")
    if not challenge:
        return JsonResponse({"error": "no challenge"}, status=400)
    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "bad json"}, status=400)

    credential = payload.get("credential")
    if not credential:
        return JsonResponse({"error": "missing credential"}, status=400)

    cred_id_b64 = credential.get("id") or credential.get("rawId") or ""
    try:
        raw_id = base64.urlsafe_b64decode(cred_id_b64 + "==")
    except Exception:
        return JsonResponse({"error": "bad credential id"}, status=400)

    try:
        passkey = Passkey.objects.get(credential_id=raw_id)
    except Passkey.DoesNotExist:
        return JsonResponse({"error": "unknown credential"}, status=400)

    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=base64.urlsafe_b64decode(challenge + "=="),
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
            credential_public_key=bytes(passkey.public_key),
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=False,
        )
    except InvalidAuthenticationResponse as e:
        return JsonResponse({"error": f"invalid assertion: {e}"}, status=400)

    passkey.sign_count = verified.new_sign_count
    passkey.last_used_at = timezone.now()
    passkey.save(update_fields=["sign_count", "last_used_at"])

    login(request, passkey.user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.pop("passkey_login_challenge", None)
    return JsonResponse({"ok": True, "redirect": "/"})


@login_required
def manage(request):
    return render(
        request,
        "notes/passkeys.html",
        {"passkeys": request.user.passkeys.all()},
    )


@login_required
@require_POST
def delete(request, pk):
    request.user.passkeys.filter(pk=pk).delete()
    return redirect("/passkeys/")
