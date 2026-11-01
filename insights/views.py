from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .forms import UploadForm
from .models import Dataset
from .services import CsvError, analyze, read_csv

SESSION_KEY = "dataset_ids"


def my_ids(request):
    """IDs of the datasets this visitor uploaded in this browser session."""
    return request.session.get(SESSION_KEY, [])


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
            request.session[SESSION_KEY] = (my_ids(request) + [dataset.pk])[-20:]
            return redirect("dataset_detail", pk=dataset.pk)
    recent = Dataset.objects.filter(pk__in=my_ids(request))[:5]
    return render(request, "insights/upload.html", {"form": form, "recent": recent})


def dataset_detail(request, pk):
    if pk not in my_ids(request):
        raise Http404("Dataset not found.")
    dataset = get_object_or_404(Dataset, pk=pk)
    with dataset.file.open("rb") as f:
        preview = read_csv(f, nrows=5).fillna("")
    return render(request, "insights/detail.html", {
        "dataset": dataset,
        "columns": list(preview.columns),
        "rows": preview.values.tolist(),
    })