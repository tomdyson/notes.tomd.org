from django import forms

from .models import Comment, Note
from .slugs import is_reserved, is_valid_slug_shape


class NoteForm(forms.ModelForm):
    password = forms.CharField(required=False, widget=forms.PasswordInput, strip=False)
    clear_password = forms.BooleanField(required=False)

    class Meta:
        model = Note
        fields = ["slug", "title", "markdown", "comments_enabled"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False

    def clean_slug(self):
        slug = (self.cleaned_data.get("slug") or "").strip()
        if not slug:
            return ""
        if not is_valid_slug_shape(slug):
            raise forms.ValidationError(
                "Slug must start with a letter or digit and contain only "
                "letters, digits, hyphens or underscores."
            )
        if is_reserved(slug):
            raise forms.ValidationError(f"Slug '{slug}' is reserved.")
        qs = Note.objects.filter(slug=slug)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A note with that slug already exists.")
        return slug

    def save(self, commit=True):
        note = super().save(commit=False)
        pw = self.cleaned_data.get("password") or ""
        clear = self.cleaned_data.get("clear_password")
        if clear:
            note.clear_password()
        elif pw:
            note.set_password(pw)
        if commit:
            note.save()
        return note


class UnlockForm(forms.Form):
    password = forms.CharField(widget=forms.PasswordInput, strip=False)


COMMENT_BODY_MAX = 5000
COMMENT_QUOTE_MAX = 2000


class CommentForm(forms.ModelForm):
    """A reader's comment. ``name`` falls back to the name already known for
    this visitor (session, or the logged-in account) so it is only required
    the first time someone comments."""

    name = forms.CharField(max_length=80, required=False)
    parent = forms.ModelChoiceField(queryset=Comment.objects.none(), required=False)

    class Meta:
        model = Comment
        fields = ["body", "quote", "prefix", "suffix", "start_offset"]

    def __init__(self, *args, note, known_name="", **kwargs):
        super().__init__(*args, **kwargs)
        self.known_name = known_name
        # Replies attach to a thread, never to another reply.
        self.fields["parent"].queryset = note.comments.filter(parent__isnull=True)
        # Surrounding whitespace is part of the selector; keep it verbatim.
        for field in ("quote", "prefix", "suffix"):
            self.fields[field].strip = False

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip() or self.known_name
        if not name:
            raise forms.ValidationError("Please add your name.")
        return name

    def clean_body(self):
        body = (self.cleaned_data.get("body") or "").strip()
        if not body:
            raise forms.ValidationError("Write something first.")
        if len(body) > COMMENT_BODY_MAX:
            raise forms.ValidationError(
                f"Comments are limited to {COMMENT_BODY_MAX} characters."
            )
        return body

    def clean_quote(self):
        quote = self.cleaned_data.get("quote") or ""
        if len(quote) > COMMENT_QUOTE_MAX:
            raise forms.ValidationError("That selection is too long to comment on.")
        return quote

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("parent"):
            # A reply belongs to its thread; the thread's anchor is its anchor.
            cleaned.update(quote="", prefix="", suffix="", start_offset=None)
        return cleaned

    def save(self, commit=True):
        comment = super().save(commit=False)
        comment.author_name = self.cleaned_data["name"]
        comment.parent = self.cleaned_data.get("parent")
        if commit:
            comment.save()
        return comment
