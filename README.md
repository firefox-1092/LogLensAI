# LogLens

**AI-Powered Application Log Analytics and Intelligent Error Analysis Platform**

LogLens turns raw application logs into structured, searchable evidence. It supports uploading `.log` and `.txt` files, parsing a documented timestamp/severity format, storing records in PostgreSQL, browsing them with severity and keyword filters, and reviewing deterministic per-dataset error analytics.

## Architecture

- **Frontend:** React, TypeScript, and Vite. The browser sends HTTP requests to FastAPI.
- **API:** FastAPI with Pydantic response schemas and SQLAlchemy ORM models.
- **Database:** PostgreSQL 16 in Docker Compose for local development. A named volume keeps data when the container stops.
- **Containerized application:** Docker Compose can also run the FastAPI backend and a static Nginx frontend. The frontend proxies API requests over the Compose network; the backend reaches PostgreSQL using the `db` service name.
- **Parser:** a small Python module extracts timestamps, supported severity levels, and messages. It retains unsupported non-empty lines as unparsed records.
- **Tests:** backend tests use an isolated in-memory SQLite database. They do not connect to or reset the development PostgreSQL database.
- **AI assistant:** FastAPI retrieves evidence from the selected PostgreSQL dataset and sends bounded, untrusted log context to the configured Groq or OpenRouter model. Responses include source references and report whether the provider confirmed normal completion.
- **Analytics:** FastAPI computes dataset-scoped severity counts, error/warning totals, normalized recurring-error patterns, and a timeline directly from stored entries. Analytics are deterministic and do not call an LLM.

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

Set a private local value for `POSTGRES_PASSWORD` in `.env`. Do not commit `.env` or share its contents. PostgreSQL uses `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD`; local backend development defaults to host `127.0.0.1` and `POSTGRES_HOST_PORT` 5433. Compose overrides the backend host/port to `db:5432`. SQLAlchemy builds the URL from separate values, so password characters do not need manual URL escaping. `LOG_LENS_MAX_UPLOAD_BYTES` defaults to 10 MiB. `LOG_LENS_CORS_ORIGINS` and `VITE_API_BASE_URL` configure browser communication for local development.

If you already have a local `.env` file, preserve its existing values and add only settings that are missing. Provider settings are:

```dotenv
POSTGRES_DB=loglens
POSTGRES_USER=loglens
POSTGRES_PASSWORD=<choose-a-private-local-password>
POSTGRES_HOST=127.0.0.1
POSTGRES_HOST_PORT=5433
LOG_LENS_MAX_UPLOAD_BYTES=10485760
GROQ_API_KEY=<your-private-groq-api-key>
GROQ_MODEL=openai/gpt-oss-20b
LLM_PROVIDER=groq
OPENROUTER_API_KEY=
OPENROUTER_MODEL=
```

The placeholder in the example above is explanatory; replace it with a local password. `.env.example` uses a placeholder only. Vite variables are public browser settings and must not contain secrets.

### AI provider setup

