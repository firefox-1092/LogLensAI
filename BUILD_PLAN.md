# LogLens Build Plan

This plan is intentionally staged. Finish and verify one milestone before moving to the next. Do not attempt to implement the entire roadmap in one pass.

## Phase 0 — Read-only reconnaissance and decisions
- Inspect repository contents, Git status/branch, installed runtimes, existing frontend/backend, environment files, and any existing tests.
- Identify whether the repository is empty or already contains code. Never overwrite useful files.
- Check available Python/Node/PostgreSQL/Docker tooling without installing things automatically.
- Compare repository reality with `PROJECT_SPEC.md`.
- Report proposed directory structure, required decisions, likely blockers, commands to run, and the smallest next milestone.
- Do not modify files until the user approves the findings and first implementation plan.

## Phase 1 — Minimal project foundation
- Agree on the confirmed stack and local database strategy.
- Establish frontend/backend structure, dependency manifests, `.gitignore`, `.env.example`, and starter README.
- Add a health endpoint and a minimal React page that can call it.
- Verify frontend and backend start locally.
- If PostgreSQL/Docker setup is not available, explain options and get approval before choosing a temporary alternative.

## Phase 2 — Log parsing and persistence (implemented and verified with PostgreSQL)
- Define SQLAlchemy dataset/log-entry models and a local table setup path using `Base.metadata.create_all`.
- Add PostgreSQL Compose service with a named volume, health check, and localhost-only port 5433.
- Implement bounded `.log`/`.txt` upload validation, UTF-8 decoding, parsing, and parsing summary.
- Preserve raw lines and original line numbers; retain unsupported records as unparsed.
- Persist records and implement dataset listing plus filtered, paginated entry retrieval.
- Add an isolated in-memory SQLite test strategy so tests cannot reset development PostgreSQL data.
- Add a synthetic sample log and document local database configuration and run commands.
- [x] Parser, validation, upload/API, persistence, health, filtering, pagination, and frontend build checks pass against the isolated test setup.
- [x] Start PostgreSQL through Compose and verify a live PostgreSQL upload.

## Phase 3 — Deterministic log explorer and analytics (implemented)
- Implement severity/text/service/time filters supported by the parser.
- Implement deterministic counts and repeated-message summaries.
- Build React upload flow, metrics, log table, filters, loading/error/empty states.
- Verify frontend API contracts and test the principal journey.

## Phase 4 — Grounded AI features
- Define a provider-neutral LLM service interface and backend-only provider configuration.
- Implement retrieval of a bounded set of relevant records.
- Add summary and question-answer endpoints.
- Structure responses into summary, observations/evidence, possible explanations, suggested checks, and limitations.
- Include source line numbers/record IDs when available.
- Treat log content as untrusted data; defend against instructions embedded in logs.
- Mock LLM calls in tests and add graceful handling of unavailable/misconfigured providers.
- Never make the core application unusable if the external LLM is unavailable; display a clear error and keep non-AI features working.
- [x] Implemented provider-neutral dataset question answering with Groq as the default, configurable OpenRouter support, bounded evidence retrieval, source references, safe provider errors, mocked provider tests, and a dataset-scoped frontend assistant. The UI reports when completion metadata is unavailable. No summary endpoint or semantic retrieval is included.

## Phase 5 — Demo readiness
- Add optional saved reports if the essential workflow is stable.
- Create a synthetic sample log file with varied severities and repeated errors.
- Run backend tests and frontend TypeScript/build checks.
- Complete README, endpoint documentation, known limitations, screenshots, and an architecture diagram.
- Walk through the entire demo from a clean setup.

## Phase 6 — Post-submission portfolio expansion
- Improve normalized-message grouping and evaluate embedding-based semantic grouping.
- Add authentication/authorization if warranted.
- Dockerize the full application and document local orchestration.
- Add GitHub Actions for tests and build checks.
- Deploy to AWS EC2 behind Nginx/HTTPS when ready.
- Add CloudWatch logs/metrics/alarms and deployment documentation.
- Consider S3, more log formats, or automated ingestion only if justified.

## Definition of done for each phase
- Code changes are small and reviewable.
- Relevant tests/checks are run and their exact results reported.
- No secrets or private logs are committed.
- Documentation is updated.
- `git diff` is reviewed for accidental edits.
- The user understands the key design choices before proceeding.
