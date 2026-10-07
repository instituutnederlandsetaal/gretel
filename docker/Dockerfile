# syntax=docker/dockerfile:1

FROM python:3.13-slim-bookworm AS backend
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=gretel.settings_docker \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends unar \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY pyproject.toml uv.lock /app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev
COPY backend .

EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn gretel.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 300"]

FROM backend AS backend-dev
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked
ENV DJANGO_SETTINGS_MODULE=gretel.settings
CMD ["sh", "-c", "python manage.py migrate --noinput && exec python -Xfrozen_modules=off -m debugpy --listen 0.0.0.0:5678 manage.py runserver 0.0.0.0:8000"]

FROM backend AS staticfiles-backend
RUN DJANGO_SECRET_KEY=collectstatic-build-only python manage.py collectstatic --noinput

FROM node:18.20.8-alpine AS frontend-dev
WORKDIR /app/web-ui
EXPOSE 4200
# The source is bind-mounted; keep the container's dependencies in a separate volume.
CMD ["sh", "-c", "npm ci && exec npm run serve-docker"]

FROM frontend-dev AS staticfiles-frontend
COPY web-ui/package.json web-ui/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY package.json /app/package.json
COPY web-ui .
ARG BUILD_SHA=unknown
ARG BUILD_SOURCE_URL=github:CentreForDigitalHumanities/gretel
RUN BUILD_SHA="$BUILD_SHA" BUILD_SOURCE_URL="$BUILD_SOURCE_URL" npm run build

FROM nginx:stable-alpine AS frontend
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=staticfiles-backend /app/backend/static /app/
COPY --from=staticfiles-frontend /app/web-ui/dist /app/
