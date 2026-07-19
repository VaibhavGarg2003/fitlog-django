from django.urls import path

from . import views

urlpatterns = [
    path("", views.ShareLinkListCreateView.as_view(), name="share-links"),
    path("<slug:slug>", views.ShareLinkDetailView.as_view(), name="share-link"),
    path(
        "<slug:slug>/copy",
        views.ShareLinkCopyView.as_view(),
        name="share-link-copy",
    ),
]
