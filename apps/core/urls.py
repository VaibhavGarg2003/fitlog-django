from django.urls import path

from . import views

urlpatterns = [
    path("healthz", views.healthz, name="healthz"),
    path("whoami", views.whoami, name="whoami"),
]
