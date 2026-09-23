// Fit — theses matched against Frederico's own stated research interests.
//
// Not Search. Search ranks PASSAGES against a question you type; this ranks
// THESES against a profile that persists, and answers a different question:
// "which of these could I write, and who would supervise it". Four things the
// backend encodes that this view must not flatten away:
//
//   1. Each interest is matched SEPARATELY (max-over-facets), so every result
//      can say WHICH interest pulled it in. That attribution is the evidence
//      the screen is built on — a single fused score could not produce it.
//   2. NO PERCENTAGE SCORE. Search.jsx renders `1 - distance` as "Match 67%",
//      which is right there and wrong here: all 18 of these are computing
//      PhDs, so they all land in a narrow band against any computing profile
//      (top-1 to top-5 spans 0.007 for the seeded profile) and a 67-vs-66 gap
//      would read as precision that does not exist. Rank out of the matchable
//      corpus, the matched interest, and the passage — nothing else.
//   3. A degraded store answers a typed 503, never an empty list. That matters
//      more here than in Search: a profile CAN legitimately match nothing.
//   4. An unresolved supervisor name is still a name. It renders, flagged —
//      never dropped, never guessed.
//
// Deliberately absent: any research-group filter or grouping (S7 measures
// group attribution at 3.72 of 6 groups per thesis — it would look
// authoritative and mean nothing), any supervisor ranking or leaderboard (the
// ceiling is 3 theses), and any generated prose.

import { useEffect, useState } from 'react';
import { ApiError, api } from '../api';
import { Caveat, ExternalLink, Section } from '../components';

const K = 8;

function Diagnostic({ error }) {
  const degraded = error instanceof ApiError && error.status === 503;
  return (
    <div className="card search-error" role="alert">
      <p className="chart-title search-error-title">
        {degraded ? 'Matching is unavailable right now' : 'Matching failed'}
      </p>
      <p className="chart-note">{error.message}</p>
      {degraded ? (
        <p className="chart-note">
          This is a backend problem, not a profile that matched nothing — try again shortly.
        </p>
      ) : null}
    </div>
  );
}

/** The people who supervised a matched thesis. An unresolved name still
 *  renders: it is a real person on a real thesis, and dropping it would
 *  quietly shrink the list of people he could approach. */
function Supervisors({ supervisors }) {
  if (!supervisors.length) {
    return <p className="chart-note">No supervisor recorded for this thesis.</p>;
  }
  return (
    <p className="chart-note">
      Supervised by{' '}
      {supervisors.map((s, i) => (
        <span key={s.name}>
          {i > 0 ? ', ' : ''}
          <strong>{s.name}</strong>
          {s.status === 'matched' ? null : (
            <span
              className="chip chip-warn"
              title={
                s.match_status === 'ambiguous'
                  ? 'More than one person in the CISUC data fits this name, and nothing separates them — so it is left unresolved rather than guessed.'
                  : 'This name does not resolve to anyone in the CISUC project data. Shown as recorded on the thesis.'
              }
            >
              {s.match_status === 'ambiguous' ? 'ambiguous' : 'unresolved'}
            </span>
          )}
        </span>
      ))}
    </p>
  );
}

function Result({ result, total }) {
  return (
    <div className="card search-result">
      <div className="search-result-head">
        <p className="chart-title">
          <span className="fit-rank">#{result.rank}</span>{' '}
          <ExternalLink href={result.source_url}>{result.title}</ExternalLink>
        </p>
        {result.full_text ? null : (
          <span
            className="chip chip-warn"
            title="The full text of this thesis was not indexed — only its title and abstracts."
          >
            Abstract only (embargoed)
          </span>
        )}
      </div>
      <p className="chart-note">
        Rank {result.rank} of {total} · matched your interest{' '}
        <strong>“{result.matched_interest}”</strong>
      </p>
      <Supervisors supervisors={result.supervisors} />
      {result.snippet ? (
        <p className="search-snippet">…{result.snippet}…</p>
      ) : (
        <p className="chart-note">No passage available for this thesis.</p>
      )}
    </div>
  );
}

/** The profile editor. The interest list is the input that actually drives
 *  the ranking; the prose below it is context he wrote and is never embedded
 *  (see uc_phd_app/profile.py — the career-narrative half of it is exactly
 *  what drags an averaged single-vector query off topic). */
