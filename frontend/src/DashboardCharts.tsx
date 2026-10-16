import type { DatasetAnalytics } from './api';
import { selectTimelineLabelIndices } from './presentation.mjs';

type Bucket = DatasetAnalytics['timeline']['buckets'][number];
type TimelineUnit = DatasetAnalytics['timeline']['bucket_unit'];

const plot = { left: 42, top: 12, width: 574, height: 128 };
const severityColors: Record<string, string> = {
  TRACE: '#8d9aad', DEBUG: '#687d9d', INFO: '#5277df', WARN: '#dda43c',
  ERROR: '#d66a5b', FATAL: '#8c4cb3', CRITICAL: '#bd3f52', UNPARSED: '#b3a3c6',
};

function bucketLabel(timestamp: string, unit: TimelineUnit): string {
  if (unit === 'minute') return timestamp.slice(11, 16);
  if (unit === 'hour') return timestamp.slice(5, 16).replace('T', ' ');
  return timestamp.slice(0, 10);
}

function displayTimestamp(timestamp: string): string {
  return timestamp.replace(/\.\d+(?=(?:Z|[+-]\d{2}:\d{2})?$)/, '').replace('T', ' ').replace(/Z$/, ' UTC').replace(/\+00:00$/, ' UTC');
}

function SeriesLegend({ items }: { items: Array<{ key: string; label: string; color: string }> }) {
  return <div className="chart-legend">{items.map((item) => <span key={item.key}><i className="chart-legend-swatch" style={{ backgroundColor: item.color }} />{item.label}</span>)}</div>;
}

function ChartHeading({ title, subtitle, note }: { title: string; subtitle: string; note?: string }) {
  return <div className="panel-heading"><div><h2>{title}</h2><p>{subtitle}</p></div>{note && <span className="chart-period">{note}</span>}</div>;
}

function TimeAxis({ buckets, unit }: { buckets: Bucket[]; unit: TimelineUnit }) {
  const labels = selectTimelineLabelIndices(buckets.length, 5);
  return <>{labels.map((index) => {
    const x = buckets.length <= 1 ? plot.left + plot.width / 2 : plot.left + (index / (buckets.length - 1)) * plot.width;
    const anchor = index === 0 ? 'start' : index === buckets.length - 1 ? 'end' : 'middle';
    return <text key={buckets[index].timestamp} x={x} y="165" textAnchor={anchor} className="chart-axis-label">{bucketLabel(buckets[index].timestamp, unit)}</text>;
  })}</>;
}

function GridLines({ maximum }: { maximum: number }) {
  return <>{Array.from({ length: 5 }, (_, index) => {
    const ratio = index / 4;
    const y = plot.top + plot.height - ratio * plot.height;
    const value = Math.round(maximum * ratio);
    return <g key={index}><line x1={plot.left} x2={plot.left + plot.width} y1={y} y2={y} className="chart-grid-line" /><text x={plot.left - 8} y={y + 3} textAnchor="end" className="chart-axis-label">{value}</text></g>;
  })}</>;
}

function BucketTargets({ buckets, onTimeBucket }: { buckets: Bucket[]; onTimeBucket: (bucket: Bucket) => void }) {
  const segmentWidth = plot.width / Math.max(buckets.length, 1);
  return <>{buckets.map((bucket, index) => <rect
    key={bucket.timestamp}
    x={plot.left + index * segmentWidth}
    y={plot.top}
    width={segmentWidth}
    height={plot.height}
    className="chart-hit-area"
    role="button"
    tabIndex={0}
    aria-label={`Filter log entries to ${displayTimestamp(bucket.timestamp)}; ${bucket.entries} events`}
    onClick={() => onTimeBucket(bucket)}
    onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onTimeBucket(bucket); } }}
  ><title>{displayTimestamp(bucket.timestamp)} · {bucket.entries} events</title></rect>)}</>;
}

function LineChart({ buckets, unit, series, onTimeBucket, label }: {
  buckets: Bucket[];
  unit: TimelineUnit;
  series: Array<{ key: string; label: string; color: string }>;
  onTimeBucket: (bucket: Bucket) => void;
  label: string;
}) {
  const maximum = Math.max(1, ...buckets.flatMap((bucket) => series.map((item) => bucket.severity_counts[item.key] ?? 0)));
  const points = (key: string) => buckets.map((bucket, index) => {
    const x = buckets.length <= 1 ? plot.left + plot.width / 2 : plot.left + (index / (buckets.length - 1)) * plot.width;
    const y = plot.top + plot.height - ((bucket.severity_counts[key] ?? 0) / maximum) * plot.height;
    return { x, y };
  });
  return <div className="chart-plot-wrap">
    {buckets.length ? <svg className="data-chart" viewBox="0 0 640 178" role="group" aria-label={label}>
      <GridLines maximum={maximum} />
      {series.map((item) => <polyline key={item.key} points={points(item.key).map(({ x, y }) => `${x},${y}`).join(' ')} fill="none" stroke={item.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />)}
      <BucketTargets buckets={buckets} onTimeBucket={onTimeBucket} />
      <TimeAxis buckets={buckets} unit={unit} />
    </svg> : <div className="chart-empty">No timestamped records are available for this dataset.</div>}
  </div>;
}

function EventChart({ buckets, unit, onTimeBucket, totalEntries, loading }: { buckets: Bucket[]; unit: TimelineUnit; onTimeBucket: (bucket: Bucket) => void; totalEntries: number; loading: boolean }) {
  const maximum = Math.max(1, ...buckets.map((bucket) => bucket.entries));
  const coords = buckets.map((bucket, index) => {
    const x = buckets.length <= 1 ? plot.left + plot.width / 2 : plot.left + (index / (buckets.length - 1)) * plot.width;
    const y = plot.top + plot.height - (bucket.entries / maximum) * plot.height;
    return { x, y };
  });
  const linePath = coords.map(({ x, y }, index) => `${index ? 'L' : 'M'} ${x} ${y}`).join(' ');
  const areaPath = coords.length ? `${linePath} L ${coords.at(-1)?.x} ${plot.top + plot.height} L ${coords[0].x} ${plot.top + plot.height} Z` : '';
  return <section className="panel chart-panel event-chart" aria-label="Event activity by time bucket">
    <ChartHeading title="Event activity" subtitle="Log volume across the selected dataset" note={totalEntries.toLocaleString() + ' events'} />
    <div className="chart-plot-wrap">
      {buckets.length ? <svg className="data-chart" viewBox="0 0 640 178" role="group" aria-label="Event count time series">
        <GridLines maximum={maximum} />
        <path d={areaPath} fill="#5277df" fillOpacity=".12" />
        <path d={linePath} fill="none" stroke="#5277df" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        <BucketTargets buckets={buckets} onTimeBucket={onTimeBucket} />
        <TimeAxis buckets={buckets} unit={unit} />
      </svg> : <div className="chart-empty">{loading ? 'Loading event activity…' : 'No timestamped records are available for this dataset.'}</div>}
    </div>
    <div className="chart-footer"><span>Bucket size: {unit === 'none' ? 'unavailable' : unit}</span><span>Select a time period to inspect entries</span></div>
  </section>;
}

function SeverityDonut({ analytics, totalEntries }: { analytics: DatasetAnalytics; totalEntries: number }) {
  const order = ['INFO', 'ERROR', 'WARN', 'DEBUG', 'TRACE', 'FATAL', 'CRITICAL'];
  const severityCounts = order.map((severity) => ({ severity, count: analytics.severity_counts[severity as keyof DatasetAnalytics['severity_counts']] ?? 0 }));
  const knownCount = severityCounts.reduce((sum, item) => sum + item.count, 0) + analytics.unparsed_entries;
  const distribution = severityCounts.concat([{ severity: 'UNPARSED', count: analytics.unparsed_entries }, { severity: 'UNCLASSIFIED', count: Math.max(0, totalEntries - knownCount) }]).filter((item) => item.count > 0);
  const circumference = 2 * Math.PI * 51;
  let offset = 0;
  return <section className="panel chart-panel severity-donut-panel" aria-label="Severity distribution by record count">
    <ChartHeading title="Severity distribution" subtitle="Composition of all log entries" note={`${totalEntries.toLocaleString()} entries`} />
    {distribution.length ? <div className="donut-content">
      <svg className="severity-donut" viewBox="0 0 132 132" role="img" aria-label={`Severity distribution across ${totalEntries} entries`}>
        <circle cx="66" cy="66" r="51" fill="none" stroke="#edf0f5" strokeWidth="15" />
        {distribution.map((item) => {
          const length = totalEntries > 0 ? (item.count / totalEntries) * circumference : 0;
          const currentOffset = offset;
          offset += length;
          return <circle key={item.severity} cx="66" cy="66" r="51" fill="none" stroke={item.severity === 'UNCLASSIFIED' ? '#c7ced9' : severityColors[item.severity]} strokeWidth="15" strokeDasharray={`${length} ${circumference - length}`} strokeDashoffset={-currentOffset} transform="rotate(-90 66 66)" />;
        })}
        <text x="66" y="63" textAnchor="middle" className="donut-total">{totalEntries.toLocaleString()}</text>
        <text x="66" y="79" textAnchor="middle" className="donut-caption">total entries</text>
      </svg>
      <div className="donut-legend">{distribution.map((item) => <div className="donut-legend-row" key={item.severity}>
        <span><i style={{ backgroundColor: item.severity === 'UNCLASSIFIED' ? '#c7ced9' : severityColors[item.severity] }} />{item.severity === 'UNPARSED' ? 'Unparsed' : item.severity === 'UNCLASSIFIED' ? 'Unclassified' : item.severity}</span>
        <strong>{item.count.toLocaleString()}<small>{totalEntries ? Math.round((item.count / totalEntries) * 100) : 0}%</small></strong>
      </div>)}</div>
    </div> : <div className="chart-empty">No entries are available for severity distribution.</div>}
    <div className="chart-footer"><span>Includes unparsed records</span></div>
  </section>;
}

function ActivityBars({ buckets, unit, onTimeBucket, loading }: { buckets: Bucket[]; unit: TimelineUnit; onTimeBucket: (bucket: Bucket) => void; loading: boolean }) {
  const maximum = Math.max(1, ...buckets.flatMap((bucket) => [bucket.error_count, bucket.warning_count]));
  const labels = selectTimelineLabelIndices(buckets.length, 5);
  const segmentWidth = plot.width / Math.max(buckets.length, 1);
  const barWidth = Math.min(9, Math.max(2, segmentWidth * .28));
  return <section className="panel chart-panel" aria-label="Error and warning counts over time">
    <ChartHeading title="Error & warning activity" subtitle="Recorded errors and warnings over time" />
    <div className="chart-plot-wrap">
      {buckets.length ? <svg className="data-chart" viewBox="0 0 640 178" role="group" aria-label="Grouped error and warning activity chart">
        <GridLines maximum={maximum} />
        {buckets.map((bucket, index) => {
          const center = plot.left + segmentWidth * (index + .5);
          const errorHeight = (bucket.error_count / maximum) * plot.height;
          const warningHeight = (bucket.warning_count / maximum) * plot.height;
          const base = plot.top + plot.height;
          return <g key={bucket.timestamp}>
            <rect x={center - barWidth - 1} y={base - errorHeight} width={barWidth} height={errorHeight} rx="2" fill={severityColors.ERROR} />
            <rect x={center + 1} y={base - warningHeight} width={barWidth} height={warningHeight} rx="2" fill={severityColors.WARN} />
            <rect x={plot.left + index * segmentWidth} y={plot.top} width={segmentWidth} height={plot.height} className="chart-hit-area" role="button" tabIndex={0} aria-label={`${displayTimestamp(bucket.timestamp)}; ${bucket.error_count} errors and ${bucket.warning_count} warnings`} onClick={() => onTimeBucket(bucket)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onTimeBucket(bucket); } }}><title>{displayTimestamp(bucket.timestamp)} · {bucket.error_count} errors · {bucket.warning_count} warnings</title></rect>
          </g>;
        })}
        {labels.map((index) => <text key={buckets[index].timestamp} x={plot.left + (buckets.length <= 1 ? plot.width / 2 : (index / (buckets.length - 1)) * plot.width)} y="165" textAnchor={index === 0 ? 'start' : index === buckets.length - 1 ? 'end' : 'middle'} className="chart-axis-label">{bucketLabel(buckets[index].timestamp, unit)}</text>)}
      </svg> : <div className="chart-empty">{loading ? 'Loading error and warning activity…' : 'No timestamped records are available for this dataset.'}</div>}
    </div>
    <div className="chart-footer"><SeriesLegend items={[{ key: 'ERROR', label: 'Errors', color: severityColors.ERROR }, { key: 'WARN', label: 'Warnings', color: severityColors.WARN }]} /><span>{unit === 'none' ? 'No time buckets' : `Per ${unit}`}</span></div>
  </section>;
}

function SeverityTrends({ buckets, unit, onTimeBucket, loading }: { buckets: Bucket[]; unit: TimelineUnit; onTimeBucket: (bucket: Bucket) => void; loading: boolean }) {
  const levels = ['INFO', 'ERROR', 'WARN', 'DEBUG', 'TRACE', 'FATAL', 'CRITICAL'];
  const series = levels.map((key) => ({ key, label: key, color: severityColors[key] }))
    .filter((item) => buckets.some((bucket) => (bucket.severity_counts[item.key] ?? 0) > 0));
  return <section className="panel chart-panel" aria-label="Severity trends over time">
    <ChartHeading title="Severity trends" subtitle="Severity counts by time bucket" note={unit === 'none' ? 'No time buckets' : `Per ${unit}`} />
    {buckets.length && series.length ? <LineChart buckets={buckets} unit={unit} series={series} onTimeBucket={onTimeBucket} label="Severity counts time series" /> : <div className="chart-empty">{loading ? 'Loading severity trends…' : buckets.length ? 'No classified severity counts are available for these time buckets.' : 'No timestamped records are available for this dataset.'}</div>}
    <div className="chart-footer"><SeriesLegend items={series} /><span>Select a time period to inspect entries</span></div>
  </section>;
}

export function DashboardCharts({ analytics, totalEntries, loading, onTimeBucket }: {
  analytics: DatasetAnalytics | null;
  totalEntries: number;
  loading: boolean;
  onTimeBucket: (bucket: Bucket) => void;
}) {
  const allBuckets = analytics?.timeline.buckets ?? [];
  const buckets = allBuckets.slice(-48);
  const unit = analytics?.timeline.bucket_unit ?? 'none';
  const analyticsReady = !!analytics && !loading;
  return <>
    {loading && !analytics && <div className="chart-loading" role="status">Loading dataset analytics…</div>}
    <div className="dashboard-charts-primary" aria-busy={loading}>
      <EventChart buckets={buckets} unit={unit} onTimeBucket={onTimeBucket} totalEntries={totalEntries} loading={loading} />
      {analyticsReady ? <SeverityDonut analytics={analytics} totalEntries={totalEntries} /> : <section className="panel chart-panel severity-donut-panel" aria-busy={loading}><ChartHeading title="Severity distribution" subtitle="Composition of all log entries" /><div className="chart-empty">{loading ? 'Calculating severity distribution…' : 'Severity data is not available.'}</div></section>}
    </div>
    {allBuckets.length > 48 && <p className="chart-window-note">Showing the latest 48 of {allBuckets.length.toLocaleString()} time buckets. All dataset totals remain available above.</p>}
    <div className="dashboard-charts-secondary" aria-busy={loading}>
      <ActivityBars buckets={buckets} unit={unit} onTimeBucket={onTimeBucket} loading={loading} />
      <SeverityTrends buckets={buckets} unit={unit} onTimeBucket={onTimeBucket} loading={loading} />
    </div>
  </>;
}
