import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { askDatasetQuestion, checkHealth, deleteSourceContext, fetchDatasetAnalytics, fetchEntries, fetchSourceContextStatus, investigateErrorPattern, uploadLogFile, uploadSourceContext } from './api';
import type { AIChatResponse, DatasetAnalytics, EvidenceReference, InvestigationWorkflow, LogEntry, PaginatedEntries, SourceContextSummary, UploadSummary } from './api';
import { parseAssistantMarkdown } from './markdown.mjs';
import type { InlineToken } from './markdown.mjs';
import { getCitedLineSegments, getTimelineBarHeight, selectTimelineLabelIndices } from './presentation.mjs';

type ConnectionState = 'loading' | 'connected' | 'error';
const PAGE_SIZE = 25;
const SEVERITY_LEVELS = ['TRACE', 'DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL', 'CRITICAL'] as const;

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTimestamp(timestamp: string | null): string {
  if (!timestamp) return '—';
  return timestamp.replace('T', ' ').slice(0, 19);
}

function formatTimelineLabel(timestamp: string, unit: DatasetAnalytics['timeline']['bucket_unit']): string {
  const value = formatTimestamp(timestamp);
  if (unit === 'minute') return value.slice(11, 16);
  if (unit === 'hour') return value.slice(5, 16);
  return value.slice(0, 10);
}

function renderInlineMarkdown(
  tokens: InlineToken[],
  citedLines: Set<number>,
  onCitation: (lineNumber: number) => void,
): ReactNode[] {
  return tokens.flatMap((token, tokenIndex) => {
    const segments = token.type === 'code'
      ? [{ type: 'text' as const, value: token.value }]
      : getCitedLineSegments(token.value, citedLines);
    const content = segments.map((segment, segmentIndex) => segment.type === 'line'
      ? <button
          className="citation-link"
          type="button"
          key={`${tokenIndex}-${segmentIndex}`}
          aria-label={`Open cited log line ${segment.lineNumber}`}
          onClick={() => onCitation(segment.lineNumber)}
        >{segment.value}</button>
      : <span key={`${tokenIndex}-${segmentIndex}`}>{segment.value}</span>);

    if (token.type === 'strong') return [<strong key={tokenIndex}>{content}</strong>];
    if (token.type === 'emphasis') return [<em key={tokenIndex}>{content}</em>];
    if (token.type === 'code') return [<code key={tokenIndex}>{content}</code>];
    return content;
  });
}

