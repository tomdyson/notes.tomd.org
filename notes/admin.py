from django.contrib import admin

from .models import NoteApiToken


@admin.register(NoteApiToken)
class NoteApiTokenAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "user",
        "prefix",
        "scopes",
        "created_at",
        "last_used_at",
        "revoked_at",
    )
    readonly_fields = (
        "user",
        "name",
        "prefix",
        "token_digest",
        "scopes",
        "created_at",
        "last_used_at",
        "revoked_at",
    )

    def has_add_permission(self, request):
        return False
