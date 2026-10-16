import type { DatasetAnalytics, LogEntry, UploadSummary } from './api';
import type { WorkspaceSection } from './AppShell';
import { DashboardCharts } from './DashboardCharts';

type TimelineBucket = DatasetAnalytics['timeline']['buckets'][number];

function displayTimestamp(value: string | null): string {
  if (!value) return '—';
  return value.replace('T', ' ').replace('Z', ' UTC').replace('+00:00', ' UTC').slice(0, 23);
}

function Metric({ label, value, note, tone = '' }: { label: string; value: string | number; note: string; tone?: string }) {
  return <article className="metric-card"><div className="metric-label">{label}</div><strong className={`metric-value ${tone}`}>{typeof value === 'number' ? value.toLocaleString() : value}</strong><span className="metric-note">{note}</span></article>;
}

export function OverviewDashboard({ dataset, analytics, analyticsLoading, analyticsError, recentEntries, recentLoading, recentError, onRetryAnalytics, onFocusLine, onTimeBucket, onNavigate, onInvestigate }: {
  dataset: UploadSummary | null;
  analytics: DatasetAnalytics | null;
  analyticsLoading: boolean;
  analyticsError: string;
  recentEntries: LogEntry[];
  recentLoading: boolean;
  recentError: string;
  onRetryAnalytics: () => void;
  onFocusLine: (line: number) => void;
  onTimeBucket: (bucket: TimelineBucket) => void;
  onNavigate: (section: WorkspaceSection) => void;
  onInvestigate: (fingerprint: string) => void;
}) {
  if (!dataset) return <section className="empty-dataset panel" aria-label="No dataset selected">
    <span className="empty-dataset-icon" aria-hidden="true">⌁</span><h2>Your next investigation starts here</h2>
    <p>Upload a log file to explore records, understand event activity, and inspect recurring errors.</p>
    <button type="button" onClick={() => onNavigate('log-explorer')}>Go to Log Explorer <span aria-hidden="true">→</span></button>
  </section>;

  const recurringPatterns = analytics?.error_patterns.filter((pattern) => pattern.occurrences >= 2) ?? [];
  const dataReady = !!analytics && !analyticsLoading;

  return <>
    <div className="dataset-bar">
      <div className="dataset-bar-file"><span className="dataset-file-icon" aria-hidden="true">≡</span><div className="dataset-bar-copy"><strong title={dataset.filename}>{dataset.filename}</strong><span>{dataset.total_entries.toLocaleString()} entries · Uploaded {new Date(dataset.uploaded_at).toLocaleString()}</span></div></div>
      <span className="dataset-persisted"><i />Persisted dataset</span>
    </div>

    <section className="metric-grid" aria-label="Selected dataset metrics" aria-busy={analyticsLoading}>
      <Metric label="Total Entries" value={dataset.total_entries} note="Across selected dataset" />
      <Metric label="Error Events" value={dataReady ? analytics.error_count : '—'} note={dataReady && analytics.total_entries ? `${((analytics.error_count / analytics.total_entries) * 100).toFixed(1)}% of all entries` : 'From selected dataset'} tone="error" />
      <Metric label="Warnings" value={dataReady ? analytics.warning_count : '—'} note={dataReady && analytics.total_entries ? `${((analytics.warning_count / analytics.total_entries) * 100).toFixed(1)}% of all entries` : 'From selected dataset'} tone="warning" />
      <Metric label="Recurring Patterns" value={dataReady ? analytics.recurring_error_patterns : '—'} note="Two or more occurrences" />
      <Metric label="Unparsed Entries" value={dataReady ? analytics.unparsed_entries : dataset.unparsed_entries} note="Original records retained" />
    </section>

    {analyticsError && <div className="error-banner overview-error" role="alert"><span>{analyticsError}</span><button type="button" onClick={onRetryAnalytics}>Retry analytics</button></div>}
    <DashboardCharts analytics={dataReady ? analytics : null} totalEntries={dataset.total_entries} loading={analyticsLoading} onTimeBucket={onTimeBucket} />

    <section className="panel table-panel overview-table-panel">
      <div className="panel-heading"><div><h2>Recurring Errors</h2><p>Repeated error patterns from the selected dataset</p></div><button type="button" className="panel-link" onClick={() => onNavigate('analytics')}>View analytics <span aria-hidden="true">→</span></button></div>
      {analyticsLoading && !analytics ? <p className="panel-empty">Finding repeated error patterns…</p> : analyticsError && !analytics ? <p className="panel-empty error-text" role="alert">{analyticsError}</p> : recurringPatterns.length ? <div className="overview-table-scroll"><table className="overview-data-table">
        <thead><tr><th>Representative message</th><th>Severity</th><th>Occurrences</th><th>Source lines</th><th><span className="sr-only">Investigation action</span></th></tr></thead>
        <tbody>{recurringPatterns.slice(0, 5).map((pattern) => <tr key={pattern.fingerprint}>
          <td><span className="overview-message" title={pattern.representative_message}>{pattern.representative_message}</span><small>{pattern.normalized_message_template}</small></td>
          <td><span className={`severity-badge ${pattern.severity.toLowerCase()}`}>{pattern.severity}</span></td>
          <td className="occurrence-cell">{pattern.occurrences.toLocaleString()}</td>
          <td><div className="source-line-links">{pattern.representative_line_numbers.slice(0, 3).map((line) => <button type="button" className="line-link" key={line} onClick={() => onFocusLine(line)} aria-label={`Open source line ${line}`}>L{line}</button>)}{pattern.representative_line_numbers.length > 3 && <span>+{pattern.representative_line_numbers.length - 3} more</span>}</div></td>
          <td><button type="button" className="table-action" onClick={() => onInvestigate(pattern.fingerprint)}>Investigate <span aria-hidden="true">→</span></button></td>
        </tr>)}</tbody>
      </table></div> : <p className="panel-empty">{analytics ? 'No recurring errors in this dataset.' : 'Analytics are not available for this dataset.'}</p>}
    </section>

    <section className="panel table-panel overview-table-panel recent-table-panel">
      <div className="panel-heading"><div><h2>Recent Log Entries</h2><p>Latest records in this dataset</p></div><button type="button" className="panel-link" onClick={() => onNavigate('log-explorer')}>Open Log Explorer <span aria-hidden="true">→</span></button></div>
      {recentLoading ? <p className="panel-empty">Loading recent entries…</p> : recentError ? <p className="panel-empty error-text" role="alert">{recentError}</p> : recentEntries.length ? <div className="overview-table-scroll"><table className="overview-data-table recent-data-table">
        <thead><tr><th>Timestamp <span>UTC</span></th><th>Severity</th><th>Message</th><th>Source</th></tr></thead>
        <tbody>{recentEntries.map((entry) => <tr key={entry.id}>
          <td className="timestamp-cell">{displayTimestamp(entry.timestamp)}</td>
          <td><span className={`severity-badge ${entry.severity?.toLowerCase() ?? 'unparsed'}`}>{entry.severity ?? 'UNPARSED'}</span></td>
          <td><button type="button" className="message-cell-button" onClick={() => onFocusLine(entry.line_number)} title="Open this source record">{entry.parsed ? entry.message : entry.raw_line}</button></td>
          <td><button type="button" className="line-link" onClick={() => onFocusLine(entry.line_number)} aria-label={`Open source line ${entry.line_number}`}>L{entry.line_number}</button></td>
        </tr>)}</tbody>
      </table></div> : <p className="panel-empty">No log entries are available.</p>}
    </section>
  </>;
}
