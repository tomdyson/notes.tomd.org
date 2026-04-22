from django.urls import path

from . import views

app_name = "notes"

urlpatterns = [
    path("", views.home, name="home"),
    path("new/", views.new_note, name="new"),
    path("<slug:slug>/", views.view_note, name="view"),
    path("<slug:slug>/raw", views.raw_note, name="raw"),
    path("<slug:slug>/edit/", views.edit_note, name="edit"),
    path("<slug:slug>/delete/", views.delete_note, name="delete"),
    path("<slug:slug>/unlock/", views.unlock_note, name="unlock"),
]