For Groq, create an API key in the [Groq console](https://console.groq.com/keys), then set `LLM_PROVIDER=groq`, `GROQ_API_KEY`, and `GROQ_MODEL` in the ignored root `.env`. The existing model default is `openai/gpt-oss-20b`; choose a model available to your Groq account.

For OpenRouter, create an API key in [OpenRouter settings](https://openrouter.ai/settings/keys), then set `LLM_PROVIDER=openrouter`, `OPENROUTER_API_KEY`, and `OPENROUTER_MODEL`. Select a model ID from [OpenRouter's model list](https://openrouter.ai/models); LogLens intentionally does not choose a default OpenRouter model. Some models have zero listed input/output pricing, but availability, free-tier terms, context limits and rate limits can change. Check the model listing and account terms before use.

The backend loads the root `.env` at startup. Provider keys remain backend-only and are never returned to the browser. In Compose, provider settings are passed to the backend container at runtime; they are not copied into either image, and the frontend build context does not include the root `.env`. To switch providers, stop the backend, change `LLM_PROVIDER` and the corresponding key/model settings in `.env`, then restart it. Do not remove the other provider's values if you want to switch back easily. Never commit `.env`. Sanitize sensitive log contents before sending relevant entries to a hosted provider.

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

## Run the full application with Docker Compose

This mode is separate from the local Python/Vite workflow above. Ensure the root `.env` has database settings that match the existing PostgreSQL volume. **Keep the same `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` that initialized that volume**; changing those environment values does not change the credentials stored in an already initialized database. Set the selected LLM provider key in `.env` only if you want AI chat enabled; uploads and analytics do not require it.

From the repository root, build and start all three services:

```bash
docker compose up --build -d
docker compose ps
```

Wait until `db` is healthy, then `backend` and `frontend` should report healthy. Open the frontend at `http://127.0.0.1:5173`. The backend is available at `http://127.0.0.1:8000`, with API documentation at `http://127.0.0.1:8000/docs`; its health endpoint is `http://127.0.0.1:8000/health`. The frontend also proxies `/health` and `/api/` to the backend on the internal Compose network.

View service logs without printing environment values:

```bash
docker compose logs -f backend frontend
docker compose logs -f db
```

Rebuild application images after code or dependency changes:

```bash
docker compose build backend frontend
docker compose up -d backend frontend
```

Stop services while retaining containers and the database volume:

```bash
docker compose stop
```

`docker compose down` also removes the containers and network but preserves the named `loglens_postgres_data` volume. Neither command deletes database records. **Never use `docker compose down -v` or volume-pruning commands as routine troubleshooting.** The existing PostgreSQL service name, host port mapping, volume name, and health check are retained.

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
| `GET /api/uploads/{upload_id}/entries` | Optional `page` (default 1), `page_size` (default 50, max 100), `severity`, `q`, and exact `line_number` | `items`, `page`, `page_size`, `total`, and `total_pages` |
| `GET /api/uploads/{upload_id}/analytics` | Dataset upload ID | Severity counts, error/warning totals, up to 10 recurring error patterns, and timestamped entry activity buckets |
| `POST /api/uploads/{upload_id}/ai/chat` | JSON body: `{"question":"Why did the database connection fail?"}` | Grounded `answer`, bounded `evidence` references, and `completion_status` (`complete` or `unknown`) |

After uploading a dataset, the page shows a deterministic overview of severity counts, errors, warnings, recurring error patterns, and entry activity over time. Pattern grouping is case-insensitive, collapses whitespace, and replaces timestamps, UUIDs, and valid IPv4 addresses; severity stays part of the pattern key, and numeric values such as HTTP status codes are preserved. The dashboard lists up to 10 patterns, ordered by occurrence count, with representative source line numbers.

Use the **Ask about these logs** panel for AI questions. Follow-up questions include at most the four most recent question/answer turns as context. The backend includes the complete dataset when it fits within the configured entry and evidence-context limits. Larger datasets use up to 100 keyword candidates and at most 12 evidence entries, each message capped at 1,200 characters. The prompt identifies whether evidence is complete or a subset. Log text is treated as untrusted evidence; the assistant is instructed to ignore embedded instructions, distinguish facts from hypotheses, and cite only supplied lines. These safeguards cannot guarantee that an LLM never makes a mistake; verify important conclusions against the displayed source entries.

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

AI provider requests are mocked in tests. The suite does not need real API keys and does not make live provider requests. A confirmed token-limit finish reason produces a clear incomplete-response error. If a provider omits its finish reason, the answer is returned with a “completion status unknown” notice instead of being labeled complete. Provider availability, model-specific output limits, account quotas and rate limits can affect live responses. Groq's and OpenRouter's limits and model availability vary by account and model; consult [Groq's API reference](https://console.groq.com/docs/api-reference) and [OpenRouter's model list](https://openrouter.ai/models) for current details.

## Continuous integration

The workflow in `.github/workflows/ci.yml` runs on pushes to `main` and pull requests targeting `main`. Its independent jobs install the locked backend/frontend dependencies, run the complete backend suite, and run the frontend TypeScript check and production build. The backend uses the existing isolated SQLite test setup; CI does not read `.env`, connect to PostgreSQL, or call Groq/OpenRouter. Dependency caches use the existing requirements and npm lock files. This repository is not deployed to a cloud provider by this workflow.

## Troubleshooting

- If Compose reports a port is already allocated, stop the local process using port 5173 or 8000 before starting the full Compose stack. The existing PostgreSQL host port remains configurable through `POSTGRES_HOST_PORT` and defaults to 5433.
- If `backend` does not become healthy, check `docker compose ps` and `docker compose logs backend db`. Confirm the `.env` credentials match those used when the existing persistent database was initialized. Do not reset the database or remove its volume to resolve an authentication error.
- If the frontend loads but API calls fail, inspect `docker compose logs frontend backend`; in Compose the frontend sends `/api/` and `/health` to Nginx, which proxies them to the backend service.
- For local development, confirm the backend is at `127.0.0.1:8000` and `VITE_API_BASE_URL` is unset or points to that address. Docker Compose does not require `VITE_API_BASE_URL` because it uses the same-origin Nginx proxy.
- AI requests require a valid selected provider key. Missing provider credentials do not prevent PostgreSQL-backed upload, browsing, or analytics.

## Current limitations

- Only the documented timestamp + severity + message format is parsed. Other formats and multiline stack-trace grouping are not yet supported.
- Data is stored in PostgreSQL; uploaded file bytes are not retained separately. There is no delete/export interface yet.
- SQLAlchemy `create_all` creates missing tables but does not migrate existing schemas.
- AI is currently keyword-retrieval question answering only. There is no dedicated whole-dataset summary endpoint, semantic retrieval, saved chat history, authentication, deployment, or CI/CD yet.
- Analytics group error-like entries (`ERROR`, `FATAL`, and `CRITICAL`) using simple normalization, not semantic similarity. Only the top 10 patterns are shown; the API reports the full unique and recurring pattern counts. Activity buckets use records with timestamps; unparsed lines are counted separately and do not contribute to timestamped activity.
- The selected hosted provider, its model availability and account rate limits affect assistant responses. Without valid credentials and model configuration for the selected provider, ordinary log upload and exploration continue to work, but AI requests return a configuration error.
