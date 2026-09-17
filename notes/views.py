import hashlib
import hmac
import json
import secrets
from html import unescape

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
from django.utils.html import strip_tags
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
        "comments_enabled": note.comments_enabled,
        "created_at": note.created_at.isoformat(),
        "updated_at": note.updated_at.isoformat(),
    }


def _api_token_or_error(request, scope):
    """Authenticate the bearer token and check it carries ``scope``."""
    token = _authenticate_note_api(request)
    if token is None:
        response = _api_error(
            "unauthorized", "A valid bearer token is required.", status=401
        )
        response["WWW-Authenticate"] = "Bearer"
        return None, response
    token.mark_used()
    if not token.permits(scope):
        return None, _api_error(
            "insufficient_scope",
            f"The token does not have the {scope} scope.",
            status=403,
        )
    return token, None


def _api_method_not_allowed(*allowed):
    response = _api_error(
        "method_not_allowed",
        f"Use {' or '.join(allowed)} on this endpoint.",
        status=405,
    )
    response["Allow"] = ", ".join(allowed)
    return response


def _json_object_or_error(request):
    """Parse a size-limited JSON object request body."""
    if request.content_type != "application/json":
        return None, _api_error(
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
        return None, _api_error(
            "request_too_large",
            f"The request body must be {max_request_bytes} bytes or fewer.",
            status=413,
        )
    try:
        raw_body = request.body
    except RequestDataTooBig:
        return None, _api_error(
            "request_too_large", "The request body is too large.", status=413
        )
    if len(raw_body) > max_request_bytes:
        return None, _api_error(
            "request_too_large",
            f"The request body must be {max_request_bytes} bytes or fewer.",
            status=413,
        )
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, _api_error(
            "invalid_json", "The request body is not valid JSON.", status=400
        )
    if not isinstance(payload, dict):
        return None, _api_error(
            "invalid_json", "The JSON body must be an object.", status=400
        )
    return payload, None


def _unknown_fields_error(payload, allowed_fields):
    unknown_fields = sorted(set(payload) - allowed_fields)
    if not unknown_fields:
        return None
    return _api_error(
        "unknown_fields",
        "The request contains unsupported fields.",
        status=400,
        fields=unknown_fields,
    )


def _invalid_field(message):
    return [{"message": message, "code": "invalid"}]


def _validation_error(fields):
    return _api_error(
        "validation_error", "One or more fields are invalid.", status=422, fields=fields
    )


def _idempotency_key_or_error(request):
    key = request.headers.get("Idempotency-Key", "").strip()
    if len(key) > 200:
        return None, _api_error(
            "invalid_idempotency_key",
            "Idempotency-Key must be 200 characters or fewer.",
            status=400,
        )
    return key, None


def _request_digest(material) -> str:
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    # Key the digest so a database leak cannot be used to test guesses for a
    # password included in an idempotent request.
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"), canonical, hashlib.sha256
    ).hexdigest()


def _idempotent_replay(token, key, digest):
    """The stored response for a repeated key, a conflict, or None if unseen."""
    if not key:
        return None
    existing = NoteApiIdempotencyRecord.objects.filter(token=token, key=key).first()
    if existing is None:
        return None
    if existing.request_digest != digest:
        return _api_error(
            "idempotency_conflict",
            "This idempotency key was already used with different input.",
            status=409,
        )
    response = JsonResponse(existing.response_body, status=200)
    response["Idempotent-Replay"] = "true"
    return response


def _create_idempotently(token, key, digest, create):
    """Run ``create() -> (note, response_body)`` at most once per key."""
    replay = _idempotent_replay(token, key, digest)
    if replay is not None:
        return replay
    try:
        with transaction.atomic():
            note, response_body = create()
            if key:
                NoteApiIdempotencyRecord.objects.create(
                    token=token,
                    key=key,
                    request_digest=digest,
                    response_body=response_body,
                    note=note,
                )
    except IntegrityError:
        # A concurrent retry can win the unique idempotency-key race. The
        # transaction above rolls back its duplicate before we replay it.
        if not key:
            raise
        replay = _idempotent_replay(token, key, digest)
        if replay is not None:
            return replay
        raise
    return JsonResponse(response_body, status=201)


