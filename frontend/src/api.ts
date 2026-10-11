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
  options: { page: number; pageSize: number; severity: string; query: string },
  signal?: AbortSignal,
): Promise<PaginatedEntries> {
  const params = new URLSearchParams({ page: String(options.page), page_size: String(options.pageSize) });
  if (options.severity) params.set('severity', options.severity);
  if (options.query) params.set('q', options.query);
  const response = await fetch(`${apiBaseUrl}/api/uploads/${uploadId}/entries?${params}`, { signal });
  return readResponse<PaginatedEntries>(response);
}
