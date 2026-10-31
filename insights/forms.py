from django import forms

from .services import CsvError, validate_csv


class UploadForm(forms.Form):
    file = forms.FileField()

    def clean_file(self):
        f = self.cleaned_data["file"]
        if not f.name.lower().endswith(".csv"):
            raise forms.ValidationError("Please upload a .csv file.")
        try:
            self.rows, self.mapping = validate_csv(f)
        except CsvError as exc:
            raise forms.ValidationError(str(exc))
        f.seek(0)
        return f