function ProfileEditor({ profile, onSave, onReset, saving, error }) {
  const [text, setText] = useState(() => profile.interests.join('\n'));
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setText(profile.interests.join('\n'));
  }, [profile.interests]);

  const lines = text.split('\n').map((l) => l.trim()).filter(Boolean);
  const dirty = lines.join('\n') !== profile.interests.join('\n');

  return (
    <div className="card fit-profile">
      <div className="search-result-head">
        <p className="chart-title">Your research interests</p>
        {profile.differs_from_seed ? (
          <span className="chip chip-warn" title="You have edited this away from the version committed in the repo.">
            edited
          </span>
        ) : null}
      </div>
      <p className="chart-note">
        One interest per line. Each line is matched <strong>separately</strong> against every
        thesis and the best match wins, so a line about security cannot be diluted by a line
        about machine learning.
      </p>
      <textarea
        className="fit-interests"
        rows={Math.max(4, lines.length + 1)}
        value={text}
        aria-label="Your research interests, one per line"
        onChange={(e) => setText(e.target.value)}
      />
      {error ? (
        <p className="chart-note search-error-title" role="alert">{error.message}</p>
      ) : null}
      <div className="search-examples">
        <button
          type="button"
          className="group-pill"
          disabled={!dirty || saving || !lines.length}
          onClick={() => onSave(lines)}
        >
          {saving ? 'Saving…' : 'Save and re-match'}
        </button>
        {profile.differs_from_seed ? (
          <button type="button" className="group-pill" disabled={saving} onClick={onReset}>
            Reset to the committed profile
          </button>
        ) : null}
      </div>
      {profile.body ? (
        <>
          <button type="button" className="table-toggle" onClick={() => setOpen(!open)}>
            {open ? 'Hide' : 'Show'} the statement this came from
          </button>
          {open ? (
            <>
              <p className="search-snippet">{profile.body}</p>
              <p className="chart-note">
                Context only — this prose is deliberately <strong>not</strong> matched against.
                Only the interest lines above are.
              </p>
            </>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

export default function Fit() {
  const [profile, setProfile] = useState(null);
  const [fit, setFit] = useState(null);
  const [error, setError] = useState(null);
  const [saveError, setSaveError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  // One reload path for the first render and for every profile edit, so the
  // results on screen can never belong to a different profile than the
  // editor shows.
  const reload = async (mutate) => {
    setSaveError(null);
    if (mutate) setSaving(true);
    try {
      const next = mutate ? await mutate() : await api.profile();
      setProfile(next);
      setError(null);
      try {
        setFit(await api.fit(K));
      } catch (e) {
        setFit(null);
        setError(e);
      }
    } catch (e) {
      if (mutate) setSaveError(e);
      else setError(e);
    } finally {
      setSaving(false);
      setLoading(false);
    }
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading) return <p className="state">Loading…</p>;

  return (
    <Section
      title="Fit"
      note="Theses closest to your own stated research interests, with the people who supervised them. A matcher, not a ranking: it tells you which of the indexed theses sit nearest your interests and who to approach about them."
    >
      {profile ? (
        <ProfileEditor
          profile={profile}
          saving={saving}
          error={saveError}
          onSave={(lines) => reload(() => api.saveProfile(lines, undefined))}
          onReset={() => reload(() => api.resetProfile())}
        />
      ) : null}

      {fit ? (
        <Caveat label="What this searched">
          {fit.corpus_note}
          {fit.coverage.unmatchable
            ? ` ${fit.coverage.unmatchable} of them have no abstract and cannot be matched at all, so they appear nowhere in this list.`
            : ''}{' '}
          {fit.supervisor_note}
        </Caveat>
      ) : null}

      {error ? <Diagnostic error={error} /> : null}

      {fit && !fit.results.length ? (
        <p className="state">
          Nothing in the indexed corpus is close to these interests. That is a real answer at this
          corpus size — try wording an interest differently, or add one.
        </p>
      ) : null}

      {fit && fit.results.length ? (
        <>
          <p className="chart-note">
            {fit.results.length} closest of {fit.coverage.matchable} — embedded in {fit.embed_ms}ms,
            matched in {fit.db_ms}ms.
          </p>
          <div className="search-results">
            {fit.results.map((r) => (
              <Result key={r.handle} result={r} total={fit.coverage.matchable} />
            ))}
          </div>
        </>
      ) : null}
    </Section>
  );
}
