# GrETEL 5

[![Actions Status](https://github.com/CentreForDigitalHumanities/gretel/workflows/Tests/badge.svg)](https://github.com/CentreForDigitalHumanities/gretel/actions)
[![DOI](https://zenodo.org/badge/95562504.svg)](https://zenodo.org/badge/latestdoi/95562504)

GrETEL stands for Greedy Extraction of Trees for Empirical Linguistics. It is a user-friendly search engine for the exploitation of syntactically annotated corpora or treebanks

GrETEL is publicly available at [https://gretel5.hum.uu.nl](https://gretel5.hum.uu.nl)

## Build and development

The application consists of a Django backend in `backend/` and an Angular frontend in
`web-ui/`. The backend uses SQLite. Search and dataset processing also need BaseX,
Redis, a Celery worker and an Alpino parser.

### Local setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and the Node.js
version in `.nvmrc`. uv manages Python 3.13 and the local `.venv`. Node 18 is retained for
[compatibility with Angular 15](https://angular.dev/reference/versions); a newer Node
major needs an Angular upgrade. npm is the frontend package manager, and
`web-ui/package-lock.json` is its dependency lockfile.

From the repository root:

```console
nvm install
nvm use
npm run setup
```

`npm run setup` syncs the locked Python dependencies, runs `npm ci` in `web-ui/`,
and applies the Django migrations. It stops on any failure. Set
`UV_PROJECT_ENVIRONMENT` to choose another Python environment.

Start the frontend and backend in separate terminals:

```console
npm start
npm run start-back
```

Visit <http://localhost:4200/>. The frontend proxies backend routes to
<http://localhost:8000/>, where the Django admin is available at `/admin/`.
`npm start` reloads frontend changes and Django's development server reloads
backend changes. `serve:acc` and `serve:live` in `web-ui/` target the acceptance and
live backends respectively.

For search and uploads, start BaseX and Redis, then run:

```console
./alpino.sh
# In another terminal:
uv run --locked --directory backend celery -A gretel.celery worker --loglevel=info -B
```

For a local BaseX server, set its admin password to `admin` to match
`backend/gretel/settings.py`. The backend defaults to BaseX on port 1984, Alpino
on port 7001 and Redis on its default port, all on localhost. Set `BASEX_HOST`,
`ALPINO_HOST` and `REDIS_HOST` when these services run elsewhere. The Docker
setup below starts all of these services for you.

### Common commands

Run these from the repository root; Python commands use `uv run` without activation:

| Command | Purpose |
| --- | --- |
| `npm run install-front` | Install the locked frontend dependencies with `npm ci` |
| `npm run install-back` | Sync the locked Python runtime and development dependencies |
| `npm run django -- migrate` | Apply Django migrations |
| `npm run build` | Build the production frontend into `web-ui/dist/` |
| `npm test` | Run backend and frontend unit tests |
| `npm run test-back` | Run the backend tests; BaseX enables the search integration tests |
| `npm run test-front` | Run the frontend tests once in headless Chrome |
| `npm run lint-back` | Check Python syntax and undefined names |

Build, serve and test commands generate `web-ui/src/environments/version.ts`
automatically. Git metadata is used when available; source archives and Docker
builds also work. Set `BUILD_SHA` and `BUILD_SOURCE_URL` to supply build metadata
without copying `.git` into a container.

Python dependencies are declared in `pyproject.toml` and pinned in `uv.lock`.
Development tools (tests, lint and debugpy) belong to the `dev` dependency group;
production Docker images install only runtime dependencies. Commit both files
when changing dependencies:

```console
uv add PACKAGE
uv add --dev PACKAGE
uv lock --upgrade-package PACKAGE
```

## Docker deployment

Docker Compose 2.24.4 or newer is required for the development override.
The default Compose file starts Nginx, Gunicorn/Django, Celery with its periodic
scheduler, BaseX, Redis and Alpino. Only Nginx is exposed to the host in production.
Django migrations run when the backend starts, before Celery and Nginx start.
Image builds install the committed dependency pins and never create a database.

### Production

Copy `docker/.env.example` to `docker/.env`, set `DJANGO_SECRET_KEY` to a generated
secret, and set `DJANGO_ALLOWED_HOSTS` to the hostnames used to access the site.
Configure SMTP in the same file for login codes, email verification and password
resets. For HTTPS behind an external reverse proxy, set
`DJANGO_CSRF_TRUSTED_ORIGINS` to the public origin including the scheme.

```console
cp docker/.env.example docker/.env
uv run --no-project --python 3.13 python -c 'import secrets; print(secrets.token_urlsafe(50))'
# Put the generated value in DJANGO_SECRET_KEY in docker/.env.
docker compose -f docker/docker-compose.yml up --build -d
```

Visit <http://localhost/> (or the configured hostname and `FRONTEND_PORT`).
Production runs with Django debug mode disabled. The database, uploads, search
cache and BaseX databases persist in Docker volumes. `docker compose down`
retains them; adding `-v` deletes those volumes and their data.

To use published images, set `REGISTRY` and `VERSION` in `docker/.env` if needed:

```console
docker compose -f docker/docker-compose.yml pull
docker compose -f docker/docker-compose.yml up --no-build -d
```

The manually triggered **Publish container images** GitHub workflow publishes
`gretel5-backend`, `gretel5-frontend` and `gretel5-basex` under
`ghcr.io/<owner>/<repository>/`. It tags images by branch or release tag and
commit; `latest` is updated only from the default branch. Compose uses that same
image naming scheme. Local builds can set `BUILD_SHA` and `BUILD_SOURCE_URL`
in `docker/.env` to display their revision in the frontend.

### Docker development

```console
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up --build
```

Visit <http://localhost:4200/>. The development override runs Angular with live
reload, Django's development server and debugpy. Attach to port 5678 for Django
or 5679 for Celery using the included VS Code configurations. Development does
not require a production secret key.

The backend source is mounted from `backend/`; its SQLite database, uploads,
cache and BaseX data stay there, separate from production volumes. Frontend
dependencies have their own Docker volume and are refreshed with `npm ci` on
startup. Stop one stack before starting the other; both use the same Compose project.
Use both `-f` arguments when stopping the development stack as well.

### User registration and dataset uploads

Uploading datasets requires a signed-in user. Registration is disabled by
default. Set `REGISTRATION_ENABLED=true` in the backend environment, or in
`docker/.env`, to enable it. Restart the backend after changing it; Compose
recreates the affected containers on `up -d`. Public datasets remain searchable
without signing in.

Provision an initial administrator locally with:

```console
npm run django -- provision-superuser --username admin --email admin@example.org
```

For a running Docker deployment:

```console
docker compose -f docker/docker-compose.yml exec backend python manage.py provision-superuser --username admin --email admin@example.org
```

The command prompts for a password and verifies the operator-provided email so
the account can sign in while registration is closed. For noninteractive
provisioning, pass `--noinput` and supply `DJANGO_SUPERUSER_PASSWORD`. Django's
standard `createsuperuser` remains available but does not verify the email for
frontend sign-in.

Sign in through **Login**, open **Upload** (`/upload-treebank`), enter the dataset
details, select the file, check **Public**, and submit. Celery processes the
dataset; it becomes visible to anonymous visitors when processing completes.
BaseX, Celery and Redis must be running, as must Alpino for unparsed input.

## Notes for users

Only the properties of the first node matched by an XPATH variable is returned for analysis. For example:

A user searches for `//node[node]`. Two variables are found in this query: `$node1 = //node` and `$node2 = $node1[node]`.

The following sentence would match this query:

`node[np] (node[det] node[noun])`

The node found for `$node1` will then be `node[np]`.
The node found for `$node2` will then be `node[det]`. The properties of `node[noun]` will not be available for analysis using this query.

When searching for a more specific structure, this is unlikely to occur.

## Info

- v5.1.0 June 2025: full replacement of GrETEL 4
- v4.2.0 August 2019: federated search, improved configuration and state management, download results with node properties and again [many more fixes](https://github.com/CentreForDigitalHumanities/gretel/compare/v4.1.0...v4.2.0).
- v4.1.0 February 2019: Fixed support for GrInded corpora, [many more fixes](https://github.com/CentreForDigitalHumanities/gretel/compare/v4.0.2...v4.1.0), feature complete replacement of version 3.
- v4.0.2 October 2018: GrETEL 4 release with many bugfixes and improvements.
- v4.0.0 June 2018: First GrETEL 4 release with new interface.
- v3.9.99 November 2017: GrETEL 4 currently under development!
- v3.0.2 July 2017: Show error message if the BaseX server is down  
- v3.0. November 2016: GrETEL 3 initial release. Available at <http://gretel.ccl.kuleuven.be/gretel3>

### Branches

- `main`: official version of GrETEL 5, available at <https://gretel5.hum.uu.nl/gretel/>
- `develop`: development version  
- `gretel2.0`: official version of GrETEL 2.0, available at <https://gretel.ccl.kuleuven.be/gretel-2.0>

## Credits

- [Liesbeth Augustinus](https://www.ccl.kuleuven.be/~liesbeth/) and [Vincent Vandeghinste](https://www.ccl.kuleuven.be/~vincent/ccl): concept and initial implementation;
- [Bram Vanroy](https://bramvanroy.be/): GrETEL 3 improvements and design;
- [Martijn van der Klis](http://www.uu.nl/staff/MHvanderKlis): initial GrETEL 4 functionality and improvements;
- [Sheean Spoel](https://www.uu.nl/staff/SJJSpoel), [Gerson Foks](https://www.linkedin.com/in/gerson-foks-50b784b2) and [Jelte van Boheemen](https://www.uu.nl/medewerkers/JvanBoheemen): additional GrETEL 4 functionality and improvements;
- [Ben Bonfil](https://www.uu.nl/staff/BBonfil) and [Tijmen Baarda](https://www.uu.nl/staff/TCBaarda): additional GrETEL 5 functionality and improvements;
- [Jan Odijk](https://www.clariah.nl/nl/personen/jan-odijk) project lead for GrETEL 4 and GrETEL 5 developments;
- [Koen Mertens](https://github.com/KCMertens): federated search at [Instituut voor de Nederlandse taal](https://ivdnt.org).
- Colleagues at the [Centre for Computational Linguistics at KU Leuven](http://www.arts.kuleuven.be/ling/ccl), and [Centre for Digital Humanities at Utrecht University](https://cdh.uu.nl/about/research-software-lab/) for their feedback.

## License

This work is licensed under the Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License (cc-by-sa-4.0). See the [LICENSE](LICENSE) file for license rights and limitations.
