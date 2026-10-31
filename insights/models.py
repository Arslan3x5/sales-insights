from django.db import models

# Create your models here.
    summary = models.JSONField(default=dict, blank=True)