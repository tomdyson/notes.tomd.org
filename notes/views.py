import hashlib
import hmac
import json
import secrets

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import RequestDataTooBig
from django.db import IntegrityError, transaction
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponseForbidden,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import gate
from .forms import CommentForm, NoteForm, UnlockForm
from .images import ImageError, process_upload
from .models import Comment, Image, Note, NoteApiIdempotencyRecord, NoteApiToken
from .rendering import toggle_task_in_markdown


COMMENT_RATE_LIMIT = 10  # posts per IP per note per minute


def home(request):
    if request.user.is_authenticated:
        return render(
            request,
            "notes/dashboard.html",
            {"notes": Note.objects.all()},
        )
    return render(request, "notes/home_public.html", {"show_public_header": True})


def _api_error(code, message, *, status, fields=None):
    error = {"code": code, "message": message}
    if fields is not None:
        error["fields"] = fields
    return JsonResponse({"error": error}, status=status)


def _authenticate_note_api(request):
    authorization = request.headers.get("Authorization", "")
    scheme, separator, secret = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return None
    return NoteApiToken.authenticate(secret.strip())


def _note_api_response(request, note):
    return {
        "slug": note.slug,
        "title": note.title,
        "url": request.build_absolute_uri(f"/{note.slug}/"),
        "raw_url": request.build_absolute_uri(f"/{note.slug}/raw"),
        "password_protected": note.has_password,
        "created_at": note.created_at.isoformat(),
        "updated_at": note.updated_at.isoformat(),
    }


@csrf_exempt
@require_POST
def api_create_note(request):
    token = _authenticate_note_api(request)
    if token is None:
        response = _api_error(
            "unauthorized", "A valid bearer token is required.", status=401
        )
        response["WWW-Authenticate"] = "Bearer"
        return response
    token.mark_used()
    if not token.permits("notes:create"):
        return _api_error(
            "insufficient_scope",
            "The token does not have the notes:create scope.",
            status=403,
        )

    if request.content_type != "application/json":
        return _api_error(
            "unsupported_media_type",
            "Content-Type must be application/json.",
            status=415,
        )
    max_request_bytes = settings.NOTE_API_MAX_REQUEST_BYTES
    try:
        content_length = int(request.headers.get("Content-Length", "0"))
    except ValueError:
        content_length = 0
    if content_length > max_request_bytes:
        return _api_error(
            "request_too_large",
            f"The request body must be {max_request_bytes} bytes or fewer.",
            status=413,
        )
    try:
        raw_body = request.body
    except RequestDataTooBig:
        return _api_error(
            "request_too_large", "The request body is too large.", status=413
        )
    if len(raw_body) > max_request_bytes:
        return _api_error(
            "request_too_large",
            f"The request body must be {max_request_bytes} bytes or fewer.",
            status=413,
        )
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _api_error("invalid_json", "The request body is not valid JSON.", status=400)
    if not isinstance(payload, dict):
        return _api_error("invalid_json", "The JSON body must be an object.", status=400)

    allowed_fields = {"title", "markdown", "slug", "password"}
    unknown_fields = sorted(set(payload) - allowed_fields)
    if unknown_fields:
        return _api_error(
            "unknown_fields",
            "The request contains unsupported fields.",
            status=400,
            fields=unknown_fields,
        )

    normalized = {}
    for field in ("title", "slug", "password"):
        value = payload.get(field, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            return _api_error(
                "validation_error",
                "One or more fields are invalid.",
                status=422,
                fields={field: [{"message": "Must be a string.", "code": "invalid"}]},
            )
        normalized[field] = value

    markdown = payload.get("markdown")
    if not isinstance(markdown, str):
        return _api_error(
            "validation_error",
            "One or more fields are invalid.",
            status=422,
            fields={"markdown": [{"message": "Must be a string.", "code": "invalid"}]},
        )
    normalized["markdown"] = markdown
    if len(normalized["password"]) > 128:
        return _api_error(
            "validation_error",
            "One or more fields are invalid.",
            status=422,
            fields={
                "password": [
                    {"message": "Must be 128 characters or fewer.", "code": "max_length"}
                ]
            },
        )

    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    if len(idempotency_key) > 200:
        return _api_error(
            "invalid_idempotency_key",
            "Idempotency-Key must be 200 characters or fewer.",
            status=400,
        )
    canonical_payload = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    # Key the digest so a database leak cannot be used to test guesses for a
    # password included in an idempotent request.
    request_digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"), canonical_payload, hashlib.sha256
    ).hexdigest()

    if idempotency_key:
        existing = NoteApiIdempotencyRecord.objects.filter(
            token=token, key=idempotency_key
        ).first()
        if existing:
            if existing.request_digest != request_digest:
                return _api_error(
                    "idempotency_conflict",
                    "This idempotency key was already used with different input.",
                    status=409,
                )
            response = JsonResponse(existing.response_body, status=200)
            response["Idempotent-Replay"] = "true"
            return response

    form = NoteForm({**normalized, "clear_password": False})
    if not form.is_valid():
        return _api_error(
            "validation_error",
            "One or more fields are invalid.",
            status=422,
            fields=form.errors.get_json_data(escape_html=True),
        )

    try:
        with transaction.atomic():
            note = form.save()
            response_body = _note_api_response(request, note)
            if idempotency_key:
                NoteApiIdempotencyRecord.objects.create(
                    token=token,
                    key=idempotency_key,
                    request_digest=request_digest,
                    response_body=response_body,
                    note=note,
                )
    except IntegrityError:
        # A concurrent retry can win the unique idempotency-key race. The
        # transaction above rolls back its duplicate note before we replay it.
        if not idempotency_key:
            raise
        existing = NoteApiIdempotencyRecord.objects.filter(
            token=token, key=idempotency_key
        ).first()
        if existing and existing.request_digest == request_digest:
            response = JsonResponse(existing.response_body, status=200)
            response["Idempotent-Replay"] = "true"
            return response
        if existing:
            return _api_error(
                "idempotency_conflict",
                "This idempotency key was already used with different input.",
                status=409,
            )
        raise

    return JsonResponse(response_body, status=201)