@csrf_exempt
@require_POST
def api_create_note(request):
    token, error = _api_token_or_error(request, "notes:create")
    if error:
        return error
    payload, error = _json_object_or_error(request)
    if error:
        return error
    error = _unknown_fields_error(
        payload, {"title", "markdown", "slug", "password", "comments_enabled"}
    )
    if error:
        return error

    normalized = {}
    for field in ("title", "slug", "password"):
        value = payload.get(field, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            return _validation_error({field: _invalid_field("Must be a string.")})
        normalized[field] = value

    markdown = payload.get("markdown")
    if not isinstance(markdown, str):
        return _validation_error({"markdown": _invalid_field("Must be a string.")})
    normalized["markdown"] = markdown
    comments_enabled = payload.get("comments_enabled", False)
    if not isinstance(comments_enabled, bool):
        return _validation_error(
            {"comments_enabled": _invalid_field("Must be true or false.")}
        )
    normalized["comments_enabled"] = comments_enabled
    if len(normalized["password"]) > 128:
        return _validation_error(
            {
                "password": [
                    {"message": "Must be 128 characters or fewer.", "code": "max_length"}
                ]
            }
        )

    idempotency_key, error = _idempotency_key_or_error(request)
    if error:
        return error
    request_digest = _request_digest(payload)
    replay = _idempotent_replay(token, idempotency_key, request_digest)
    if replay is not None:
        return replay

    form = NoteForm({**normalized, "clear_password": False})
    if not form.is_valid():
        return _validation_error(form.errors.get_json_data(escape_html=True))

    def create():
        note = form.save()
        return note, _note_api_response(request, note)

    return _create_idempotently(token, idempotency_key, request_digest, create)


def _note_text(note) -> str:
    """Best-effort rendered text of a note, used only to tell API clients
    whether a quote still appears in it. Real anchoring happens in the browser."""
    return unescape(strip_tags(note.html))


def _comment_api_json(request, note, comment, note_text, replies=()):
    data = {
        "id": comment.pk,
        "parent": comment.parent_id,
        "author_name": comment.author_name,
        "is_owner": comment.is_owner,
        "body": comment.body,
        "created_at": comment.created_at.isoformat(),
        "url": request.build_absolute_uri(f"/{note.slug}/#comment-{comment.pk}"),
    }
    if comment.parent_id is None:
        data["anchor"] = (
            {
                "quote": comment.quote,
                "prefix": comment.prefix,
                "suffix": comment.suffix,
                "start_offset": comment.start_offset,
                "quote_in_note": comment.quote in note_text,
            }
            if comment.is_anchored
            else None
        )
        data["replies"] = [
            _comment_api_json(request, note, reply, note_text) for reply in replies
        ]
    return data


def _comment_form_data_or_error(payload):
    """Type-check the JSON comment payload into CommentForm data."""
    errors = {}
    data = {}
    for field in ("body", "quote", "prefix", "suffix", "author_name"):
        value = payload.get(field)
        if value is None:
            value = ""
        if not isinstance(value, str):
            errors[field] = _invalid_field("Must be a string.")
        data[field] = value
    for field in ("parent", "start_offset"):
        value = payload.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            errors[field] = _invalid_field("Must be an integer.")
        data[field] = "" if value is None else value
    if errors:
        return None, _validation_error(errors)
    data["name"] = data.pop("author_name")
    return data, None


@csrf_exempt
def api_note_comments(request, slug):
    """GET lists a note's comment threads; POST adds a comment as the owner."""
    if request.method not in ("GET", "POST"):
        return _api_method_not_allowed("GET", "POST")
    scope = "comments:read" if request.method == "GET" else "comments:write"
    token, error = _api_token_or_error(request, scope)
    if error:
        return error
    note = Note.objects.filter(slug=slug).first()
    if note is None:
        return _api_error("not_found", "No note has that slug.", status=404)

    if request.method == "GET":
        note_text = _note_text(note)
        threads = note.comments.filter(parent__isnull=True).prefetch_related("replies")
        return JsonResponse(
            {
                "note": _note_api_response(request, note),
                "comments": [
                    _comment_api_json(
                        request, note, thread, note_text, replies=thread.replies.all()
                    )
                    for thread in threads
                ],
            }
        )

    payload, error = _json_object_or_error(request)
    if error:
        return error
    error = _unknown_fields_error(
        payload,
        {"body", "parent", "quote", "prefix", "suffix", "start_offset", "author_name"},
    )
    if error:
        return error
    if not note.comments_enabled:
        return _api_error(
            "comments_disabled", "Comments are turned off for this note.", status=409
        )
    data, error = _comment_form_data_or_error(payload)
    if error:
        return error

    idempotency_key, error = _idempotency_key_or_error(request)
    if error:
        return error
    request_digest = _request_digest(
        {"endpoint": "comments", "slug": slug, "payload": payload}
    )
    replay = _idempotent_replay(token, idempotency_key, request_digest)
    if replay is not None:
        return replay

    form = CommentForm(data, note=note, known_name=_account_name(token.user))
    if not form.is_valid():
        fields = form.errors.get_json_data(escape_html=True)
        if "name" in fields:
            fields["author_name"] = fields.pop("name")
        return _validation_error(fields)

    def create():
        comment = form.save(commit=False)
        comment.note = note
        comment.is_owner = True
        comment.save()
        return note, _comment_api_json(request, note, comment, _note_text(note))

    return _create_idempotently(token, idempotency_key, request_digest, create)


@csrf_exempt
def api_note_comment(request, slug, pk):
    """DELETE removes one comment (and its replies) for moderation."""
    if request.method != "DELETE":
        return _api_method_not_allowed("DELETE")
    token, error = _api_token_or_error(request, "comments:write")
    if error:
        return error
    comment = Comment.objects.filter(pk=pk, note__slug=slug).first()
    if comment is None:
        return _api_error("not_found", "No such comment on that note.", status=404)
    comment.delete()
    return HttpResponse(status=204)


def _gate(request, note, next_url):
    if note.has_password and not gate.is_unlocked(request, note.slug):
        return redirect(f"/{note.slug}/unlock/?next={next_url}")
    return None


def _account_name(user) -> str:
    return user.get_full_name() or user.get_username()


def _commenter_name(request) -> str:
    if request.user.is_authenticated:
        return _account_name(request.user)
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
    context = {
        "note": note,
        "container_class": "note-page-width",
        "header_container_class": "note-page-width",
    }
    if note.comments_enabled:
        comments_context = _comments_context(request, note, comment_form)
        context["container_class"] = "max-w-7xl"
        context["header_container_class"] = "note-page-width note-header-width--comments"
        if not comments_context["comment_threads"]:
            context["header_container_class"] += " note-header-width--empty"
        context.update(comments_context)
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
    if comment.parent_id:
        return redirect(f"/{slug}/")
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
        {"form": form, "note": None, "container_class": "max-w-4xl"},
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
        {"form": form, "note": note, "container_class": "max-w-4xl"},
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
