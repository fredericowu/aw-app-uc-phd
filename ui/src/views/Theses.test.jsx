// The expand/collapse control on the "Resolved to a research group" tile —
// the `+ N more` / "Show fewer" pattern already used by Search.jsx's
// passage list and (in-flight, same shape) Overview.jsx's "No detail page"
// tile. Everything it reveals comes from `api.theses()`'s own payload, so
// the only thing worth asserting is that `!t.attributed` is what the toggle
// filters on and that a revealed row still reuses `onOpenThesis`.

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Theses from './Theses';

const THESES = [
  { handle: 'a', title: 'Resolved Thesis', attributed: true, full_text: true, authors: [], supervisors: [], year: 2020, groups: ['AC'] },
  { handle: 'b', title: 'Unattributed Thesis One', attributed: false, full_text: true, authors: [], supervisors: [], year: 2021, groups: [] },
  { handle: 'c', title: 'Unattributed Thesis Two', attributed: false, full_text: false, authors: [], supervisors: [], year: 2022, groups: [] },
];

vi.mock('../api', () => ({
  api: {
    theses: () =>
      Promise.resolve({
        theses: THESES,
        attribution_tiers: {},
        identity_coverage: null,
        identity_note: '',
        attribution_note: '',
      }),
    thesesGroups: () =>
      Promise.resolve({
        groups: [{ code: 'AC', name: 'Adaptive Computation', thesis_count: 1 }],
        unattributed: 2,
        caveat: '',
      }),
    search: () => Promise.resolve({ results: [] }),
  },
  ApiError: class ApiError extends Error {},
}));

describe('Theses — unattributed expand control', () => {
  it('reveals exactly the unattributed theses on click, and collapses back on "Show fewer"', async () => {
    const user = userEvent.setup();
    const onOpenThesis = vi.fn();
    render(<Theses onOpenThesis={onOpenThesis} />);

    const toggle = await screen.findByRole('button', { name: '+ 2 more' });
    // Both unattributed titles already appear once each, as rows in the big
    // "All N theses" table at the bottom of this same view — the expand
    // control is additive, so collapsed state means exactly one occurrence.
    expect(screen.getAllByText('Unattributed Thesis One')).toHaveLength(1);
    expect(screen.getAllByText('Unattributed Thesis Two')).toHaveLength(1);

    await user.click(toggle);

    expect(await screen.findAllByText('Unattributed Thesis One')).toHaveLength(2);
    expect(screen.getAllByText('Unattributed Thesis Two')).toHaveLength(2);
    // The attributed thesis must never show up in the revealed list.
    expect(screen.getAllByText('Resolved Thesis')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Show fewer' })).toBeInTheDocument();

    // Clicking a revealed row reuses the same onOpenThesis the big table uses.
    await user.click(screen.getAllByRole('button', { name: 'Unattributed Thesis One' })[0]);
    expect(onOpenThesis).toHaveBeenCalledWith('b');

    await user.click(screen.getByRole('button', { name: 'Show fewer' }));
    expect(screen.getAllByText('Unattributed Thesis One')).toHaveLength(1);
    expect(screen.getByRole('button', { name: '+ 2 more' })).toBeInTheDocument();
  });
});
