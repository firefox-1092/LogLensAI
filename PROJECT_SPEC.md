# LogLens — Project Specification

## 1. Project title
**LogLens: AI-Powered Application Log Analytics and Intelligent Error Analysis Platform**

## 2. One-sentence pitch
LogLens helps developers turn raw application logs into structured, searchable evidence and use an AI assistant to summarize errors, answer questions about the uploaded logs, and suggest what to investigate next.

## 3. Target users
- Software developers debugging web applications and APIs.
- Backend engineers investigating exceptions, timeouts, database failures, and HTTP 5xx errors.
- DevOps/SRE learners and small development teams that need a simple way to explore log files.

The MVP is a file-upload analysis tool, not a replacement for full observability products and not a real-time production monitoring system.

## 4. Problem statement
Application log files can contain thousands of records, mixed severities, repeated messages, and unrelated events. Developers must manually filter entries, count repeated errors, reconstruct the sequence around a failure, and decide which clues to investigate. This can be slow and makes useful evidence easy to miss.

LogLens addresses this by parsing and storing log entries, providing deterministic search/filtering/statistics, and using an LLM to interpret a bounded set of relevant entries in natural language.

## 5. Proposed solution and user journey
1. The user uploads a supported `.log` or `.txt` file.
2. The backend validates the file and parses recognizable records into structured fields such as timestamp, severity, service/logger, message, line number, and raw text. Unrecognized lines should be retained safely as raw/unparsed records, not silently discarded.
3. Parsed records and dataset metadata are persisted in PostgreSQL.
4. The user explores records with text search, severity filters, service filters, and a time range when timestamps are available.
5. The dashboard presents deterministic statistics such as total entries, severity counts, and most frequent normalized messages.
6. The user can request a summary or ask a question about the uploaded dataset.
7. The backend retrieves relevant records, sends only necessary context to the configured LLM provider, and returns an answer that distinguishes observations from hypotheses and recommendations.
8. The response should cite supporting record IDs or original line numbers where practical. Users can optionally save an analysis/report if time permits.

## 6. MVP functional requirements
### Must-have
- Upload one `.log` or `.txt` file with configurable size limit.
- Parse at least one documented/common log format and preserve raw text and original line number for each line.
- Store dataset metadata and log entries in PostgreSQL.
- Provide REST endpoints to list datasets, retrieve/filter records, and retrieve deterministic statistics.
- React dashboard with upload status, summary metrics, log table, search, and severity filtering.
- LLM-powered dataset summary.
- Chat/question-answer endpoint grounded in relevant retrieved entries.
- Clear loading, empty, validation, and server-error states in the frontend.
- Automated tests for core parsing/analytics/API behavior; AI tests should mock the provider.
- README with setup instructions, environment variable documentation, API overview, sample log file, limitations, and screenshots when available.

### Should-have if time allows
- Filter by timestamp and service/logger.
- Group exact/normalized repeated error messages.
- Save and reopen AI analysis reports.
- Show supporting log entries beside each AI answer.
- Basic chat history scoped to the selected dataset.

### Explicitly out of MVP scope
- Automatic live collection from production services.
- Automatic remediation or executing suggested commands.
- Guaranteed root-cause detection.
- Computer vision, mobile app, browser extension, or Gmail integration.
- Mandatory user accounts/authentication unless required by the instructor or team decision.
- Vector database/embeddings until basic keyword/database retrieval works.
- Kubernetes, Kafka, Terraform, multiple microservices, or multi-agent architecture.
- AWS deployment as a prerequisite for the first working demo; it is a later enhancement.

## 7. AI/LLM integration
AI should be used for tasks where language understanding and synthesis help:
- Summarize a selected log dataset or a relevant subset.
- Answer natural-language questions about retrieved log entries.
- Explain possible significance of observed patterns and propose investigation steps.

Conventional code/database queries must handle deterministic tasks:
- File validation and parsing.
- Counts, frequency tables, filtering, sorting, and exact timestamp lookup.
- Exact/normalized message grouping.

