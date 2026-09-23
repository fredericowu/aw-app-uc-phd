// Shell: nav, theme toggle, and hash routing.
//
// Hash routing rather than the History API, deliberately. This bundle is
// served by StaticFiles(html=True) from two different roots (see api.js), and
// a real path route would need the server to rewrite deep links for both. A
// hash keeps location.pathname constant, so deep links work unchanged on the
// subdomain and on the /api/apps/aw-app-uc-phd/ mount.

import { useEffect, useState } from 'react';
import Overview from './views/Overview';
import Groups from './views/Groups';
import TopProjects from './views/TopProjects';
import Money from './views/Money';
import Coordinators from './views/Coordinators';
import Collab from './views/Collab';
import Partners from './views/Partners';
import Projects from './views/Projects';
import ProjectDetail from './views/ProjectDetail';
import Theses from './views/Theses';
import ThesisDetail from './views/ThesisDetail';
import Search from './views/Search';
import Fit from './views/Fit';

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'search', label: 'Search' },
  { id: 'fit', label: 'Fit' },
  { id: 'groups', label: 'Research groups' },
  { id: 'top', label: 'Top 10 per group' },
  { id: 'coordinators', label: 'Coordinators & collaboration' },
  { id: 'partners', label: 'Partners' },
  { id: 'projects', label: 'All projects' },
  { id: 'theses', label: 'Theses' },
];

function parseHash() {
  const raw = window.location.hash.replace(/^#\/?/, '');
  const detail = /^projects\/(\d+)$/.exec(raw);
  if (detail) return { tab: 'projects', projectId: Number(detail[1]), thesisHandle: null };
  const thesisDetail = /^theses\/(.+)$/.exec(raw);
  // location.hash never auto-decodes (unlike pathname), so the segments
  // openThesis() percent-encoded are still literal here — decode each one
  // back before rejoining, mirroring the encode on the way in.
  if (thesisDetail) {
    const handle = thesisDetail[1].split('/').map(decodeURIComponent).join('/');
    return { tab: 'theses', projectId: null, thesisHandle: handle };
  }
  const tab = TABS.find((t) => t.id === raw);
  return { tab: tab ? tab.id : 'overview', projectId: null, thesisHandle: null };
}

function useTheme() {
  const [theme, setTheme] = useState(() => localStorage.getItem('uc-phd-theme') || 'system');
  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', theme);
    localStorage.setItem('uc-phd-theme', theme);
  }, [theme]);
  return [theme, setTheme];
}

export default function App() {
  const [route, setRoute] = useState(parseHash);
  const [theme, setTheme] = useTheme();

  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const go = (hash) => {
    window.location.hash = hash;
  };

  const openProject = (id) => go(`#/projects/${id}`);
  // Handles contain a slash ("10316/000001"): encode each segment on its
  // own and rejoin with a literal "/", never encodeURIComponent(handle)
  // whole — that would escape the slash itself and stop matching the
  // backend's {handle:path} route.
  const openThesis = (handle) => go(`#/theses/${handle.split('/').map(encodeURIComponent).join('/')}`);

  let body;
  if (route.projectId != null) {
    body = <ProjectDetail projectId={route.projectId} onBack={() => go('#/projects')} />;
  } else if (route.thesisHandle != null) {
    body = <ThesisDetail handle={route.thesisHandle} onBack={() => go('#/theses')} />;
  } else if (route.tab === 'search') {
    body = <Search onOpenThesis={openThesis} />;
  } else if (route.tab === 'fit') {
    body = <Fit />;
  } else if (route.tab === 'groups') {
    body = <Groups />;
  } else if (route.tab === 'top') {
    body = <TopProjects onOpenProject={openProject} />;
  } else if (route.tab === 'coordinators') {
    body = (
      <>
        <Coordinators />
        <Collab />
      </>
    );
  } else if (route.tab === 'partners') {
    body = <Partners />;
  } else if (route.tab === 'projects') {
    body = (
      <>
        <Projects onOpenProject={openProject} />
        <Money />
      </>
    );
  } else if (route.tab === 'theses') {
    body = <Theses onOpenThesis={openThesis} />;
  } else {
    body = <Overview />;
  }

  const nextTheme = { system: 'light', light: 'dark', dark: 'system' }[theme];
  const themeLabel = { system: 'Theme: system', light: 'Theme: light', dark: 'Theme: dark' }[theme];

  return (
    <div className="app">
      <header className="header">
        <h1>UC PhD Projects</h1>
        <p className="subtitle">
          Every research project at CISUC / UC DEI. Each figure comes from a committed SQL query
          against the scraped database — no number here is hand-typed.
        </p>
        <span className="spacer" />
        <button type="button" className="theme-toggle" onClick={() => setTheme(nextTheme)}>
          {themeLabel}
        </button>
      </header>

      <nav className="nav">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            aria-current={route.tab === t.id ? 'page' : undefined}
            onClick={() => go(`#/${t.id}`)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main className="main">{body}</main>
    </div>
  );
}
