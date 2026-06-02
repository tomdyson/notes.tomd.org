from django.core.management.base import BaseCommand

from notes.models import Note
from notes.rendering import render_markdown


class Command(BaseCommand):
    help = (
        "Re-render every note's stored html from its markdown. Use after a "
        "rendering change so existing notes pick it up. Only notes whose html "
        "actually changes are written, and updated_at is preserved (a re-render "
        "is not an edit)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many notes would change without writing.",
        )

    def handle(self, *args, dry_run, **kwargs):
        changed = 0
        total = 0
        for note in Note.objects.all().iterator():
            total += 1
            new_html = render_markdown(note.markdown)
            if new_html == note.html:
                continue
            changed += 1
            if not dry_run:
                # Bypass save() so we don't bump updated_at (auto_now) or rerun
                # slug generation / image attachment — we only want fresh html.
                Note.objects.filter(pk=note.pk).update(html=new_html)
        if dry_run:
            self.stdout.write(f"Would update {changed} of {total} note(s).")
        else:
            self.stdout.write(f"{changed} updated, {total - changed} unchanged.")
