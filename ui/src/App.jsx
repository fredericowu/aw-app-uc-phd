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
import Bibliography from './views/Bibliography';
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
  { id: 'bibliography', label: 'Bibliography' },
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

// A person is reachable from five places, so their Back button means
// "wherever you came from" — but a deep-linked profile has no in-app origin
// to return to. Neither `history.length <= 1` nor a length captured once at
// load can tell those apart from a real predecessor: `history.length` is
// tab-global (an about:blank first entry from some new-tab flows already
// makes it 2), and it is identical before and after a full reload, so a
// reload-then-Back on a real predecessor falls through to the fallback.
//
// Instead the app stamps its own monotonic nav depth into `history.state`
// per entry — the same shape React Router v6 uses (`{ idx }`) — because
// state is per-entry and survives a full reload while `history.length`
// does not answer per-entry questions at all.
let lastNavDepth = null;
function syncNavDepth() {
  const state = window.history.state;
  if (state && typeof state.ucPhdIdx === 'number') {
    // Popped to (or reloaded on) an entry this app already stamped.
    lastNavDepth = state.ucPhdIdx;
    return;
  }
  lastNavDepth = lastNavDepth === null ? 0 : lastNavDepth + 1;
  // Two-argument replaceState only — this bundle is served from two
  // different roots (see the header comment and api.js), and a relative
  // URL third argument resolves differently under each, breaking deep
  // links on one of them. Spread the existing state rather than replacing
  // it wholesale, so this never collides with anything else that writes
  // history state later.
  window.history.replaceState({ ...state, ucPhdIdx: lastNavDepth }, '');
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

  // parseHash() builds a new object on every hashchange, so this fires on
  // the initial mount (seeding the landing entry at depth 0) and on every
  // subsequent navigation, push or pop — the one seam that covers go() and
  // PersonLink alike without either needing to call syncNavDepth itself.
  useEffect(() => {
    syncNavDepth();
  }, [route]);

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
    // "wherever you came from" — falling back to #/coordinators when this
    // entry has no in-app predecessor, which is exactly the deep-link case.
    // See syncNavDepth for why nav depth, not history.length, answers that.
    body = (
      <PersonDetail
        slug={route.personSlug}
        onBack={() =>
          ((window.history.state?.ucPhdIdx ?? 0) > 0
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
  } else if (route.tab === 'bibliography') {
    body = <Bibliography onOpenThesis={openThesis} />;
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