def _gate(request, note, next_url):
    if note.has_password and not gate.is_unlocked(request, note.slug):
        return redirect(f"/{note.slug}/unlock/?next={next_url}")
    return None


def _commenter_name(request) -> str:
    if request.user.is_authenticated:
        return request.user.get_full_name() or request.user.get_username()
    return request.session.get("commenter_name", "")


def _comments_context(request, note, form=None):
    key = request.session.get("commenter_key", "")
    is_owner = request.user.is_authenticated

    def can_delete(comment):
        return is_owner or (bool(key) and comment.author_key == key)

    threads = list(note.comments.filter(parent__isnull=True).prefetch_related("replies"))
    count = 0
    for thread in threads:
        thread.can_delete = can_delete(thread)
        count += 1
        for reply in thread.replies.all():
            reply.can_delete = can_delete(reply)
            count += 1
    return {
        "comment_threads": threads,
        "comment_count": count,
        "comment_form": form if form is not None else CommentForm(note=note),
        "commenter_name": _commenter_name(request),
    }


def _view_context(request, note, comment_form=None):
    context = {"note": note}
    if note.comments_enabled:
        context.update(_comments_context(request, note, comment_form))
    return context


def view_note(request, slug):
    note = get_object_or_404(Note, slug=slug)
    redirect_resp = _gate(request, note, f"/{slug}/")
    if redirect_resp:
        return redirect_resp
    return render(request, "notes/view.html", _view_context(request, note))


@require_POST
def create_comment(request, slug):
    note = get_object_or_404(Note, slug=slug)
    redirect_resp = _gate(request, note, f"/{slug}/")
    if redirect_resp:
        return redirect_resp
    if not note.comments_enabled:
        raise Http404
    if gate.is_rate_limited(request, slug, scope="comment", limit=COMMENT_RATE_LIMIT):
        return HttpResponse("Too many comments. Try again in a minute.", status=429)
    form = CommentForm(request.POST, note=note, known_name=_commenter_name(request))
    if not form.is_valid():
        return render(
            request, "notes/view.html", _view_context(request, note, form), status=400
        )
    comment = form.save(commit=False)
    comment.note = note
    if request.user.is_authenticated:
        comment.is_owner = True
    else:
        key = request.session.get("commenter_key")
        if not key:
            key = secrets.token_urlsafe(16)
            request.session["commenter_key"] = key
        request.session["commenter_name"] = comment.author_name
        comment.author_key = key
    comment.save()
    gate.record_attempt(request, slug, scope="comment")
    return redirect(f"/{slug}/#comment-{comment.pk}")


