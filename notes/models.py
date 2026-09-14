import hashlib
import re
import secrets

from django.conf import settings
from django.contrib.auth.hashers import check_password as _check_password
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

from .rendering import render_markdown
from .slugs import generate_slug


_IMAGE_REF_RE = re.compile(r"/i/([A-Za-z0-9]+)\.webp")


class Note(models.Model):
    slug = models.CharField(max_length=64, unique=True, db_index=True, blank=True)
    title = models.CharField(max_length=200, blank=True)
    markdown = models.TextField()
    html = models.TextField(blank=True)
    password_hash = models.CharField(max_length=256, blank=True)
    comments_enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.title or self.slug or f"note-{self.pk}"

    @property
    def has_password(self) -> bool:
        return bool(self.password_hash)

    def set_password(self, raw: str) -> None:
        self.password_hash = make_password(raw) if raw else ""

    def clear_password(self) -> None:
        self.password_hash = ""

    def check_password(self, raw: str) -> bool:
        if not self.password_hash:
            return False
        return _check_password(raw, self.password_hash)

    def save(self, *args, **kwargs):
        self.html = render_markdown(self.markdown)
        if not self.slug:
            self._save_with_generated_slug(*args, **kwargs)
        else:
            super().save(*args, **kwargs)
        self._attach_referenced_images()

    def _save_with_generated_slug(self, *args, **kwargs):
        for _ in range(8):
            self.slug = generate_slug()
            try:
                with transaction.atomic():
                    super().save(*args, **kwargs)
                return
            except IntegrityError:
                continue
        raise IntegrityError("could not allocate a unique slug after 8 tries")

    def _attach_referenced_images(self):
        """Link any Image rows referenced in this note's markdown to self."""
        ids = set(_IMAGE_REF_RE.findall(self.markdown or ""))
        if not ids:
            return
        Image.objects.filter(short_id__in=ids).update(note=self)


class Comment(models.Model):
    """A reader's comment on a note, optionally anchored to a text selection.

    Anchoring follows the W3C Web Annotation text-quote model: ``quote`` is the
    selected text as it appeared in the rendered note, ``prefix``/``suffix``
    are a few characters of surrounding context used to disambiguate repeated
    phrases, and ``start_offset`` is a hint into the rendered text content.
    The selectors are captured and resolved in the browser; the server stores
    them verbatim. A comment with no ``quote`` is a note-level comment.
    """

    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="comments")
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="replies"
    )
    author_name = models.CharField(max_length=80)
    # Random per-browser token, stored in the session, so a commenter can
    # delete their own comments without an account. Never shown to readers.
    author_key = models.CharField(max_length=64, blank=True, db_index=True)
    # Set when the logged-in note owner comments, so replies get an author badge.
    is_owner = models.BooleanField(default=False)
    body = models.TextField()
    quote = models.TextField(blank=True)
    prefix = models.CharField(max_length=64, blank=True)
    suffix = models.CharField(max_length=64, blank=True)
    start_offset = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self) -> str:
        return f"{self.author_name} on {self.note}"

    @property
    def is_anchored(self) -> bool:
        return bool(self.quote)


class NoteApiToken(models.Model):
    """Revocable bearer token for the note API; the secret is never stored."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="note_api_tokens",
    )
    name = models.CharField(max_length=80)
    prefix = models.CharField(max_length=12, db_index=True)
    token_digest = models.CharField(max_length=64, unique=True)
    scopes = models.CharField(max_length=255, default="notes:create")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix}…)"

    @staticmethod
    def digest(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()

    @classmethod
    def issue(cls, *, user, name: str, scopes: str = "notes:create"):
        secret = f"nt_{secrets.token_urlsafe(32)}"
        token = cls.objects.create(
            user=user,
            name=name,
            prefix=secret[:12],
            token_digest=cls.digest(secret),
            scopes=scopes,
        )
        return token, secret

    @classmethod
    def authenticate(cls, secret: str):
        if not secret or not secret.startswith("nt_"):
            return None
        return (
            cls.objects.select_related("user")
            .filter(
                token_digest=cls.digest(secret),
                revoked_at__isnull=True,
                user__is_active=True,
            )
            .first()
        )

    def permits(self, scope: str) -> bool:
        return scope in self.scopes.split()

    def mark_used(self) -> None:
        now = timezone.now()
        type(self).objects.filter(pk=self.pk).update(last_used_at=now)
        self.last_used_at = now

    def revoke(self) -> None:
        now = timezone.now()
        type(self).objects.filter(pk=self.pk).update(revoked_at=now)
        self.revoked_at = now


class NoteApiIdempotencyRecord(models.Model):
    token = models.ForeignKey(
        NoteApiToken,
        on_delete=models.CASCADE,
        related_name="idempotency_records",
    )
    key = models.CharField(max_length=200)
    request_digest = models.CharField(max_length=64)
    response_body = models.JSONField()
    note = models.ForeignKey(Note, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["token", "key"],
                name="unique_note_api_idempotency_key",
            )
        ]


def _image_upload_to(instance, filename):
    return f"images/{instance.short_id}.webp"


class Image(models.Model):
    short_id = models.CharField(max_length=16, unique=True, db_index=True, blank=True)
    note = models.ForeignKey(
        "Note",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="images",
    )
    file = models.ImageField(upload_to=_image_upload_to)
    original_name = models.CharField(max_length=255, blank=True)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"image-{self.short_id}"

    def assign_short_id(self) -> str:
        """Generate and assign a unique short_id without saving the row."""
        for _ in range(8):
            candidate = generate_slug()
            if not Image.objects.filter(short_id=candidate).exists():
                self.short_id = candidate
                return candidate
        raise IntegrityError("could not allocate a unique image short_id after 8 tries")

    def save(self, *args, **kwargs):
        if not self.short_id:
            self._save_with_generated_short_id(*args, **kwargs)
            return
        super().save(*args, **kwargs)

    def _save_with_generated_short_id(self, *args, **kwargs):
        last_err = None
        for _ in range(8):
            self.short_id = generate_slug()
            try:
                with transaction.atomic():
                    super().save(*args, **kwargs)
                return
            except IntegrityError as e:
                last_err = e
                continue
        raise IntegrityError(
            f"could not allocate a unique image short_id after 8 tries: {last_err}"
        )


@receiver(post_delete, sender=Image)
def _delete_image_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)


class Passkey(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="passkeys"
    )
    credential_id = models.BinaryField(unique=True)
    public_key = models.BinaryField()
    sign_count = models.PositiveIntegerField(default=0)
    name = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name or f"passkey-{self.pk}"
