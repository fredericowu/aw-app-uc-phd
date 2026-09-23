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
import PersonDetail from './views/PersonDetail';
import Fit from './views/Fit';

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'fit', label: 'Fit' },
  { id: 'groups', label: 'Research groups' },
  { id: 'coordinators', label: 'Coordinators & collaboration' },
  { id: 'partners', label: 'Partners' },
  { id: 'projects', label: 'Projects' },
  { id: 'theses', label: 'Theses' },
];

function parseHash() {
  const raw = window.location.hash.replace(/^#\/?/, '');
  const detail = /^projects\/(\d+)$/.exec(raw);
  if (detail) {
    return { tab: 'projects', projectId: Number(detail[1]), thesisHandle: null, personSlug: null };
  }
  const thesisDetail = /^theses\/(.+)$/.exec(raw);
  // location.hash never auto-decodes (unlike pathname), so the segments
  // openThesis() percent-encoded are still literal here — decode each one
  // back before rejoining, mirroring the encode on the way in.
  if (thesisDetail) {
    const handle = thesisDetail[1].split('/').map(decodeURIComponent).join('/');
    return { tab: 'theses', projectId: null, thesisHandle: handle, personSlug: null };
  }
  // A detail route like #/projects/{id}, NOT a tab — people are reached by
  // clicking a name, never from the nav. `tab: 'coordinators'` keeps the nav
  // highlight on the section people actually live under, the same way the
  // project route returns `tab: 'projects'`. A slug carries no slash, so one
  // decodeURIComponent is the whole mirror of PersonLink's encode.
  const personDetail = /^people\/(.+)$/.exec(raw);
  if (personDetail) {
    return {
      tab: 'coordinators',
      projectId: null,
      thesisHandle: null,
      personSlug: decodeURIComponent(personDetail[1]),
    };
  }
  const tab = TABS.find((t) => t.id === raw);
  return { tab: tab ? tab.id : 'overview', projectId: null, thesisHandle: null, personSlug: null };
}

// How long the tab's history already was when this document loaded. A person
// is reachable from five places, so their Back button means "wherever you came
// from" — but a deep-linked profile has no in-app origin to return to, and
// `history.length <= 1` does not detect that reliably: a tab opened
// programmatically (or by some browsers' new-tab flow) carries an about:blank
// entry first, so length is already 2 and back() lands on a blank page.
// Verified live — Playwright's own new tab does exactly that. Comparing
// against the length at load answers the real question ("has this session
// navigated inside the app yet?") in every one of those cases.
const HISTORY_LENGTH_AT_LOAD = window.history.length;

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
  } else if (route.personSlug != null) {
    // ProjectDetail/ThesisDetail hard-code their origin because each is
    // reached from one place. A person is reached from five, so Back means
    // "wherever you came from" — falling back to #/coordinators when this tab
    // never navigated inside the app, which is exactly the deep-link case.
    // See HISTORY_LENGTH_AT_LOAD for why that, not `history.length <= 1`.
    body = (
      <PersonDetail
        slug={route.personSlug}
        onBack={() =>
          (window.history.length > HISTORY_LENGTH_AT_LOAD
            ? window.history.back()
            : go('#/coordinators'))
        }
      />
    );
  } else if (route.tab === 'fit') {
    body = <Fit />;
  } else if (route.tab === 'groups') {
    body = <Groups />;
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
        <TopProjects onOpenProject={openProject} />
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
