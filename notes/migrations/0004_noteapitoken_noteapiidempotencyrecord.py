import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("notes", "0003_image"),
    ]

    operations = [
        migrations.CreateModel(
            name="NoteApiToken",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=80)),
                ("prefix", models.CharField(db_index=True, max_length=12)),
                ("token_digest", models.CharField(max_length=64, unique=True)),
                ("scopes", models.CharField(default="notes:create", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="note_api_tokens",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="NoteApiIdempotencyRecord",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key", models.CharField(max_length=200)),
                ("request_digest", models.CharField(max_length=64)),
                ("response_body", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "note",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="notes.note",
                    ),
                ),
                (
                    "token",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="idempotency_records",
                        to="notes.noteapitoken",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="noteapiidempotencyrecord",
            constraint=models.UniqueConstraint(
                fields=("token", "key"),
                name="unique_note_api_idempotency_key",
            ),
        ),
    ]
