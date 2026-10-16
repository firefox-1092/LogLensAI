import type { ReactNode } from 'react';
import type { UploadSummary } from './api';

export type WorkspaceSection = 'home' | 'log-explorer' | 'analytics' | 'ai-investigator';
export type BackendHealth = 'loading' | 'connected' | 'error';

const navigation: Array<{ id: WorkspaceSection; label: string; icon: 'overview' | 'explorer' | 'analytics' | 'investigator' }> = [
  { id: 'home', label: 'Overview', icon: 'overview' },
  { id: 'log-explorer', label: 'Log Explorer', icon: 'explorer' },
  { id: 'analytics', label: 'Analytics', icon: 'analytics' },
  { id: 'ai-investigator', label: 'AI Investigator', icon: 'investigator' },
];

function NavIcon({ name }: { name: (typeof navigation)[number]['icon'] }) {
  const common = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  return <svg aria-hidden="true" viewBox="0 0 20 20" width="18" height="18" {...common}>
    {name === 'overview' && <><rect x="2.5" y="2.5" width="6" height="6" rx="1" /><rect x="11.5" y="2.5" width="6" height="6" rx="1" /><rect x="2.5" y="11.5" width="6" height="6" rx="1" /><rect x="11.5" y="11.5" width="6" height="6" rx="1" /></>}
    {name === 'explorer' && <><circle cx="8.5" cy="8.5" r="5.5" /><path d="m13 13 4 4M6 8.5h5M8.5 6v5" /></>}
    {name === 'analytics' && <><path d="M3 16.5V10m5 6.5V4m5 12.5V7m5 9.5H2" /></>}
    {name === 'investigator' && <><circle cx="10" cy="4" r="2" /><circle cx="4" cy="15.5" r="2" /><circle cx="16" cy="15.5" r="2" /><path d="M10 6v3m0 0H4v4.5m6-4.5h6v4.5" /></>}
  </svg>;
}

function sectionTitle(section: WorkspaceSection): string {
  return navigation.find((item) => item.id === section)?.label ?? 'Overview';
}

export function AppShell({ children, section, health, datasets, dataset, datasetsLoading, mobileNavOpen, onSelectDataset, onSectionChange, onToggleMobileNav, onCloseMobileNav, onRetryHealth, onUploadClick }: {
  children: ReactNode;
  section: WorkspaceSection;
  health: BackendHealth;
  datasets: UploadSummary[];
  dataset: UploadSummary | null;
  datasetsLoading: boolean;
  mobileNavOpen: boolean;
  onSelectDataset: (id: string) => void;
  onSectionChange: (section: WorkspaceSection) => void;
  onToggleMobileNav: () => void;
  onCloseMobileNav: () => void;
  onRetryHealth: () => void;
  onUploadClick: () => void;
}) {
  const healthLabel = health === 'connected' ? 'Connected' : health === 'loading' ? 'Connecting' : 'Offline';
  return <div className="page-shell">
    <aside className={`app-sidebar ${mobileNavOpen ? 'mobile-open' : ''}`}>
      <a className="brand" href="#home" aria-label="LogLens home" onClick={onCloseMobileNav}>
        <span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M3 12h4l2.2-5 4.1 10 2.1-5H21" /></svg></span><span>LogLens<span className="brand-period">.</span></span>
      </a>
      <div className="sidebar-dataset">
        <label htmlFor="sidebar-dataset-select">DATASET</label>
        <select id="sidebar-dataset-select" aria-label="Select uploaded dataset" value={dataset?.id ?? ''} onChange={(event) => onSelectDataset(event.target.value)} disabled={datasetsLoading || datasets.length === 0}>
          {!datasets.length && <option value="">{datasetsLoading ? 'Loading datasets…' : 'No dataset selected'}</option>}
          {datasets.map((item) => <option key={item.id} value={item.id}>{item.filename}</option>)}
        </select>
      </div>
      <div className="sidebar-divider" />
      <p className="sidebar-caption">WORKSPACE</p>
      <nav className="workspace-nav" aria-label="Workspace sections">
        {navigation.map((item) => <button key={item.id} type="button" className={section === item.id ? 'active' : ''} aria-current={section === item.id ? 'page' : undefined} onClick={() => { onSectionChange(item.id); onCloseMobileNav(); }}>
          <NavIcon name={item.icon} /><span>{item.label}</span>{item.id === 'ai-investigator' && <span className="nav-tag">AI</span>}
        </button>)}
      </nav>
      <div className="sidebar-current">
        <span className="sidebar-current-label">CURRENT DATASET</span>
        <strong title={dataset?.filename}>{dataset?.filename ?? 'Nothing selected'}</strong>
        <small>{dataset ? `${dataset.total_entries.toLocaleString()} entries · persisted` : 'Upload a log file to begin'}</small>
      </div>
      <div className="sidebar-footer"><span className={`health-dot ${health}`} /><span>{health === 'connected' ? 'API connected' : health === 'loading' ? 'Checking API' : 'API unavailable'}</span></div>
    </aside>
    {mobileNavOpen && <button type="button" className="sidebar-backdrop" aria-label="Close navigation" onClick={onCloseMobileNav} />}
    <div className="app-main">
      <header className="topbar">
        <button type="button" className="mobile-menu" aria-label={mobileNavOpen ? 'Close navigation' : 'Open navigation'} aria-expanded={mobileNavOpen} onClick={onToggleMobileNav}>{mobileNavOpen ? '×' : '☰'}</button>
        <div className="topbar-breadcrumb"><span>Workspace</span><span className="breadcrumb-separator" aria-hidden="true">›</span><strong>{sectionTitle(section)}</strong>{dataset && <span className="topbar-dataset">{dataset.filename}</span>}</div>
        <div className="topbar-actions">
          <div className={`header-health ${health}`} role="status" aria-live="polite"><i />{healthLabel}{health === 'error' && <button type="button" onClick={onRetryHealth}>Retry</button>}</div>
          <button type="button" className="topbar-upload" onClick={onUploadClick}><span aria-hidden="true">↑</span>Upload logs</button>
        </div>
      </header>
      <main id="main-content" className="app-content" data-section={section}>{children}
        <footer className="app-footer"><span>LogLens <span className="footer-separator">/</span> Application log intelligence</span><span>{dataset ? 'Selected dataset · live backend data' : 'No dataset selected'}</span></footer>
      </main>
    </div>
  </div>;
}
