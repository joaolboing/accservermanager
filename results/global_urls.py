from django.urls import path

from . import views

urlpatterns = [
    path("", views.all_results, name="all_results"),
    path(
        "public/<instance>/<result>.json",
        views.download_public_global,
        name="download_public_global",
    ),
]
