import type { InvestigationWorkflow } from './api';

export function InvestigationWorkflowPanel({ workflow, loading, error, selectedNode, onSelectNode, onRetry, onFocusLine }: {
  workflow: InvestigationWorkflow | null;
  loading: boolean;
  error: string;
  selectedNode: string | null;
  onSelectNode: (id: string | null) => void;
  onRetry: () => void;
  onFocusLine: (line: number) => void;
}) {
  if (!loading && !error && !workflow) return null;
  return <section className="workflow-panel panel" aria-label="AI troubleshooting workflow" aria-busy={loading}>
    <div className="workflow-heading"><div><span className="panel-kicker">STRUCTURED INVESTIGATION</span><h2>{workflow?.title ?? 'Troubleshooting workflow'}</h2></div>{workflow && <span className="workflow-safety">Suggested steps · root cause unconfirmed</span>}</div>
    {loading && <p className="assistant-status" role="status"><span className="spinner" /> Reviewing selected error and nearby log evidence…</p>}
    {error && <p className="form-error" role="alert">{error} <button type="button" onClick={onRetry}>Retry</button></p>}
    {workflow && <>
      <p className="workflow-summary">{workflow.summary}</p>
      {workflow.source_context_used && <p className="workflow-caution">Relevant source snippets were included by your request. Code evidence does not establish runtime behavior.</p>}
      <div className="workflow-graph" role="list" aria-label="Investigation steps">
        {workflow.nodes.map((node, index) => <div className="workflow-node-wrap" key={node.id}>
          <article className={`workflow-node ${selectedNode === node.id ? 'selected' : ''}`} role="listitem">
            <button type="button" className="workflow-node-toggle" onClick={() => onSelectNode(selectedNode === node.id ? null : node.id)} aria-expanded={selectedNode === node.id}>
              <span className="workflow-status-line"><span className="node-step">{String(index + 1).padStart(2, '0')}</span><span className={`workflow-status ${node.status}`}>{node.status.replace('_', ' ')}</span></span>
              <strong>{node.title}</strong><small>{node.kind.replaceAll('_', ' ')}</small>
            </button>
            {selectedNode === node.id && <div className="workflow-description">{node.description}
              {node.evidence_lines.length > 0 && <div className="workflow-lines">Log evidence: {node.evidence_lines.map((line) => <span key={line}><button type="button" className="line-link" onClick={() => onFocusLine(line)}>Line {line}</button>{' '}</span>)}</div>}
              {node.source_refs.length > 0 && <div className="workflow-lines">Source evidence: {node.source_refs.map((reference) => <span key={reference}><a href={`#source-${reference}`}>{workflow.source_evidence.find((item) => item.reference === reference)?.file_path ?? reference}</a>{' '}</span>)}</div>}
            </div>}
          </article>
          {workflow.edges.filter((edge) => edge.source === node.id).map((edge) => <button type="button" className="workflow-edge" key={`${edge.source}-${edge.target}`} onClick={() => onSelectNode(edge.target)} aria-label={`Follow ${edge.label || 'workflow edge'} to ${workflow.nodes.find((target) => target.id === edge.target)?.title ?? edge.target}`}><span aria-hidden="true">→</span> {edge.label || 'Continue to'} <strong>{workflow.nodes.find((target) => target.id === edge.target)?.title ?? edge.target}</strong></button>)}
        </div>)}
      </div>
      <p className="workflow-caution">Recommendations are investigation ideas, not confirmed causes. Verify them against the application and infrastructure.</p>
      {workflow.limitations.length > 0 && <ul className="workflow-limitations">{workflow.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul>}
      {workflow.evidence.length > 0 && <div className="evidence-list"><strong>Validated log evidence</strong>{workflow.evidence.map((item) => <div className="evidence-item" key={item.id}>
        <span><button type="button" className="line-link" onClick={() => onFocusLine(item.line_number)}>Line {item.line_number}</button>{item.severity ? ` · ${item.severity}` : ''}</span><p>{item.parsed ? item.message : item.raw_line ?? item.message}</p>{!item.parsed && <small>Unparsed original text; structured fields are unavailable.</small>}
      </div>)}</div>}
      {workflow.source_evidence.length > 0 && <div className="evidence-list source-evidence"><strong>Source-code evidence · code observations do not prove runtime behavior</strong>{workflow.source_evidence.map((item) => <div className="evidence-item" id={`source-${item.reference}`} key={item.reference}>
        <span>{item.reference} · {item.file_path} · chunk {item.chunk_index + 1}</span><pre>{item.content}</pre>
      </div>)}</div>}
      {workflow.verification_steps.length > 0 && <div className="workflow-verifications"><strong>Verification steps</strong><ol>{workflow.verification_steps.map((step, index) => <li key={index}>{step}</li>)}</ol></div>}
    </>}
  </section>;
}