function renderAssistantAnswer(
  answer: string,
  citedEvidence: EvidenceReference[],
  onCitation: (lineNumber: number) => void,
): ReactNode {
  const citedLines = new Set(citedEvidence.map((item) => item.line_number));
  const blocks = parseAssistantMarkdown(answer).map((block, index) => {
    if (block.type === 'heading') {
      const heading = renderInlineMarkdown(block.tokens, citedLines, onCitation);
      const headingText = block.tokens.map((token) => token.value).join('').toLowerCase();
      const headingClass = headingText.includes('hypothes') || headingText.includes('explanation')
        ? 'answer-heading hypothesis-heading'
        : headingText.includes('observ') || headingText.includes('fact')
          ? 'answer-heading fact-heading'
          : 'answer-heading';
      if (block.level === 1) return <h1 className={headingClass} key={index}>{heading}</h1>;
      if (block.level === 2) return <h2 className={headingClass} key={index}>{heading}</h2>;
      return <h3 className={headingClass} key={index}>{heading}</h3>;
    }
    if (block.type === 'paragraph') return <p key={index}>{renderInlineMarkdown(block.tokens, citedLines, onCitation)}</p>;
    const items = block.items.map((tokens, itemIndex) => <li key={itemIndex}>{renderInlineMarkdown(tokens, citedLines, onCitation)}</li>);
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
  const [analytics, setAnalytics] = useState<DatasetAnalytics | null>(null);
  const [analyticsDatasetId, setAnalyticsDatasetId] = useState('');
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [analyticsError, setAnalyticsError] = useState('');
  const [analyticsAttempt, setAnalyticsAttempt] = useState(0);
  const [page, setPage] = useState(1);
  const [selectedLine, setSelectedLine] = useState<number | null>(null);
  const [timeRange, setTimeRange] = useState<{ from: string; to: string; label: string } | null>(null);
  const [severity, setSeverity] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [assistantQuestion, setAssistantQuestion] = useState('');
  const [assistantLoading, setAssistantLoading] = useState(false);
  const [assistantError, setAssistantError] = useState('');
  const [assistantTurns, setAssistantTurns] = useState<Array<{ question: string; result: AIChatResponse }>>([]);
  const [workflow, setWorkflow] = useState<InvestigationWorkflow | null>(null);
  const [workflowLoading, setWorkflowLoading] = useState(false);
  const [workflowError, setWorkflowError] = useState('');
  const [selectedWorkflowNode, setSelectedWorkflowNode] = useState<string | null>(null);
  const [workflowFingerprint, setWorkflowFingerprint] = useState('');
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [sourceContext, setSourceContext] = useState<SourceContextSummary>({ files: 0, chunks: 0 });
  const [sourceContextBusy, setSourceContextBusy] = useState(false);
  const [sourceContextError, setSourceContextError] = useState('');
  const [useSourceContext, setUseSourceContext] = useState(false);
  const assistantRequestToken = useRef(0);
  const activeDatasetId = useRef<string | null>(null);
  activeDatasetId.current = dataset?.id ?? null;

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
    void fetchEntries(dataset.id, { page, pageSize: PAGE_SIZE, severity, query: searchTerm, lineNumber: selectedLine, timestampFrom: timeRange?.from, timestampTo: timeRange?.to }, controller.signal)
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
  }, [dataset, page, searchTerm, selectedLine, severity, timeRange]);

  useEffect(() => {
    if (!dataset) return;
    const controller = new AbortController();
    setAnalytics(null);
    setAnalyticsDatasetId(dataset.id);
    setAnalyticsLoading(true);
    setAnalyticsError('');
    void fetchDatasetAnalytics(dataset.id, controller.signal)
      .then(setAnalytics)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setAnalyticsError(error instanceof Error ? error.message : 'Could not load dataset analytics.');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setAnalyticsLoading(false);
      });
    return () => controller.abort();
  }, [dataset, analyticsAttempt]);

  useEffect(() => {
    if (!dataset) { setSourceContext({ files: 0, chunks: 0 }); return; }
    let current = true;
    void fetchSourceContextStatus(dataset.id).then((status) => { if (current) setSourceContext(status); }).catch(() => { if (current) setSourceContext({ files: 0, chunks: 0 }); });
    return () => { current = false; };
  }, [dataset]);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedFile) return;
    setUploading(true);
    setUploadError('');
    try {
      const result = await uploadLogFile(selectedFile);
      assistantRequestToken.current += 1;
      setDataset(result);
      setEntries(null);
      setSeverity('');
      setSearchInput('');
      setSearchTerm('');
      setPage(1);
      setSelectedLine(null);
      setTimeRange(null);
      setAssistantTurns([]);
      setWorkflow(null);
      setWorkflowError('');
      setUseSourceContext(false);
      setSourceFile(null);
      setWorkflowLoading(false);
      setAssistantError('');
      setAssistantLoading(false);
      setAnalytics(null);
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'The file could not be uploaded.');
    } finally {
      setUploading(false);
    }
  }

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(1);
    setSelectedLine(null);
    setSearchTerm(searchInput.trim());
  }

  async function handleAssistantQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!dataset || !assistantQuestion.trim()) return;
    const question = assistantQuestion.trim();
    const datasetId = dataset.id;
    const requestToken = ++assistantRequestToken.current;
    setAssistantLoading(true);
    setAssistantError('');
    try {
      const history = assistantTurns.slice(-4).map((turn) => ({
        question: turn.question,
        answer: turn.result.answer,
      }));
      const result = await askDatasetQuestion(datasetId, question, history);
      if (assistantRequestToken.current !== requestToken || activeDatasetId.current !== datasetId) return;
      setAssistantTurns((turns) => [...turns, { question, result }]);
      setAssistantQuestion('');
    } catch (error) {
      if (assistantRequestToken.current === requestToken && activeDatasetId.current === datasetId) {
        setAssistantError(error instanceof Error ? error.message : 'The AI assistant could not answer right now.');
      }
    } finally {
      if (assistantRequestToken.current === requestToken) setAssistantLoading(false);
    }
  }

  function focusLogLine(lineNumber: number) {
    setSelectedLine(lineNumber);
    setPage(1);
    setSearchInput('');
    setSearchTerm('');
    setSeverity('');
    setTimeRange(null);
    document.getElementById('log-explorer')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function investigatePattern(fingerprint: string) {
    if (!dataset) return;
    setWorkflowLoading(true);
    setWorkflowFingerprint(fingerprint);
    setWorkflowError('');
    setWorkflow(null);
    setSelectedWorkflowNode(null);
    try {
      const result = await investigateErrorPattern(dataset.id, fingerprint, useSourceContext);
      if (activeDatasetId.current === dataset.id) setWorkflow(result);
    } catch (error) {
      if (activeDatasetId.current === dataset.id) setWorkflowError(error instanceof Error ? error.message : 'Could not create the investigation workflow.');
    } finally {
      if (activeDatasetId.current === dataset.id) setWorkflowLoading(false);
    }
  }

  async function handleSourceUpload() {
    if (!dataset || !sourceFile) return;
    setSourceContextBusy(true); setSourceContextError('');
    try { const status = await uploadSourceContext(dataset.id, sourceFile); if (activeDatasetId.current === dataset.id) { setSourceContext(status); setSourceFile(null); } }
    catch (error) { if (activeDatasetId.current === dataset.id) setSourceContextError(error instanceof Error ? error.message : 'Could not index this source archive.'); }
    finally { if (activeDatasetId.current === dataset.id) setSourceContextBusy(false); }
  }

  async function handleSourceDelete() {
    if (!dataset) return;
    setSourceContextBusy(true); setSourceContextError('');
    try { await deleteSourceContext(dataset.id); if (activeDatasetId.current === dataset.id) { setSourceContext({ files: 0, chunks: 0 }); setUseSourceContext(false); } }
    catch (error) { if (activeDatasetId.current === dataset.id) setSourceContextError(error instanceof Error ? error.message : 'Could not remove source context.'); }
    finally { if (activeDatasetId.current === dataset.id) setSourceContextBusy(false); }
  }

  function focusTimelineBucket(timestamp: string, unit: DatasetAnalytics['timeline']['bucket_unit'], interval: number) {
    const start = new Date(timestamp.endsWith('Z') ? timestamp : `${timestamp}Z`);
    const duration = unit === 'minute' ? 60_000 : unit === 'hour' ? 3_600_000 : unit === 'day' ? 86_400_000 : 604_800_000;
    const from = start.toISOString();
    const to = new Date(start.getTime() + duration * interval).toISOString();
    setTimeRange({ from, to, label: formatTimestamp(timestamp) });
    setSelectedLine(null);
    setPage(1);
    setSearchTerm('');
    setSearchInput('');
    document.getElementById('log-explorer')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  const timelineBuckets = analytics?.timeline.buckets ?? [];
  const timelineMaximum = Math.max(...timelineBuckets.map((bucket) => bucket.entries), 0);
  const severityTimelineMaximum = Math.max(...timelineBuckets.map((bucket) => bucket.error_count + bucket.warning_count), 0);
  const allSeverityTimelineMaximum = Math.max(...timelineBuckets.map((bucket) => Object.values(bucket.severity_counts).reduce((sum, count) => sum + count, 0)), 0);
  const timestampedEventCount = timelineBuckets.reduce((total, bucket) => total + bucket.entries, 0);
  const timelineLabelIndices = selectTimelineLabelIndices(timelineBuckets.length);
  const timelinePlotMinWidth = timelineBuckets.length > 32
    ? Math.min(700, timelineBuckets.length * 7)
    : null;

  return (
    <main className="page-shell">
      <header className="topbar">
        <a className="brand" href="#home" aria-label="LogLens home">
          <span className="brand-mark" aria-hidden="true"><span /><span /><span /></span>
          <span>LogLens</span>
        </a>
        <span className="phase-label">LOCAL PREVIEW <i /></span>
      </header>
      <nav className="workspace-nav" aria-label="Workspace sections">
        <a href="#home">Overview</a><a href="#log-explorer">Log Explorer</a><a href="#analytics">Analytics</a><a href="#ai-investigator">AI Investigator</a>
      </nav>

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

      <section className="workspace" id="log-explorer" aria-label="Log file explorer">
        <div className="section-heading">
          <div><div className="eyebrow"><span className="eyebrow-line" /> LOG EXPLORER</div><h2>Start with a log file</h2></div>
          <span className="local-note">Files stay in your local LogLens database</span>
        </div>

        <form className="upload-panel" onSubmit={handleUpload}>
          <label className="file-picker">
            <span className="file-picker-icon" aria-hidden="true">↑</span>
            <span><strong>Choose a log file</strong><small>Supported formats: .log, .txt, .json, .jsonl, and .ndjson</small></span>
            <input
              type="file"
              accept=".log,.txt,.json,.jsonl,.ndjson,text/plain,application/json"
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

            <section className="analytics-panel" id="analytics" aria-label="Dataset analytics" aria-busy={analyticsLoading}>
              <div className="section-heading analytics-heading">
                <div><div className="eyebrow"><span className="eyebrow-line" /> DETERMINISTIC ANALYTICS</div><h2>Dataset overview</h2></div>
                <span className="local-note">Counts and patterns are computed from this dataset</span>
              </div>
              {analyticsLoading ? <div className="table-message"><span className="spinner" /> Calculating dataset analytics…</div> : analyticsError ? (
                <div className="analytics-error" role="alert"><span>{analyticsError}</span><button type="button" onClick={() => setAnalyticsAttempt((value) => value + 1)}>Retry analytics</button></div>
              ) : analytics && analyticsDatasetId === dataset.id ? (
                <>
                  <div className="analytics-metrics">
                    <div className="analytics-metric"><strong>{analytics.error_count}</strong><span>ERROR EVENTS</span></div>
                    <div className="analytics-metric"><strong>{analytics.warning_count}</strong><span>WARNINGS</span></div>
                    <div className="analytics-metric"><strong>{analytics.unique_error_patterns}</strong><span>UNIQUE ERROR PATTERNS</span></div>
                    <div className="analytics-metric"><strong>{analytics.recurring_error_patterns}</strong><span>RECURRING PATTERNS</span></div>
                    <div className="analytics-metric"><strong>{analytics.unparsed_entries}</strong><span>UNPARSED ENTRIES</span></div>
                  </div>
                  <div className="analytics-grid">
                    <section className="analytics-card" aria-label="Severity distribution">
                      <h3>Severity distribution</h3>
                      <div className="severity-chart">
                        {Object.entries(analytics.severity_counts).map(([level, count]) => {
                          const maxCount = Math.max(...Object.values(analytics.severity_counts), 1);
                          return <div className="severity-row" key={level}>
                            <span>{level}</span><div className="bar-track"><div className={`bar-fill ${level.toLowerCase()}`} style={{ width: `${(count / maxCount) * 100}%` }} /></div><strong>{count}</strong>
                          </div>;
                        })}
                      </div>
                    </section>
                    <section className="analytics-card timeline-card" aria-label="Entry activity timeline">
                      <h3>Entry activity <small>{analytics.timeline.bucket_unit === 'none' ? 'no timestamps' : `per ${analytics.timeline.bucket_interval > 1 ? `${analytics.timeline.bucket_interval} ` : ''}${analytics.timeline.bucket_unit}`}</small></h3>
                      {timelineBuckets.length ? <>
                        <div className="timeline-summary" aria-label="Dataset event totals">
                          <span><strong>{timestampedEventCount}</strong> timestamped events</span>
                          <span><strong>{analytics.error_count}</strong> dataset errors</span>
                          <span><strong>{analytics.warning_count}</strong> dataset warnings</span>
                        </div>
                        <div className="timeline-viewport" role="region" aria-label="Scrollable activity timeline">
                          <div className="timeline-plot" style={timelinePlotMinWidth ? { minWidth: `${timelinePlotMinWidth}px` } : undefined}>
                            <div className="timeline-chart" role="group" aria-label={`Activity chart with ${timelineBuckets.length} time buckets`} style={{ gridTemplateColumns: `repeat(${timelineBuckets.length}, minmax(3px, 1fr))` }}>
                              {timelineBuckets.map((bucket) => {
                                const timestamp = formatTimestamp(bucket.timestamp);
                                const interval = `${analytics.timeline.bucket_interval > 1 ? `${analytics.timeline.bucket_interval} ` : ''}${analytics.timeline.bucket_unit}`;
                                return <button
                                  type="button"
                                  className="timeline-column"
                                  key={bucket.timestamp}
                                  title={`${timestamp} · ${bucket.entries} events · ${bucket.error_count} errors · ${bucket.warning_count} warnings`}
                                  aria-label={`${timestamp}, ${bucket.entries} events, ${bucket.error_count} errors, and ${bucket.warning_count} warnings in this ${interval} bucket`}
                                  onClick={() => focusTimelineBucket(bucket.timestamp, analytics.timeline.bucket_unit, analytics.timeline.bucket_interval)}
                                >
                                  <span className="timeline-bar" style={{ height: `${getTimelineBarHeight(bucket.entries, timelineMaximum)}%` }} />
                                </button>;
                              })}
                            </div>
                            <div className="timeline-axis" aria-hidden="true">
                              {timelineLabelIndices.map((bucketIndex, labelIndex) => {
                                const bucket = timelineBuckets[bucketIndex];
                                const edge = labelIndex === 0 || labelIndex === timelineLabelIndices.length - 1;
                                const left = timelineBuckets.length === 1 ? 0 : (bucketIndex / (timelineBuckets.length - 1)) * 100;
                                return <span
                                  className={`timeline-axis-label${edge ? ' edge' : ' interior'}`}
                                  key={bucket.timestamp}
                                  style={{ left: `${left}%` }}
                                  title={formatTimestamp(bucket.timestamp)}
                                >{formatTimelineLabel(bucket.timestamp, analytics.timeline.bucket_unit)}</span>;
                              })}
                            </div>
                          </div>
                        </div>
                        <div className="severity-timeline-heading"><strong>Error and warning activity</strong><span><i className="legend-error" /> Errors <i className="legend-warning" /> Warnings</span></div>
                        <div className="timeline-viewport" role="region" aria-label="Scrollable error and warning activity timeline">
                          <div className="timeline-chart severity-timeline" role="group" aria-label="Errors and warnings by time bucket" style={{ gridTemplateColumns: `repeat(${timelineBuckets.length}, minmax(3px, 1fr))`, minWidth: timelinePlotMinWidth ? `${timelinePlotMinWidth}px` : undefined }}>
                            {timelineBuckets.map((bucket) => <button type="button" className="severity-timeline-column" key={bucket.timestamp} title={`${formatTimestamp(bucket.timestamp)} · ${bucket.error_count} errors · ${bucket.warning_count} warnings`} aria-label={`Filter log entries to ${formatTimestamp(bucket.timestamp)} with ${bucket.error_count} errors and ${bucket.warning_count} warnings`} onClick={() => focusTimelineBucket(bucket.timestamp, analytics.timeline.bucket_unit, analytics.timeline.bucket_interval)}>
                              <span className="severity-stack"><i className="legend-error" style={{ height: `${severityTimelineMaximum ? (bucket.error_count / severityTimelineMaximum) * 100 : 0}%` }} /><i className="legend-warning" style={{ height: `${severityTimelineMaximum ? (bucket.warning_count / severityTimelineMaximum) * 100 : 0}%` }} /></span>
                            </button>)}
                          </div>
                        </div>
                        <div className="all-severity-heading"><strong>Severity trends</strong><span>{SEVERITY_LEVELS.map((level) => <span key={level}><i className={`legend-${level.toLowerCase()}`} />{level}</span>)}</span></div>
                        <div className="timeline-viewport" role="region" aria-label="Scrollable severity trends">
                          <div className="timeline-chart severity-timeline" role="group" aria-label="Severity counts by time bucket" style={{ gridTemplateColumns: `repeat(${timelineBuckets.length}, minmax(3px, 1fr))`, minWidth: timelinePlotMinWidth ? `${timelinePlotMinWidth}px` : undefined }}>
                            {timelineBuckets.map((bucket) => <button type="button" className="severity-timeline-column" key={bucket.timestamp} title={`${formatTimestamp(bucket.timestamp)} · ${SEVERITY_LEVELS.map((level) => `${bucket.severity_counts[level] ?? 0} ${level}`).join(' · ')}`} aria-label={`Filter entries for ${formatTimestamp(bucket.timestamp)} by severity activity`} onClick={() => focusTimelineBucket(bucket.timestamp, analytics.timeline.bucket_unit, analytics.timeline.bucket_interval)}>
                              <span className="severity-stack">{SEVERITY_LEVELS.map((level) => <i key={level} className={`legend-${level.toLowerCase()}`} style={{ height: `${allSeverityTimelineMaximum ? ((bucket.severity_counts[level] ?? 0) / allSeverityTimelineMaximum) * 100 : 0}%` }} />)}</span>
                            </button>)}
                          </div>
                        </div>
                        <p className="sr-only">The chart contains {timestampedEventCount} timestamped events in {timelineBuckets.length} buckets. Dataset totals: {analytics.error_count} errors and {analytics.warning_count} warnings.</p>
                      </> : <p className="analytics-empty">{analytics.total_entries === 0
                        ? 'This dataset has no entries to plot.'
                        : `No parsed timestamps are available to plot. All ${analytics.total_entries} records remain available in Log entries.`}</p>}
                    </section>
                  </div>
                  <section className="analytics-card patterns-card">
                    <div className="pattern-heading"><div><h3>Top Error Patterns</h3><p>Messages are grouped by severity after case, whitespace, timestamp, UUID, valid IPv4/IPv6, and labeled request ID normalization. Meaningful numbers such as status codes remain distinct.</p></div><span>TOP {analytics.error_patterns.length} / {analytics.unique_error_patterns}</span></div>
                    {analytics.error_patterns.length ? <div className="pattern-list">{analytics.error_patterns.map((pattern) => (
                      <article className="pattern-row" key={pattern.fingerprint}>
                        <div className="pattern-card-heading">
                          <span className={`severity-badge ${pattern.severity.toLowerCase()}`}>{pattern.severity}</span>
                          <span className="pattern-occurrences"><strong>{pattern.occurrences}</strong> occurrence{pattern.occurrences === 1 ? '' : 's'}</span>
                          {pattern.occurrences >= 2 && <span className="recurring-badge">Recurring</span>}
                        </div>
                        <p className="pattern-template">{pattern.normalized_message_template}</p>
                        <p className="pattern-example"><span>Representative message</span><code>{pattern.representative_message}</code></p>
                        <div className="pattern-details">
                          <span>{pattern.distinct_message_count} message variation{pattern.distinct_message_count === 1 ? '' : 's'}</span>
                          <span>First seen <time dateTime={pattern.first_timestamp ?? undefined}>{formatTimestamp(pattern.first_timestamp)}</time></span>
                          <span>Last seen <time dateTime={pattern.last_timestamp ?? undefined}>{formatTimestamp(pattern.last_timestamp)}</time></span>
                        </div>
                        <div className="pattern-sources" aria-label="Representative source lines">
                          <span>Source lines</span>
                          {pattern.representative_line_numbers.map((lineNumber) => <button
                            type="button"
                            className="line-link"
                            key={lineNumber}
                            aria-label={`Open line ${lineNumber} in the selected dataset`}
                            onClick={() => focusLogLine(lineNumber)}
                          >{lineNumber}</button>)}
                        </div>
                        <button type="button" className="investigate-pattern-button" disabled={workflowLoading} onClick={() => void investigatePattern(pattern.fingerprint)}>
                          {workflowLoading ? 'Building workflow…' : 'Investigate this error'}
                        </button>
                      </article>
                    ))}</div> : <p className="analytics-empty">No error patterns were found in this dataset. ERROR, FATAL, and CRITICAL entries will appear here.</p>}
                  </section>
                  {(workflowLoading || workflowError || workflow) && <section className="workflow-panel" aria-label="AI troubleshooting workflow" aria-busy={workflowLoading}>
                    <div className="workflow-heading"><div><div className="eyebrow"><span className="eyebrow-line" /> AI INVESTIGATION</div><h3>{workflow?.title ?? 'Troubleshooting workflow'}</h3></div>{workflow && <span className="workflow-safety">Suggested steps · root cause unconfirmed</span>}</div>
                    {workflowLoading && <p className="assistant-status" role="status"><span className="spinner" /> Reviewing selected error and nearby log evidence…</p>}
                    {workflowError && <p className="form-error" role="alert">{workflowError} <button type="button" onClick={() => workflowFingerprint && void investigatePattern(workflowFingerprint)}>Retry</button></p>}
                    {workflow && <><p className="workflow-summary">{workflow.summary}</p>{workflow.source_context_used && <p className="workflow-caution">Relevant source snippets were included by your request. Code evidence does not establish runtime behavior.</p>}<div className="workflow-graph" role="list" aria-label="Investigation steps">
                      {workflow.nodes.map((node) => <div className="workflow-node-wrap" key={node.id}>
                        <div className={`workflow-node ${selectedWorkflowNode === node.id ? 'selected' : ''}`} role="listitem">
                          <button type="button" className="workflow-node-toggle" onClick={() => setSelectedWorkflowNode(selectedWorkflowNode === node.id ? null : node.id)} aria-expanded={selectedWorkflowNode === node.id}>
                            <span className={`workflow-status ${node.status}`}>{node.status.replace('_', ' ')}</span><strong>{node.title}</strong><small>{node.kind.replaceAll('_', ' ')}</small>
                          </button>
                          {selectedWorkflowNode === node.id && <div className="workflow-description">{node.description}{node.evidence_lines.length > 0 && <div className="workflow-lines">Log evidence: {node.evidence_lines.map((line) => <span key={line}><button type="button" className="line-link" onClick={() => focusLogLine(line)}>Line {line}</button>{' '}</span>)}</div>}{node.source_refs.length > 0 && <div className="workflow-lines">Source evidence: {node.source_refs.map((reference) => <span key={reference}><a href={`#source-${reference}`}>{workflow.source_evidence.find((item) => item.reference === reference)?.file_path ?? reference}</a>{' '}</span>)}</div>}</div>}
                        </div>
                        {workflow.edges.filter((edge) => edge.source === node.id).map((edge) => <button type="button" className="workflow-edge" key={`${edge.source}-${edge.target}`} onClick={() => setSelectedWorkflowNode(edge.target)} aria-label={`Follow ${edge.label || 'workflow edge'} to ${workflow.nodes.find((target) => target.id === edge.target)?.title ?? edge.target}`}>
                          <span aria-hidden="true">→</span> {edge.label || 'Continue to'} <span aria-hidden="true">→</span> {workflow.nodes.find((target) => target.id === edge.target)?.title ?? edge.target}
                        </button>)}
                      </div>)}
                    </div><p className="workflow-caution">Recommendations are investigation ideas, not confirmed causes. Verify them against the application and infrastructure.</p>
                    {workflow.limitations.length > 0 && <ul className="workflow-limitations">{workflow.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul>}
                    {workflow.evidence.length > 0 && <div className="evidence-list"><strong>Validated log evidence</strong>{workflow.evidence.map((item) => <div className="evidence-item" key={item.id}><span><button type="button" className="line-link" onClick={() => focusLogLine(item.line_number)}>Line {item.line_number}</button>{item.severity ? ` · ${item.severity}` : ''}</span><p>{item.parsed ? item.message : item.raw_line ?? item.message}</p>{!item.parsed && <small>Unparsed original text; structured fields are unavailable.</small>}</div>)}</div>}
                    {workflow.source_evidence.length > 0 && <div className="evidence-list source-evidence"><strong>Source-code evidence · code observations do not prove runtime behavior</strong>{workflow.source_evidence.map((item) => <div className="evidence-item" id={`source-${item.reference}`} key={item.reference}><span>{item.reference} · {item.file_path} · chunk {item.chunk_index + 1}</span><pre>{item.content}</pre></div>)}</div>}
                    {workflow.verification_steps.length > 0 && <div className="workflow-verifications"><strong>Verification steps</strong><ol>{workflow.verification_steps.map((step, index) => <li key={index}>{step}</li>)}</ol></div>}
                    </>}
                  </section>}
                </>
              ) : null}
            </section>

            <section className="assistant-panel" id="ai-investigator" aria-label="AI log assistant">
              <div className="assistant-heading">
                <div><div className="eyebrow"><span className="eyebrow-line" /> AI ASSISTANT</div><h2>Ask about these logs</h2></div>
                <span className="assistant-note">Answers cite retrieved log lines</span>
              </div>
              <div className="source-context-controls">
                <div><strong>Optional source context</strong><p>Upload a ZIP containing source code you are authorized to share. LogLens indexes selected source files locally and never executes uploaded code.</p></div>
                <input aria-label="Choose a source code ZIP" type="file" accept=".zip,application/zip" disabled={sourceContextBusy} onChange={(event) => { setSourceFile(event.target.files?.[0] ?? null); setSourceContextError(''); }} />
                <button type="button" disabled={!sourceFile || sourceContextBusy} onClick={() => void handleSourceUpload()}>{sourceContextBusy ? 'Indexing…' : sourceContext.files ? 'Replace source ZIP' : 'Index source ZIP'}</button>
                {sourceContext.files > 0 && <><span className="source-status">{sourceContext.files} files indexed</span><button type="button" className="source-delete" disabled={sourceContextBusy} onClick={() => void handleSourceDelete()}>Delete source context</button></>}
                <label className="source-opt-in"><input type="checkbox" checked={useSourceContext} disabled={sourceContext.files === 0 || sourceContextBusy} onChange={(event) => setUseSourceContext(event.target.checked)} /> Include relevant code snippets when investigating an error</label>
                {sourceContextError && <p className="form-error" role="alert">{sourceContextError}</p>}
              </div>
              {assistantTurns.map((turn, index) => (
                <article className="assistant-turn" key={`${index}-${turn.question}`}>
                  <p className="assistant-question">{turn.question}</p>
                  {renderAssistantAnswer(turn.result.answer, turn.result.cited_evidence, focusLogLine)}
                  <p className="assistant-result-meta" role="status">
                    {turn.result.cited_evidence.length > 0
                      ? `Response ready · ${turn.result.cited_evidence.length} cited entr${turn.result.cited_evidence.length === 1 ? 'y' : 'ies'}`
                      : turn.result.evidence.length > 0
                        ? `Response ready · no explicit citations · ${turn.result.evidence.length} entries available as context`
                        : 'Response ready · no supporting entries were returned'}
                  </p>
                  {turn.result.completion_status === 'unknown' && <p className="assistant-status">The provider did not report whether generation ended normally. Review the answer against the supporting entries.</p>}
                  {turn.result.evidence.length > 0 && <div className="evidence-list">
                    <strong>{turn.result.cited_evidence.length > 0 ? 'Supporting entries' : 'Available context'}</strong>
                    {(turn.result.cited_evidence.length > 0 ? turn.result.cited_evidence : turn.result.evidence).map((item) => <div className="evidence-item" key={item.id}>
                      <span><button type="button" className="line-link" aria-label={`Open supporting log line ${item.line_number}`} onClick={() => focusLogLine(item.line_number)}>Line {item.line_number}</button>{item.severity ? ` · ${item.severity}` : ''}{!item.parsed ? ' · UNPARSED' : ''}</span><p>{!item.parsed ? item.raw_line ?? item.message : item.message}</p>
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

            <div className="entries-heading"><div><div className="eyebrow"><span className="eyebrow-line" /> SOURCE RECORDS</div><h2>Log entries</h2></div><span className="entry-count">{selectedLine ? `Line ${selectedLine} · ` : ''}{entries?.total ?? '—'} matching records</span></div>
            {timeRange && <div className="active-time-filter" role="status">Showing entries from {timeRange.label}<button type="button" onClick={() => { setTimeRange(null); setPage(1); }}>Clear time filter</button></div>}
            <div className="filters">
              <form className="search-form" onSubmit={handleSearch}>
                <span aria-hidden="true">⌕</span><input aria-label="Search log messages" maxLength={200} value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="Search messages…" />
                <button type="submit">Search</button>
              </form>
              <label className="severity-control">Severity
                <select value={severity} onChange={(event) => { setSeverity(event.target.value); setSelectedLine(null); setPage(1); }}>
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

      <footer><span>LOG LENS <span className="footer-dot">·</span> PHASE 4</span><span>Built for clearer debugging</span></footer>
    </main>
  );
}
