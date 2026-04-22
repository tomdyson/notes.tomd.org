from django import forms

from .models import Note
from .slugs import is_reserved, is_valid_slug_shape


class NoteForm(forms.ModelForm):
    password = forms.CharField(required=False, widget=forms.PasswordInput, strip=False)
    clear_password = forms.BooleanField(required=False)

    class Meta:
        model = Note
        fields = ["slug", "title", "markdown"]

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
