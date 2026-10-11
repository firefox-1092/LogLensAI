# LogLens

**AI-Powered Application Log Analytics and Intelligent Error Analysis Platform**

LogLens will help developers turn raw application logs into structured, searchable evidence. This Phase 1 foundation contains a small React interface and a FastAPI health endpoint; log analysis features are not implemented yet.

## Prerequisites

- Python 3.10 or newer
- Node.js and npm
- Git Bash on Windows

## Setup

Open Git Bash in the repository directory. Copy the example environment file if you want to override the local defaults:

```bash
cp .env.example .env
```

Create and activate a Python virtual environment, then install the backend dependencies (including the small test dependencies):

```bash
python -m venv backend/.venv
source backend/.venv/Scripts/activate
python -m pip install -r backend/requirements-dev.txt
```

Install the frontend packages:

```bash
cd frontend
npm install
cd ..
```

## Run the backend

From the repository root, with the virtual environment active:

```bash
python -m uvicorn app.main:app --reload --app-dir backend
```

The API listens at `http://127.0.0.1:8000`. Check it directly at `http://127.0.0.1:8000/health`; the response should be `{"status":"healthy"}`. Interactive API documentation is available at `http://127.0.0.1:8000/docs`.

## Run the frontend

In a second Git Bash terminal, from the repository root:

```bash
cd frontend
npm run dev
```

Open the local address Vite prints (by default, `http://127.0.0.1:5173`). The page checks the backend when it loads and displays a connecting, online, or offline state. If the backend was stopped, start it and select **Retry connection**.

The frontend calls `GET http://127.0.0.1:8000/health`. The API allows the local Vite origins `http://localhost:5173` and `http://127.0.0.1:5173` through CORS. Set `VITE_API_BASE_URL` to change the frontend endpoint and `LOG_LENS_CORS_ORIGINS` to change the allowed browser origins in the root `.env` file. The backend reads that file at startup and Vite reads its public `VITE_` setting. Restart the relevant development server after changing environment variables. Vite variables are public browser configuration; never put secrets in them.

## Run the backend test

From the repository root with the virtual environment active:

```bash
python -m pytest backend/tests
```

## Phase 1 limitations

- The API only reports process health. It does not yet validate database connectivity.
- There is no file upload, log parsing, PostgreSQL persistence, search, filtering, or dashboard analytics.
- There is no LLM integration, AI summary, question-answering, or saved analysis.
- There is no authentication, Docker setup, or cloud deployment.
- The interface is an initial connection-status page, not the complete LogLens dashboard.
