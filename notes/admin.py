from django.contrib import admin

from .models import Comment, NoteApiToken


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


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("author_name", "note", "parent", "created_at")
    list_filter = ("note",)
    search_fields = ("author_name", "body", "quote")
    readonly_fields = ("author_key", "created_at")
