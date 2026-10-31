from django.urls import path

from . import views

urlpatterns = [
    path("", views.upload, name="upload"),
    path("dataset/<int:pk>/", views.dataset_detail, name="dataset_detail"),
]