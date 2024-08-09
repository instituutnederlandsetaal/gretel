# Dockerfile for building the backend+frontend
# This needs to be in one file as the frontend also needs the static files from the backend.
# This process is 3 steps:
# 1. create the python/django backend container
# 2. run collectstatic in a separate copy of the backend container we just created.
# This container won't be published, but it will be used to extract the static files.
# 3. create the frontend build container. 
# This container won't be published either.
# 4. create the actual frontend container. 
# This is an nginx container that contains the backend+frontend static files
# And selectively forwards/proxies requests to the django backend.


# The backend runtime container.
# buster is the debian version, pin it so that the image is reproducible
FROM python:3.11-buster as backend

WORKDIR /app

RUN apt update
RUN apt install unar -y

# Copy requirements.in, expand then, and install the dependencies.
RUN python -m pip install pip-tools

COPY backend/requirements.in backend/requirements.in
RUN pip-compile backend/requirements.in --output-file backend/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip-sync backend/requirements.txt

# Debug mode. By default the container doesn't use the debugpy package, but 
# For convenience we install it so that we can easily switch to debug mode.
RUN python -m pip install debugpy

# Copy the backend code.
COPY backend backend
WORKDIR /app/backend
RUN python manage.py migrate

RUN echo "\
ALLOWED_HOSTS = ['*'] \n\
" >> gretel/settings.py

# This is the debug command. You can switch to it if you need to debug the python code.
# CMD python -Xfrozen_modules=off -m debugpy --wait-for-client --listen 0.0.0.0:5678 manage.py runserver 0.0.0.0:8000 --pythonpath ..
CMD python manage.py migrate && python manage.py runserver 0.0.0.0:8000 --pythonpath ..

# The frontend builder. 
FROM node:18-alpine as staticfiles-frontend

WORKDIR /app

# :( for retrieving the build number. This is pretty slow.
COPY .git .git 
RUN apk add git

COPY package.json package.json
COPY web-ui/package.json web-ui/package.json

RUN --mount=type=cache,target=/root/.yarn YARN_CACHE_FOLDER=/root/.yarn yarn fyarn install

COPY web-ui web-ui

RUN yarn fyarn build

# Extract the static files from the django container
FROM backend as staticfiles-backend

# Collect static files. 
RUN echo "\
STATIC_ROOT = '/app/static' \n\
" >> gretel/settings.py

RUN mkdir /app/static
RUN python manage.py collectstatic --noinput

FROM nginx:1.27-alpine as frontend

# Copy the nginx configuration file.
COPY docker/production/nginx.conf /etc/nginx/conf.d/default.conf

# Copy the static files from the staticfiles stage to the nginx directory.
COPY --from=staticfiles-backend /app/static /app/
COPY --from=staticfiles-frontend /app/web-ui/dist /app/

# Daemon off just makes nginx run in the foreground.
# So we can inspect logs and so on.
CMD ["nginx", "-g", "daemon off;"]