#!/bin/sh
set -e

python manage.py migrate --noinput

if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
  python manage.py shell <<PY
from django.contrib.auth import get_user_model
import os
U = get_user_model()
u = os.environ["DJANGO_SUPERUSER_USERNAME"]
p = os.environ["DJANGO_SUPERUSER_PASSWORD"]
e = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
user, created = U.objects.get_or_create(username=u, defaults={"email": e, "is_staff": True, "is_superuser": True})
if created or not user.check_password(p):
    user.set_password(p)
    user.is_staff = True
    user.is_superuser = True
    if e:
        user.email = e
    user.save()
    print(f"superuser {'created' if created else 'updated'}: {u}")
else:
    print(f"superuser exists: {u}")
PY
fi

exec gunicorn \
  --bind 0.0.0.0:8000 \
  --workers 2 \
  --access-logfile - \
  --error-logfile - \
  --capture-output \
  --log-level info \
  noteserver.wsgi:application
