from django.shortcuts import get_object_or_404, redirect, render

from .forms import UploadForm
from .models import Dataset
from .services import CsvError, analyze, read_csv


def upload(request):
    form = UploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        f = form.cleaned_data["file"]
        dataset = Dataset.objects.create(
            name=f.name, file=f, row_count=form.rows, mapping=form.mapping
        )
        try:
            with dataset.file.open("rb") as fh:
                dataset.summary = analyze(fh, dataset.mapping)
        except CsvError as exc:
            dataset.delete()
            form.add_error("file", str(exc))
        else:
            dataset.save(update_fields=["summary"])
            return redirect("dataset_detail", pk=dataset.pk)
    return render(request, "insights/upload.html", {"form": form, "recent": Dataset.objects.all()[:5]})


def dataset_detail(request, pk):
    dataset = get_object_or_404(Dataset, pk=pk)
    with dataset.file.open("rb") as f:
        preview = read_csv(f, nrows=5).fillna("")
    return render(request, "insights/detail.html", {
        "dataset": dataset,
        "columns": list(preview.columns),
        "rows": preview.values.tolist(),
    })