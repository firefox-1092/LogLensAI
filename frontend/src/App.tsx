import { useCallback, useEffect, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { askDatasetQuestion, checkHealth, fetchEntries, uploadLogFile } from './api';
import type { AIChatResponse, LogEntry, PaginatedEntries, UploadSummary } from './api';
import { parseAssistantMarkdown } from './markdown.mjs';
import type { InlineToken } from './markdown.mjs';

type ConnectionState = 'loading' | 'connected' | 'error';
const PAGE_SIZE = 25;

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTimestamp(timestamp: string | null): string {
  if (!timestamp) return '—';
  return timestamp.replace('T', ' ').slice(0, 19);
}

function renderInlineMarkdown(tokens: InlineToken[]): ReactNode[] {
  return tokens.map((token, index) => {
    if (token.type === 'strong') return <strong key={index}>{token.value}</strong>;
    if (token.type === 'emphasis') return <em key={index}>{token.value}</em>;
    if (token.type === 'code') return <code key={index}>{token.value}</code>;
    return token.value;
  });
}

function renderAssistantAnswer(answer: string): ReactNode {
  const blocks = parseAssistantMarkdown(answer).map((block, index) => {
    if (block.type === 'heading') {
      const heading = renderInlineMarkdown(block.tokens);
      if (block.level === 1) return <h1 key={index}>{heading}</h1>;
      if (block.level === 2) return <h2 key={index}>{heading}</h2>;
      return <h3 key={index}>{heading}</h3>;
    }
    if (block.type === 'paragraph') return <p key={index}>{renderInlineMarkdown(block.tokens)}</p>;
    const items = block.items.map((tokens, itemIndex) => <li key={itemIndex}>{renderInlineMarkdown(tokens)}</li>);
    return block.type === 'ordered-list' ? <ol key={index}>{items}</ol> : <ul key={index}>{items}</ul>;
  });
  return <div className="assistant-answer">{blocks}</div>;
}

export default function App() {
  const [connection, setConnection] = useState<ConnectionState>('loading');
  const [attempt, setAttempt] = useState(0);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [dataset, setDataset] = useState<UploadSummary | null>(null);
  const [entries, setEntries] = useState<PaginatedEntries | null>(null);
  const [entriesLoading, setEntriesLoading] = useState(false);
  const [entriesError, setEntriesError] = useState('');
  const [page, setPage] = useState(1);
  const [severity, setSeverity] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [assistantQuestion, setAssistantQuestion] = useState('');
  const [assistantLoading, setAssistantLoading] = useState(false);
  const [assistantError, setAssistantError] = useState('');
  const [assistantTurns, setAssistantTurns] = useState<Array<{ question: string; result: AIChatResponse }>>([]);

  const checkBackend = useCallback(async (signal: AbortSignal) => {
    setConnection('loading');
    try {
      await checkHealth(signal);
      setConnection('connected');
    } catch {
      if (!signal.aborted) setConnection('error');
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void checkBackend(controller.signal);
    return () => controller.abort();
  }, [attempt, checkBackend]);

  useEffect(() => {
    if (!dataset) return;
    const controller = new AbortController();
    setEntriesLoading(true);
    setEntriesError('');
    void fetchEntries(dataset.id, { page, pageSize: PAGE_SIZE, severity, query: searchTerm }, controller.signal)
      .then(setEntries)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setEntriesError(error instanceof Error ? error.message : 'Could not load log entries.');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setEntriesLoading(false);
      });
    return () => controller.abort();
  }, [dataset, page, searchTerm, severity]);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedFile) return;
    setUploading(true);
    setUploadError('');
    try {
      const result = await uploadLogFile(selectedFile);
      setDataset(result);
      setEntries(null);
      setSeverity('');
      setSearchInput('');
      setSearchTerm('');
      setPage(1);
      setAssistantTurns([]);
      setAssistantError('');
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'The file could not be uploaded.');
    } finally {
      setUploading(false);
    }
  }

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(1);
    setSearchTerm(searchInput.trim());
  }

  async function handleAssistantQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dataset || !assistantQuestion.trim()) return;
    const question = assistantQuestion.trim();
    setAssistantLoading(true);
    setAssistantError('');
    try {
      const history = assistantTurns.slice(-4).map((turn) => ({
        question: turn.question,
        answer: turn.result.answer,
      }));
      const result = await askDatasetQuestion(dataset.id, question, history);
      setAssistantTurns((turns) => [...turns, { question, result }]);
      setAssistantQuestion('');
    } catch (error) {
      setAssistantError(error instanceof Error ? error.message : 'The AI assistant could not answer right now.');
    } finally {
      setAssistantLoading(false);
    }
  }

  return (
    <main className="page-shell">
      <header className="topbar">
        <a className="brand" href="#home" aria-label="LogLens home">
          <span className="brand-mark" aria-hidden="true"><span /><span /><span /></span>
          <span>LogLens</span>
        </a>
        <span className="phase-label">LOCAL PREVIEW <i /></span>
      </header>

      <section className="hero" id="home">
        <div className="eyebrow"><span className="eyebrow-line" /> APPLICATION LOG INTELLIGENCE</div>
        <h1>Make sense of<br /><span>what happened.</span></h1>
        <p className="intro">Turn application logs into searchable evidence. Upload a file to inspect its entries and spot important events.</p>

        <section className={`connection-card ${connection}`} aria-live="polite" aria-busy={connection === 'loading'}>
          <div className="connection-icon" aria-hidden="true">
            {connection === 'loading' ? <span className="spinner" /> : connection === 'connected' ? <span className="check">✓</span> : <span className="warning">!</span>}
          </div>
          <div className="connection-copy">
            <div className="connection-heading">
              <h2>{connection === 'loading' ? 'Checking connection' : connection === 'connected' ? 'Backend connected' : 'Backend unavailable'}</h2>
              <span className={`status-pill ${connection}`}>{connection === 'loading' ? 'CONNECTING' : connection === 'connected' ? 'ONLINE' : 'OFFLINE'}</span>
            </div>
            <p>{connection === 'loading' ? 'Contacting the local LogLens API…' : connection === 'connected' ? 'The API is responding and ready for the next step.' : 'Could not reach the API. Start the backend, then try again.'}</p>
            {connection === 'error' && <button className="retry-button" onClick={() => setAttempt((value) => value + 1)}>Retry connection <span aria-hidden="true">↻</span></button>}
          </div>
        </section>

      </section>

      <section className="workspace" aria-label="Log file explorer">
        <div className="section-heading">
          <div><div className="eyebrow"><span className="eyebrow-line" /> LOG EXPLORER</div><h2>Start with a log file</h2></div>
          <span className="local-note">Files stay in your local LogLens database</span>
        </div>

        <form className="upload-panel" onSubmit={handleUpload}>
          <label className="file-picker">
            <span className="file-picker-icon" aria-hidden="true">↑</span>
            <span><strong>Choose a log file</strong><small>Supported formats: .log and .txt</small></span>
            <input
              type="file"
              accept=".log,.txt,text/plain"
              onChange={(event) => {
                setSelectedFile(event.target.files?.[0] ?? null);
                setUploadError('');
              }}
            />
          </label>
          {selectedFile && (
            <div className="selected-file"><span className="file-dot" />
              <span className="selected-name">{selectedFile.name}</span><span>{formatBytes(selectedFile.size)}</span>
            </div>
          )}
          <button className="upload-button" type="submit" disabled={!selectedFile || uploading || connection !== 'connected'}>
            {uploading ? 'Uploading and parsing…' : 'Upload and inspect'} <span aria-hidden="true">→</span>
          </button>
          {uploadError && <p className="form-error" role="alert">{uploadError}</p>}
          <p className="privacy-note">Log files may contain passwords, API keys, tokens, or personal information. Sanitize sensitive data before uploading.</p>
        </form>

        {!dataset ? (
          <div className="empty-state"><span className="empty-mark" aria-hidden="true">⌁</span><strong>Your log entries will appear here</strong><p>Choose a file above to parse and explore its contents.</p></div>
        ) : (
          <>
            <div className="dataset-summary">
              <div className="dataset-title"><span className="dataset-file-icon" aria-hidden="true">≡</span><div><strong>{dataset.filename}</strong><small>{formatBytes(dataset.file_size_bytes)} · Uploaded {new Date(dataset.uploaded_at).toLocaleString()}</small></div></div>
              <div className="metric"><strong>{dataset.total_entries}</strong><small>ENTRIES</small></div>
              <div className="metric success"><strong>{dataset.parsed_entries}</strong><small>PARSED</small></div>
              <div className="metric muted"><strong>{dataset.unparsed_entries}</strong><small>UNPARSED</small></div>
            </div>

            <section className="assistant-panel" aria-label="AI log assistant">
              <div className="assistant-heading">
                <div><div className="eyebrow"><span className="eyebrow-line" /> AI ASSISTANT</div><h2>Ask about these logs</h2></div>
                <span className="assistant-note">Answers cite retrieved log lines</span>
              </div>
              {assistantTurns.map((turn, index) => (
                <article className="assistant-turn" key={`${index}-${turn.question}`}>
                  <p className="assistant-question">{turn.question}</p>
                  {renderAssistantAnswer(turn.result.answer)}
                  {turn.result.completion_status === 'unknown' && <p className="assistant-status">The provider did not report whether generation ended normally. Review the answer against the supporting entries.</p>}
                  {turn.result.evidence.length > 0 && <div className="evidence-list">
                    <strong>{turn.result.cited_evidence.length > 0 ? 'Supporting entries' : 'Available context'}</strong>
                    {(turn.result.cited_evidence.length > 0 ? turn.result.cited_evidence : turn.result.evidence).map((item) => <div className="evidence-item" key={item.id}>
                      <span>Line {item.line_number}{item.severity ? ` · ${item.severity}` : ''}{!item.parsed ? ' · UNPARSED' : ''}</span><p>{!item.parsed ? item.raw_line ?? item.message : item.message}</p>
                      {!item.parsed && <small>Original text retained; timestamp, severity, and structured meaning could not be reliably extracted.</small>}
                    </div>)}
                  </div>}
                </article>
              ))}
              <form className="assistant-form" onSubmit={handleAssistantQuestion}>
                <label className="sr-only" htmlFor="assistant-question">Ask a question about this dataset</label>
                <input id="assistant-question" maxLength={1000} value={assistantQuestion} onChange={(event) => setAssistantQuestion(event.target.value)} placeholder="Ask about errors, events, or what to investigate…" />
                <button type="submit" disabled={!assistantQuestion.trim() || assistantLoading}>
                  {assistantLoading ? 'Thinking…' : 'Ask LogLens'}
                </button>
              </form>
              {assistantLoading && <p className="assistant-status" role="status"><span className="spinner" /> Searching relevant entries and asking the configured model…</p>}
              {assistantError && <p className="form-error" role="alert">{assistantError}</p>}
            </section>

            <div className="entries-heading"><div><div className="eyebrow"><span className="eyebrow-line" /> SOURCE RECORDS</div><h2>Log entries</h2></div><span className="entry-count">{entries?.total ?? '—'} matching records</span></div>
            <div className="filters">
              <form className="search-form" onSubmit={handleSearch}>
                <span aria-hidden="true">⌕</span><input aria-label="Search log messages" maxLength={200} value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="Search messages…" />
                <button type="submit">Search</button>
              </form>
              <label className="severity-control">Severity
                <select value={severity} onChange={(event) => { setSeverity(event.target.value); setPage(1); }}>
                  <option value="">All levels</option>
                  <option>TRACE</option><option>DEBUG</option><option>INFO</option><option>WARN</option><option>ERROR</option><option>FATAL</option><option>CRITICAL</option>
                </select>
              </label>
            </div>

            {entriesError && <p className="form-error" role="alert">{entriesError}</p>}
            <div className="table-wrap" aria-busy={entriesLoading}>
              {entriesLoading ? <div className="table-message"><span className="spinner" /> Loading log entries…</div> : entries?.items.length ? (
                <table>
                  <thead><tr><th>LINE</th><th>TIME</th><th>LEVEL</th><th>MESSAGE</th></tr></thead>
                  <tbody>{entries.items.map((entry: LogEntry) => <tr key={entry.id}>
                    <td className="line-number">{entry.line_number}</td>
                    <td className="time-cell">{formatTimestamp(entry.timestamp)}</td>
                    <td>{entry.severity ? <span className={`severity-badge ${entry.severity.toLowerCase()}`}>{entry.severity}</span> : <span className="unparsed-badge">UNPARSED</span>}</td>
                    <td className="message-cell"><span>{entry.message}</span></td>
                  </tr>)}</tbody>
                </table>
              ) : <div className="table-message">No entries match these filters.</div>}
            </div>
            <div className="pagination">
              <span>Page {page} of {Math.max(entries?.total_pages ?? 0, 1)}</span>
              <div><button type="button" onClick={() => setPage((value) => value - 1)} disabled={page <= 1 || entriesLoading}>Previous</button>
                <button type="button" onClick={() => setPage((value) => value + 1)} disabled={!entries || page >= entries.total_pages || entriesLoading}>Next</button></div>
            </div>
          </>
        )}
      </section>

      <footer><span>LOG LENS <span className="footer-dot">·</span> PHASE 2</span><span>Built for clearer debugging</span></footer>
    </main>
  );
}
