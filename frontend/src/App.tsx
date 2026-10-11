import { useCallback, useEffect, useState } from 'react';

type ConnectionState = 'loading' | 'connected' | 'error';
type HealthResponse = { status: string };

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

export default function App() {
  const [connection, setConnection] = useState<ConnectionState>('loading');
  const [attempt, setAttempt] = useState(0);

  const checkBackend = useCallback(async (signal: AbortSignal) => {
    setConnection('loading');
    try {
      const response = await fetch(`${apiBaseUrl}/health`, { signal });
      if (!response.ok) throw new Error(`Backend returned HTTP ${response.status}`);
      const result = (await response.json()) as HealthResponse;
      if (result.status !== 'healthy') throw new Error('Backend health check did not pass');
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
        <p className="intro">A clearer way to explore application logs. LogLens is getting ready to turn noisy events into useful evidence.</p>

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

        <div className="next-step">
          <span className="next-step-index">01</span>
          <div><strong>A better view of your logs</strong><p>Upload, filter, and understand — all in one place.</p></div>
          <span className="next-step-arrow" aria-hidden="true">↗</span>
        </div>
      </section>
      <footer><span>LOG LENS <span className="footer-dot">·</span> PHASE 1</span><span>Built for clearer debugging</span></footer>
    </main>
  );
}
