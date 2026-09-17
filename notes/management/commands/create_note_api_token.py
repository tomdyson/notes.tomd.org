from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from notes.models import NoteApiToken


class Command(BaseCommand):
    help = "Create a note API bearer token and print its secret once."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--name", default="Codex")
        parser.add_argument(
            "--scopes",
            default="notes:create",
            help="Space-separated scopes. Known: " + ", ".join(NoteApiToken.KNOWN_SCOPES),
        )

    def handle(self, *args, username, name, scopes="notes:create", **kwargs):
        user_model = get_user_model()
        try:
            user = user_model.objects.get(username=username)
        except user_model.DoesNotExist as exc:
            raise CommandError(f"No user named '{username}'.") from exc
        try:
            scopes = NoteApiToken.normalize_scopes(scopes)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        token, secret = NoteApiToken.issue(user=user, name=name, scopes=scopes)
        self.stdout.write(
            self.style.SUCCESS(f"Created token {token.prefix}… for {username} ({scopes}).")
        )
        self.stdout.write(secret)
        self.stdout.write(self.style.WARNING("Store it securely; it is shown only once."))
