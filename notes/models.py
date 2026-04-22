from django.conf import settings
from django.contrib.auth.hashers import check_password as _check_password
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, models, transaction

from .rendering import render_markdown
from .slugs import generate_slug


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
            return
        super().save(*args, **kwargs)

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
