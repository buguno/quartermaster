# build: install the runtime dependencies into a virtualenv
FROM python:3.14-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# Poetry lives in its own virtualenv, so it does not end up in the final image.
RUN python -m venv /opt/venv \
    && python -m venv /opt/poetry \
    && /opt/poetry/bin/pip install poetry==2.3.3

WORKDIR /app
# Only the dependency files first, so this layer is cached until they change.
COPY pyproject.toml poetry.lock ./
RUN /opt/poetry/bin/poetry install --only main --no-root --no-interaction


# run: a small image with just the app
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    ENVIRONMENT=production

# gnupg is what the encrypted backup (Settings page) uses.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gnupg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 vault \
    && mkdir /app \
    && chown vault:vault /app

COPY --from=build /opt/venv /opt/venv

WORKDIR /app
COPY --chown=vault:vault manage.py gunicorn.conf.py ./
COPY --chown=vault:vault config ./config
COPY --chown=vault:vault apps ./apps
COPY --chown=vault:vault templates ./templates
COPY --chown=vault:vault static ./static
COPY --chown=vault:vault locale ./locale
COPY --chown=vault:vault --chmod=755 docker-entrypoint.sh /usr/local/bin/

USER vault

# Gather the static files now, so nothing has to run before the first start.
# The values are throwaway: collectstatic never touches the database.
RUN SECRET_KEY=build-only ALLOWED_HOSTS=localhost \
    DATABASE_URL=postgres://build:build@localhost/build \
    python manage.py collectstatic --noinput

EXPOSE 8000

# The app answers on its port (a plain TCP check: no Host header to allow).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8000), 3)"

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--config", "gunicorn.conf.py"]
