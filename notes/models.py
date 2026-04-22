import re

from django.conf import settings
from django.contrib.auth.hashers import check_password as _check_password
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .rendering import render_markdown
from .slugs import generate_slug


_IMAGE_REF_RE = re.compile(r"/i/([A-Za-z0-9]+)\.webp")


class Note(models.Model):
    slug = models.CharField(max_length=64, unique=True, db_index=True, blank=True)
    title = models.CharField(max_length=200, blank=True)
    markdown = models.TextField()
    html = models.TextField(blank=True)
    password_hash = models.CharField(max_length=256, blank=True)
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
