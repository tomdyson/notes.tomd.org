from django.urls import path

from . import passkey_views, views

app_name = "notes"

urlpatterns = [
    path("", views.home, name="home"),
    path("new/", views.new_note, name="new"),
    path("upload/", views.upload_image, name="image_upload"),
    path("i/<slug:short_id>.webp", views.serve_image, name="image_serve"),
    path("passkeys/", passkey_views.manage, name="passkeys"),
    path("passkeys/register/begin/", passkey_views.register_begin, name="passkey_register_begin"),
    path("passkeys/register/finish/", passkey_views.register_finish, name="passkey_register_finish"),
    path("passkeys/login/begin/", passkey_views.login_begin, name="passkey_login_begin"),
    path("passkeys/login/finish/", passkey_views.login_finish, name="passkey_login_finish"),
    path("passkeys/<int:pk>/delete/", passkey_views.delete, name="passkey_delete"),
    path("<slug:slug>/", views.view_note, name="view"),
    path("<slug:slug>/raw", views.raw_note, name="raw"),
    path("<slug:slug>/edit/", views.edit_note, name="edit"),
    path("<slug:slug>/delete/", views.delete_note, name="delete"),
    path("<slug:slug>/unlock/", views.unlock_note, name="unlock"),
]
