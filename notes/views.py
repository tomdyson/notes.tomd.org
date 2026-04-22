from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import gate
from .forms import NoteForm, UnlockForm
from .images import ImageError, process_upload
from .models import Image, Note
from .rendering import toggle_task_in_markdown


def home(request):
    if request.user.is_authenticated:
        return render(
            request,
            "notes/dashboard.html",
            {"notes": Note.objects.all()},
        )
    raise Http404


def _gate(request, note, next_url):
    if note.has_password and not gate.is_unlocked(request, note.slug):
        return redirect(f"/{note.slug}/unlock/?next={next_url}")
    return None


def view_note(request, slug):
    note = get_object_or_404(Note, slug=slug)
    redirect_resp = _gate(request, note, f"/{slug}/")
    if redirect_resp:
        return redirect_resp
    return render(request, "notes/view.html", {"note": note})


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
