from django.core.management.base import BaseCommand, CommandError

from notes.models import NoteApiToken


class Command(BaseCommand):
    help = (
        "Replace the scopes of an existing, unrevoked note API token, found by "
        "its prefix (shown in the admin). The secret is unchanged."
    )

    def add_arguments(self, parser):
        parser.add_argument("--prefix", required=True, help="Token prefix, e.g. nt_AbCdEf123")
        parser.add_argument(
            "--scopes",
            required=True,
            help="Space-separated scopes. Known: " + ", ".join(NoteApiToken.KNOWN_SCOPES),
        )

    def handle(self, *args, prefix, scopes, **kwargs):
        try:
            scopes = NoteApiToken.normalize_scopes(scopes)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        matches = list(NoteApiToken.objects.filter(prefix=prefix, revoked_at__isnull=True))
        if not matches:
            raise CommandError(f"No active token with prefix '{prefix}'.")
        if len(matches) > 1:
            raise CommandError(f"More than one active token has prefix '{prefix}'.")
        token = matches[0]
        token.scopes = scopes
        token.save(update_fields=["scopes"])
        self.stdout.write(self.style.SUCCESS(f"Token {token.prefix}… ({token.name}) now has: {scopes}"))
