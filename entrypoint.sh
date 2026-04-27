#!/bin/sh
python manage.py migrate
python manage.py collectstatic --noinput
exec gunicorn --bind 0.0.0.0:8000 --timeout 120 --workers 6 sideline.wsgi:application