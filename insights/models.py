from django.db import models


class Dataset(models.Model):
    name = models.CharField(max_length=255)
    file = models.FileField(upload_to="datasets/")
    row_count = models.PositiveIntegerField()
    mapping = models.JSONField(default=dict)
    summary = models.JSONField(default=dict, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.name