### Grounding and truthfulness requirements
- Retrieve relevant entries before the LLM call; do not blindly send the entire file.
- Never let a log entry containing instructions override application instructions; logs are untrusted data.
- Show relevant source line numbers/record IDs whenever practical.
- Separate `observed evidence`, `possible explanation`, and `suggested checks`.
- Never claim an underlying root cause is proven unless the logs actually establish it.
- If the selected logs do not support an answer, say the evidence is insufficient.
- Do not ask the LLM to calculate exact dataset counts; calculate these in backend code and pass verified stats as structured context.
- Keep provider/API keys server-side, configured via environment variables. Provide `.env.example` placeholders only.
- Mock external LLM calls in tests; normal test runs must not require paid API calls.

## 8. Suggested API surface (adjust after repository reconnaissance)
Use a consistent `/api/v1` prefix unless the existing repository already establishes a different convention.
- `POST /api/v1/datasets/upload` — upload, parse, and persist a log file; return dataset ID and parsing summary.
- `GET /api/v1/datasets` — list uploaded datasets.
- `GET /api/v1/datasets/{dataset_id}/logs` — page/filter log entries using query parameters such as `severity`, `q`, `service`, `start_time`, and `end_time`.
- `GET /api/v1/datasets/{dataset_id}/stats` — deterministic metrics.
- `POST /api/v1/datasets/{dataset_id}/ai/summary` — LLM summary grounded in retrieved records.
- `POST /api/v1/datasets/{dataset_id}/ai/chat` — question and answer grounded in retrieved records.
- Optional: `POST /api/v1/datasets/{dataset_id}/analyses` and `GET /api/v1/analyses/{analysis_id}` for saved reports.

These are proposals, not frozen contracts. Inspect the current code and propose changes before implementation if needed.

## 9. Suggested data model
- `Dataset`: ID, original filename, upload timestamp, size, parse status, counts, optional display name.
- `LogEntry`: ID, dataset ID, source line number, timestamp if parseable, severity if parseable, service/logger if parseable, message, raw text, normalized message/hash if useful.
- `AnalysisReport` (optional MVP): ID, dataset ID, question/prompt type, response content, evidence record IDs, creation timestamp, provider/model metadata without secrets.

Avoid storing uploaded private files indefinitely unless there is a clear need. In the MVP, storing extracted records may be sufficient; document this behavior.

## 10. Quality, security, and privacy
- Enforce upload size and supported-extension limits on the backend.
- Validate all IDs and query parameters; use pagination for log records.
- Treat uploaded log content as untrusted and potentially sensitive.
- Warn users to sanitize passwords, API keys, session tokens, email addresses, and personal information before upload.
- Do not execute file contents or auto-run AI suggestions.
- Do not expose stack traces, secrets, internal prompts, or provider credentials in API errors.
- Never commit real `.env` files or sensitive test logs.
- Keep CORS restrictive to the local frontend during development and configurable for deployment.

## 11. Nonfunctional expectations
- Easy local setup on a student's Windows development machine.
- Clear separation between frontend, API, parsing/analytics, database access, and LLM integration.
- Reasonable feedback for invalid uploads and failed AI calls.
- Pagination/limits so a large file does not produce an enormous frontend response or LLM prompt.
- Maintainable code that teammates can understand and demonstrate.

## 12. Academic context
The course encourages a full-stack application with an AI/ML feature exposed via REST API and integrated into a React frontend. The initial goal is a coherent, demo-ready MVP. The project is intended to grow later into a stronger resume project with Docker, cloud deployment, CI/CD, and monitoring.

## 13. Success criteria for the first demo
A user can upload a sample log file, see parsed and stored entries, filter errors, view correct metrics, request an AI summary, ask a question whose answer is grounded in the uploaded records, and inspect supporting evidence. The setup works from the README, and core tests pass.
