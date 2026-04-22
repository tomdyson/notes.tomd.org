from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from notes.models import Image


class Command(BaseCommand):
    help = "Delete orphaned Image rows (no note FK) older than --hours."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=24,
            help="Minimum age in hours for an orphan to be swept (default: 24).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted without deleting.",
        )

    def handle(self, *args, hours, dry_run, **kwargs):
        cutoff = timezone.now() - timedelta(hours=hours)
        orphans = Image.objects.filter(note__isnull=True, created_at__lt=cutoff)
        count = orphans.count()
        if dry_run:
            self.stdout.write(f"Would delete {count} orphan image(s).")
            return
        # Delete individually so the post_delete signal removes files too.
        for img in orphans:
            img.delete()
        self.stdout.write(f"Deleted {count} orphan image(s).")