@require_POST
def delete_comment(request, slug, pk):
    note = get_object_or_404(Note, slug=slug)
    redirect_resp = _gate(request, note, f"/{slug}/")
    if redirect_resp:
        return redirect_resp
    if not note.comments_enabled:
        raise Http404
    comment = get_object_or_404(Comment, pk=pk, note=note)
    key = request.session.get("commenter_key", "")
    if not (request.user.is_authenticated or (key and comment.author_key == key)):
        return HttpResponseForbidden("You can only delete your own comments.")
    comment.delete()
    return redirect(f"/{slug}/#comments")


def raw_note(request, slug):
    note = get_object_or_404(Note, slug=slug)
    redirect_resp = _gate(request, note, f"/{slug}/raw")
    if redirect_resp:
        return redirect_resp
    return HttpResponse(note.markdown, content_type="text/plain; charset=utf-8")


def unlock_note(request, slug):
    note = get_object_or_404(Note, slug=slug)
    next_url = request.GET.get("next") or f"/{slug}/"
    if not note.has_password:
        return redirect(next_url)
    if request.method == "POST":
        if gate.is_rate_limited(request, slug):
            return HttpResponse("Too many attempts. Try again in a minute.", status=429)
        form = UnlockForm(request.POST)
        if form.is_valid() and note.check_password(form.cleaned_data["password"]):
            gate.mark_unlocked(request, slug)
            return redirect(next_url)
        gate.record_failed_attempt(request, slug)
        if gate.is_rate_limited(request, slug):
            return HttpResponse("Too many attempts. Try again in a minute.", status=429)
        return render(
            request,
            "notes/unlock.html",
            {"form": form, "note": note, "error": True, "next": next_url},
        )
    return render(
        request,
        "notes/unlock.html",
        {"form": UnlockForm(), "note": note, "next": next_url},
    )


@login_required
def new_note(request):
    if request.method == "POST":
        form = NoteForm(request.POST)
        if form.is_valid():
            note = form.save()
            return redirect(f"/{note.slug}/")
    else:
        form = NoteForm()
    return render(
        request,
        "notes/editor.html",
        {"form": form, "note": None, "container_class": "max-w-6xl"},
    )


@login_required
def edit_note(request, slug):
    note = get_object_or_404(Note, slug=slug)
    if request.method == "POST":
        form = NoteForm(request.POST, instance=note)
        if form.is_valid():
            note = form.save()
            return redirect(f"/{note.slug}/")
    else:
        form = NoteForm(instance=note)
    return render(
        request,
        "notes/editor.html",
        {"form": form, "note": note, "container_class": "max-w-6xl"},
    )


@login_required
@require_POST
def delete_note(request, slug):
    note = get_object_or_404(Note, slug=slug)
    note.delete()
    return redirect("/")


@login_required
@require_POST
def toggle_task(request, slug):
    note = get_object_or_404(Note, slug=slug)
    raw = request.POST.get("index")
    try:
        index = int(raw)
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid index"}, status=400)
    new_md = toggle_task_in_markdown(note.markdown, index)
    if new_md is None:
        return JsonResponse({"error": "task not found"}, status=404)
    note.markdown = new_md
    note.save()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def upload_image(request):
    upload = request.FILES.get("file")
    if not upload:
        return JsonResponse({"error": "No file provided."}, status=400)
    try:
        image = process_upload(upload)
    except ImageError as e:
        return JsonResponse({"error": str(e)}, status=400)
    url = f"/i/{image.short_id}.webp"
    alt = image.original_name.rsplit(".", 1)[0] if image.original_name else ""
    return JsonResponse({"url": url, "markdown": f"![{alt}]({url})"})


def serve_image(request, short_id):
    image = get_object_or_404(Image, short_id=short_id)
    try:
        fh = image.file.open("rb")
    except FileNotFoundError:
        raise Http404
    resp = FileResponse(fh, content_type="image/webp")
    resp["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp
