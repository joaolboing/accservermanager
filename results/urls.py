from django.urls import re_path, path

from . import views

urlpatterns = [
    path("", views.resultSelect, name="instances"),
    path("public/<result>.json", views.download_public, name="download_public"),
    re_path(r"^([^/]+)/?(.*).json", views.download, name="download"),
    re_path(r"^([^/]+)/?(.*)", views.results, name="results"),
]
