// Where the API lives, derived from where this page was served.
//
// The same bundle is loaded from two roots by the same sub-app:
//
//   subdomain     https://aw-app-uc-phd.app.<workspace>/        -> /api/...
//   path mount    https://<workspace>/api/apps/aw-app-uc-phd/   -> /api/apps/aw-app-uc-phd/api/...
//
// Stripping the last path segment gives the mount root in both cases (and for
// `.../index.html` too). Routing is hash-based, so location.pathname never
// changes while the app runs and this stays correct after navigation.

const MOUNT_ROOT = window.location.pathname.replace(/\/[^/]*$/, '/');

export function apiUrl(sub) {
  return `${MOUNT_ROOT}api${sub}`;
}

async function getJSON(sub) {
  const res = await fetch(apiUrl(sub), { headers: { Accept: 'application/json' } });
  if (!res.ok) {
    let detail = '';
    try {
      detail = (await res.json()).detail || '';
    } catch {
      /* a non-JSON error body is itself the useful signal — see below */
    }
    throw new Error(`GET ${sub} -> ${res.status}${detail ? `: ${detail}` : ''}`);
  }
  const type = res.headers.get('content-type') || '';
  if (!type.includes('application/json')) {
    // The static SPA is mounted at "/" and a Starlette Mount("/") matches
    // everything, so an API route registered after it would answer with
    // index.html instead of JSON. Name that failure here rather than letting
    // it surface as an opaque JSON parse error.
    throw new Error(
      `GET ${sub} returned ${type || 'no content-type'}, not JSON — the SPA's ` +
      `static mount is probably shadowing the API routes (see routes.py).`,
    );
  }
  return res.json();
}

export const api = {
  healthz: () => getJSON('').then(() => null),
  coverage: () => getJSON('/coverage'),
  groups: () => getJSON('/groups'),
  topProjects: () => getJSON('/top-projects'),
  funding: () => getJSON('/funding'),
  budgetByGroup: () => getJSON('/budget/by-group'),
  budgetByYear: () => getJSON('/budget/by-year'),
  timeline: () => getJSON('/timeline'),
  coordinators: () => getJSON('/coordinators'),
  partners: () => getJSON('/partners'),
  theses: () => getJSON('/theses'),
  thesesGroups: () => getJSON('/theses/groups'),
  projects: ({ group, q, limit = 50, offset = 0 } = {}) => {
    const params = new URLSearchParams();
    if (group) params.set('group', group);
    if (q) params.set('q', q);
    params.set('limit', String(limit));
    params.set('offset', String(offset));
    return getJSON(`/projects?${params}`);
  },
  project: (id) => getJSON(`/projects/${id}`),
};
