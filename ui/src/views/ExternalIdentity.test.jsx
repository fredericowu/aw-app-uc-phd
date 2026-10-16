// The "(unattributed)" seam, after the 45-name sweep gave 29 of those names a
// researched person (analysis/external_people.py). Three states have to stay
// distinct, and the whole point of the change is that they look different:
//
//   1. matched           — a profile link, no marker at all.
//   2. unattributed + external — the researched name, marked "external", with
//      the source. NOT a profile link: there is no person_slug behind it and
//      there never will be, so a reader must not read it as attributed.
//   3. unattributed, no external — the bare "(unattributed)" it always was.
//      Still the right answer for the 4 ambiguous names and for Álvaro Rocha,
//      a real CISUC person missing from the directory snapshot.
//
// Both views are asserted because they render it two ways on purpose (the
// table compacts the affiliation into a tooltip, the detail view shows it)
// and the shared `ExternalIdentity` is what keeps them from wording it twice.

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Theses from './Theses';
import ThesisDetail from './ThesisDetail';

const EXTERNAL = {
  display_name: 'Torsten Braun',
  affiliation: 'University of Bern',
  source_url: 'https://example.test/braun',
  note: null,
};

const PEOPLE = [
  { name: 'Braun, Torsten', status: 'unattributed', match_status: 'unmatched', matched: [], note: 'nobody fits', external: EXTERNAL },
  { name: 'Nobody, Researched', status: 'unattributed', match_status: 'ambiguous', matched: [], note: 'two rows fit' },
  { name: 'Lovelace, Ada', status: 'matched', match_status: 'exact', matched: [{ slug: 'ada', name: 'Ada Lovelace' }], note: 'exact' },
];

const THESIS = {
  handle: 'a', title: 'A Thesis', attributed: true, full_text: false, year: 2020,
  groups: ['AC'], authors: PEOPLE, supervisors: [], source_url: 'https://example.test/t',
  rights: 'openAccess', abstract_en: null, abstract_pt: null, group_attribution: { tier: 'people-only', ranked: [{ code: 'AC' }] },
};

vi.mock('../api', () => ({
  api: {
    theses: () => Promise.resolve({
      theses: [{ ...THESIS }], attribution_tiers: {}, identity_coverage: null,
      identity_note: '', attribution_note: '',
    }),
    thesesGroups: () => Promise.resolve({ groups: [], unattributed: 0, caveat: '' }),
    search: () => Promise.resolve({ results: [] }),
    thesis: () => Promise.resolve({ ...THESIS }),
    thesisBody: () => Promise.resolve(null),
  },
  ApiError: class ApiError extends Error {},
}));

describe('a researched external identity replaces the bare "(unattributed)"', () => {
  it('names the person in the theses table, compactly, and keeps the bare label for a name nobody looked up', async () => {
    render(<Theses onOpenThesis={vi.fn()} />);
    await screen.findByText('A Thesis');

    // The researched name is shown and the bare label is NOT — they would
    // read as a defect sitting beside the answer to it.
    expect(screen.getByText(/Torsten Braun \(external\)/)).toBeInTheDocument();
    // The thesis's own name_raw still renders next to it: the reader is
    // looking at the thesis, and substituting a different string would make
    // the two disagree.
    expect(screen.getByText('Braun, Torsten')).toBeInTheDocument();
    // The affiliation rides in the tooltip at this width, not on the row.
    expect(screen.getByTitle(/External to CISUC — University of Bern/)).toBeInTheDocument();

    // ...and the unresearched name keeps exactly what it had.
    expect(screen.getByText('(unattributed)')).toBeInTheDocument();
  });

  it('shows the affiliation and a source link in the detail view', async () => {
    render(<ThesisDetail handle="a" onBack={vi.fn()} />);
    await screen.findByText('A Thesis');

    expect(screen.getByText(/Torsten Braun/)).toBeInTheDocument();
    expect(screen.getByText(/\(external — University of Bern\)/)).toBeInTheDocument();
    const source = screen.getByRole('link', { name: /source/i });
    expect(source).toHaveAttribute('href', 'https://example.test/braun');
    expect(screen.getByText('(unattributed)')).toBeInTheDocument();
  });

  it('never turns an external identity into a profile link', async () => {
    render(<ThesisDetail handle="a" onBack={vi.fn()} />);
    await screen.findByText('A Thesis');

    // The matched person gets one; the external one must not, because there
    // is no slug to send the reader to.
    expect(screen.getByRole('link', { name: 'Lovelace, Ada' })).toHaveAttribute(
      'href', '#/people/ada',
    );
    const profileLinks = screen.getAllByRole('link').filter(
      (a) => (a.getAttribute('href') || '').startsWith('#/people/'),
    );
    expect(profileLinks).toHaveLength(1);
  });

  it('carries who the person is in the tooltip even where only the name is rendered', async () => {
    // ResolvedPersonName is shared by six views and only two render the full
    // ExternalIdentity, so the researched person has to reach the others.
    const user = userEvent.setup();
    render(<Theses onOpenThesis={vi.fn()} />);
    await screen.findByText('A Thesis');
    await user.hover(screen.getByText('Braun, Torsten'));
    expect(screen.getByTitle(/Torsten Braun — University of Bern/)).toBeInTheDocument();
  });
});
