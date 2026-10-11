const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

export type UploadSummary = {
  id: string;
  filename: string;
  uploaded_at: string;
  file_size_bytes: number;
  total_entries: number;
  parsed_entries: number;
  unparsed_entries: number;
};

export type LogEntry = {
  id: string;
  dataset_id: string;
  line_number: number;
  timestamp: string | null;
  severity: string | null;
  message: string;
  raw_line: string;
  parsed: boolean;
};

export type PaginatedEntries = {
  items: LogEntry[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
};

export type AnalyticsSeverity = 'TRACE' | 'DEBUG' | 'INFO' | 'WARN' | 'ERROR' | 'FATAL' | 'CRITICAL';

export type ErrorPattern = {
  fingerprint: string;
  severity: string;
  representative_message: string;
  occurrences: number;
  recurring: boolean;
  first_timestamp: string | null;
  last_timestamp: string | null;
  representative_line_numbers: number[];
  distinct_message_count: number;
};

export type DatasetAnalytics = {
  total_entries: number;
  parsed_entries: number;
  unparsed_entries: number;
  error_count: number;
  warning_count: number;
  unique_error_patterns: number;
  recurring_error_patterns: number;
  severity_counts: Record<AnalyticsSeverity, number>;
  error_patterns: ErrorPattern[];
  timeline: {
    bucket_unit: 'minute' | 'hour' | 'day' | 'week' | 'none';
    bucket_interval: number;
    buckets: Array<{ timestamp: string; entries: number }>;
  };
};

export type EvidenceReference = {
  id: string;
  line_number: number;
  timestamp: string | null;
  severity: string | null;
  message: string;
  raw_line: string | null;
  parsed: boolean;
};

export type AIChatResponse = {
  answer: string;
  evidence: EvidenceReference[];
  cited_evidence: EvidenceReference[];
  completion_status: 'complete' | 'unknown';
};

export type AIChatHistoryTurn = {
  question: string;
  answer: string;
};

async function readResponse<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body && typeof body.detail === 'string' ? body.detail : 'The request could not be completed.';
    throw new Error(detail);
  }
  return body as T;
}

export async function checkHealth(signal?: AbortSignal): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/health`, { signal });
  const result = await readResponse<{ status: string }>(response);
  if (result.status !== 'healthy') throw new Error('The backend health check did not pass.');
}

export async function uploadLogFile(file: File): Promise<UploadSummary> {
  const formData = new FormData();
  formData.append('file', file);
  const response = await fetch(`${apiBaseUrl}/api/uploads`, { method: 'POST', body: formData });
  return readResponse<UploadSummary>(response);
}

export async function fetchEntries(
  uploadId: string,
  options: { page: number; pageSize: number; severity: string; query: string; lineNumber?: number | null },
  signal?: AbortSignal,
): Promise<PaginatedEntries> {
  const params = new URLSearchParams({ page: String(options.page), page_size: String(options.pageSize) });
  if (options.severity) params.set('severity', options.severity);
  if (options.query) params.set('q', options.query);
  if (options.lineNumber) params.set('line_number', String(options.lineNumber));
  const response = await fetch(`${apiBaseUrl}/api/uploads/${uploadId}/entries?${params}`, { signal });
  return readResponse<PaginatedEntries>(response);
}

export async function fetchDatasetAnalytics(uploadId: string, signal?: AbortSignal): Promise<DatasetAnalytics> {
  const response = await fetch(`${apiBaseUrl}/api/uploads/${uploadId}/analytics`, { signal });
  return readResponse<DatasetAnalytics>(response);
}

export async function askDatasetQuestion(
  uploadId: string,
  question: string,
  history: AIChatHistoryTurn[] = [],
): Promise<AIChatResponse> {
  const response = await fetch(`${apiBaseUrl}/api/uploads/${uploadId}/ai/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, history: history.slice(-4) }),
  });
  return readResponse<AIChatResponse>(response);
}
