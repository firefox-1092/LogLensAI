# LogLens

**AI-Powered Application Log Analytics and Intelligent Error Analysis Platform**

LogLens turns raw application logs into structured, searchable evidence. Phase 2 supports uploading `.log` and `.txt` files, parsing a documented timestamp/severity format, storing records in PostgreSQL, and browsing them with severity and keyword filters.

## Architecture

- **Frontend:** React, TypeScript, and Vite. The browser sends HTTP requests to FastAPI.
- **API:** FastAPI with Pydantic response schemas and SQLAlchemy ORM models.
- **Database:** PostgreSQL 16 in Docker Compose for local development. A named volume keeps data when the container stops.
- **Parser:** a small Python module extracts timestamps, supported severity levels, and messages. It retains unsupported non-empty lines as unparsed records.
- **Tests:** backend tests use an isolated in-memory SQLite database. They do not connect to or reset the development PostgreSQL database.

The API creates missing tables at startup with SQLAlchemy `create_all`. A schema migration tool is not part of this phase.

## Requirements

- Python 3.10 or newer
- Node.js and npm
- Git Bash for Windows
- Docker Desktop with Docker Compose

## Environment configuration

The repository has a root `.env.example`. On a fresh checkout, create `.env` only if it does not already exist:

```bash
if [ ! -f .env ]; then cp .env.example .env; fi
```

Set a private local value for `POSTGRES_PASSWORD` in `.env`. Do not commit `.env` or share its contents. PostgreSQL uses `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD`; the backend connects to `127.0.0.1` using `POSTGRES_HOST_PORT` (default `5433`). `LOG_LENS_MAX_UPLOAD_BYTES` defaults to 10 MiB. `LOG_LENS_CORS_ORIGINS` and `VITE_API_BASE_URL` configure browser communication.

If you already have a local `.env` file (for example, from Phase 1), preserve it and add these missing settings locally:

```dotenv
POSTGRES_DB=loglens
POSTGRES_USER=loglens
POSTGRES_PASSWORD=<choose-a-private-local-password>
POSTGRES_HOST_PORT=5433
LOG_LENS_MAX_UPLOAD_BYTES=10485760
```

The placeholder in the example above is explanatory; replace it with a local password. `.env.example` uses a placeholder only. Vite variables are public browser settings and must not contain secrets.

## Setup in Git Bash

Open Git Bash at the repository root. After configuring `.env`, create the Python environment and install dependencies:

```bash
python -m venv backend/.venv
source backend/.venv/Scripts/activate
python -m pip install -r backend/requirements-dev.txt
cd frontend
npm install
cd ..
```

## Start and stop PostgreSQL

From the repository root, start the database and wait for its health check:

```bash
docker compose up -d db
docker compose ps
```

The database port is bound to `127.0.0.1:5433` by default, reducing conflicts with a local PostgreSQL server on port 5432. The named `loglens_postgres_data` volume persists records across container stops.

Stop the container without deleting database files:

```bash
docker compose stop db
```

To remove the stopped container and Compose network while retaining the named data volume, use `docker compose down`. Do not use `docker compose down -v` unless you intentionally want to delete the database volume.

## Start the backend

In a Git Bash terminal from the repository root, with the virtual environment active:

```bash
source backend/.venv/Scripts/activate
python -m uvicorn app.main:app --reload --app-dir backend
```

The backend listens on `http://127.0.0.1:8000`. `GET /health` returns `{"status":"healthy"}` after the database is available and the application has initialized its tables. Interactive API documentation is at `http://127.0.0.1:8000/docs`.

## Start the frontend

In a second Git Bash terminal:

```bash
cd frontend
npm run dev
```

Open `http://127.0.0.1:5173`. The existing backend connection indicator remains. Select a `.log` or `.txt` file, review its name and size, then choose **Upload and inspect**. After upload, the page shows parsing counts, entries, severity filtering, case-insensitive message search, and pagination. The sample file is `backend/sample_logs/sample.log`.

### API endpoints

| Method and path | Request | Response |
| --- | --- | --- |
| `GET /health` | None | `{"status":"healthy"}` |
| `POST /api/uploads` | Multipart form field named `file` | Upload ID, filename, byte size, and parsed/unparsed counts; HTTP 201 |
| `GET /api/uploads?limit=20` | Optional recent-list limit, 1–100 | Recent upload records and their counts |
| `GET /api/uploads/{upload_id}/entries` | Optional `page` (default 1), `page_size` (default 50, max 100), `severity`, and `q` | `items`, `page`, `page_size`, `total`, and `total_pages` |

Upload a sample with Git Bash `curl`:

```bash
curl -F "file=@backend/sample_logs/sample.log" http://127.0.0.1:8000/api/uploads
```

Use the returned upload `id` to inspect a filtered page:

```bash
curl -G "http://127.0.0.1:8000/api/uploads/UPLOAD_ID/entries" \
  --data-urlencode "severity=ERROR" \
  --data-urlencode "q=timeout" \
  --data-urlencode "page=1" \
  --data-urlencode "page_size=25"
```

`WARNING` is normalized to `WARN` for both stored records and filtering. Unsupported severity values and invalid pagination receive HTTP 422; a missing upload ID receives 404. Unsupported extensions, empty files, and invalid UTF-8 receive 400; files over the configured size receive 413. Database errors return a generic 503 response without SQL details.

Uploads accept UTF-8 text files with `.log` or `.txt` suffixes, up to the configured size. Empty files and invalid UTF-8 are rejected. Blank lines are skipped; each non-empty line keeps its physical source line number. Records outside the supported format remain available as raw, unparsed entries. Uploaded contents are never executed. Sanitize logs before uploading because they may contain passwords, tokens, personal data, or other secrets.

## Tests and frontend build

With the Python environment active, from the repository root:

```bash
python -m pytest backend/tests
```

Build the frontend from `frontend`:

```bash
npm run build
```

Tests use their own in-memory SQLite database. They exercise persistence and API behavior without modifying the Compose PostgreSQL volume.

## Current limitations

- Only the documented timestamp + severity + message format is parsed. Other formats and multiline stack-trace grouping are not yet supported.
- Data is stored in PostgreSQL; uploaded file bytes are not retained separately. There is no delete/export interface yet.
- SQLAlchemy `create_all` creates missing tables but does not migrate existing schemas.
- There is no LLM summary or chat, dashboard analytics, authentication, deployment, or CI/CD yet.
