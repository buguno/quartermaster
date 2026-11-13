#!/bin/sh
# Optionally apply migrations, then run the command (gunicorn by default).
set -e

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    python manage.py migrate --noinput
fi

exec "$@"
