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

/** Thrown by `api.search` — carries the HTTP status and the parsed error
 *  body (`{error, reason}` for a degraded-store 503) so a caller can tell
 *  "the search backend is broken" apart from a generic fetch failure
 *  instead of matching on message text. */
export class ApiError extends Error {
  constructor(message, { status, body } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

async function readJSON(res) {
  const type = res.headers.get('content-type') || '';
  if (!type.includes('application/json')) return null;
  try {
    return await res.json();
  } catch {
    return null;
  }
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
  // Not `getJSON`: a degraded store answers a typed 503 with a structured
  // `{error, reason}` detail (see uc_phd_app/api/search.py), and that shape
  // is the signal a caller needs to render a diagnostic instead of a
  // generic error string.
  search: async (q, k = 20) => {
    const params = new URLSearchParams({ q, k: String(k) });
    const res = await fetch(apiUrl(`/search?${params}`), { headers: { Accept: 'application/json' } });
    const body = await readJSON(res);
    if (!res.ok) {
      const detail = body && body.detail;
      const message = (detail && (detail.reason || detail.error))
        || `search failed (HTTP ${res.status})`;
      throw new ApiError(message, { status: res.status, body: detail });
    }
    if (!body) {
      throw new ApiError(
        `GET /search returned a non-JSON response — the SPA's static mount is ` +
        `probably shadowing the API routes (see routes.py).`,
        { status: res.status },
      );
    }
    return body;
  },
  profile: () => getJSON('/profile'),
  saveProfile: (interests, body) => sendJSON('PUT', '/profile', { interests, body }),
  resetProfile: () => sendJSON('POST', '/profile/reset'),
  // Same reasoning as `search`: a degraded store answers a typed 503 and that
  // structured detail is what the screen needs to tell "the matcher is broken"
  // apart from "your profile genuinely matched nothing" — which, unlike
  // search, is a legitimate answer here.
  fit: (k = 8) => sendJSON('GET', `/fit?k=${k}`),
};

/** The `search`-style error contract for the routes that need it: throws an
 *  ApiError carrying the parsed `{error, reason}` body on a non-2xx, and
 *  names the static-mount shadowing failure explicitly on a non-JSON reply. */
async function sendJSON(method, sub, payload) {
  const init = { method, headers: { Accept: 'application/json' } };
  if (payload !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(payload);
  }
  const res = await fetch(apiUrl(sub), init);
  const body = await readJSON(res);
  if (!res.ok) {
    const detail = body && body.detail;
    const message =
      (detail && (detail.reason || detail.error || (typeof detail === 'string' ? detail : null)))
      || `${method} ${sub} failed (HTTP ${res.status})`;
    throw new ApiError(message, { status: res.status, body: detail });
  }
  if (!body) {
    throw new ApiError(
      `${method} ${sub} returned a non-JSON response — the SPA's static mount is `
      + `probably shadowing the API routes (see routes.py).`,
      { status: res.status },
    );
  }
  return body;
}
