# GrETEL frontend

This is the Angular 15 frontend. Use the Node.js version in the repository's
`.nvmrc` and npm. See the [root README](../README.md) for backend and Docker setup.

From this directory:

```console
npm ci
npm start
```

Visit <http://localhost:4200/>. The default proxy forwards API and authentication
requests to the local backend on port 8000. `npm run serve:acc` and
`npm run serve:live` use the acceptance and production backend proxies.

`npm run build` produces the optimized frontend in `dist/` with asset URLs under
`/static/`, for the Docker Nginx image. `npm test` runs tests in watch mode;
`npm test -- --watch=false` runs once in headless Chrome. Set `CHROME_BIN` if Chrome is
not in the usual location. `npm run lint` runs the existing Angular ESLint rules.

Build, serve and test commands generate the ignored `src/environments/version.ts`
from the root package version and optional Git metadata. `BUILD_SHA` and
`BUILD_SOURCE_URL` can supply the commit and repository URL in Docker or archive
builds. The generator uses no third-party packages.

Use `npm run ng -- generate component NAME` for scaffolding and
`npm run i18n` to extract translation messages. Localized build configurations
are not defined; the removed locale commands referred to nonexistent targets.
