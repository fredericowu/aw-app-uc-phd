// Component-level coverage for the "All N theses" table's sort/filter UI —
// thesesTable.test.js covers the pure logic; this exercises the actual
// rendered headers, pills and author combobox a user clicks.

import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Theses from './Theses';

const THESES = [
  {
    handle: 'z',
    title: 'Zebra Thesis',
    attributed: true,
    full_text: false,
    year: 2019,
    authors: [{ name: 'Zeca Afonso', status: 'matched', matched: [{ slug: 'zeca-afonso' }] }],
    supervisors: [],
    groups: ['AC'],
  },
  {
    handle: 'a',
    title: 'Ana Thesis',
    attributed: true,
    full_text: true,
    year: 2021,
    authors: [{ name: 'Ana Reis', status: 'matched', matched: [{ slug: 'ana-reis' }] }],
    supervisors: [],
    groups: ['CMS'],
  },
  {
    handle: 'n',
    title: 'No Year Thesis',
    attributed: false,
    full_text: true,
    year: null,
    authors: [{ name: 'Nuno Silva', status: 'unmatched', matched: [] }],
    supervisors: [],
    groups: [],
  },
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
      Promise.resolve({ groups: [{ code: 'AC', name: 'Adaptive Computation', thesis_count: 1 }], unattributed: 1, caveat: '' }),
    search: () => Promise.resolve({ results: [] }),
  },
  ApiError: class ApiError extends Error {},
}));

function tableRowTitles() {
  return screen.getAllByRole('row').slice(1).map((row) => within(row).queryAllByRole('button')[0]?.textContent);
}

describe('Theses table — sorting', () => {
  it('cycles a column header asc -> desc -> none (original order)', async () => {
    const user = userEvent.setup();
    render(<Theses onOpenThesis={() => {}} />);
    await screen.findByText('All 3 theses');
    expect(tableRowTitles()).toEqual(['Zebra Thesis', 'Ana Thesis', 'No Year Thesis']);

    // Scoped to the "Year" <th> itself — a row title (e.g. "No Year Thesis")
    // would also match a loose /Year/ name search.
    const yearHeader = () => screen.getByRole('columnheader', { name: /^Year/ });
    const clickYearSort = () => user.click(within(yearHeader()).getByRole('button'));

    await clickYearSort();
    expect(yearHeader()).toHaveAttribute('aria-sort', 'ascending');
    // Missing year sorts last ascending.
    expect(tableRowTitles()).toEqual(['Zebra Thesis', 'Ana Thesis', 'No Year Thesis']);

    await clickYearSort();
    expect(yearHeader()).toHaveAttribute('aria-sort', 'descending');
    // Missing year STILL sorts last, descending too.
    expect(tableRowTitles()).toEqual(['Ana Thesis', 'Zebra Thesis', 'No Year Thesis']);

    await clickYearSort();
    expect(yearHeader()).toHaveAttribute('aria-sort', 'none');
    expect(tableRowTitles()).toEqual(['Zebra Thesis', 'Ana Thesis', 'No Year Thesis']);
  });

  it('shows Clear filters when only a sort is active (no filter), and it resets the sort', async () => {
    const user = userEvent.setup();
    render(<Theses onOpenThesis={() => {}} />);
    await screen.findByText('All 3 theses');

    const yearHeader = () => screen.getByRole('columnheader', { name: /^Year/ });
    await user.click(within(yearHeader()).getByRole('button'));
    expect(yearHeader()).toHaveAttribute('aria-sort', 'ascending');
    expect(await screen.findByText('3 of 3 theses')).toBeInTheDocument();

    const clearButton = screen.getByRole('button', { name: 'Clear filters' });
    await user.click(clearButton);

    expect(await screen.findByText('All 3 theses')).toBeInTheDocument();
    expect(yearHeader()).toHaveAttribute('aria-sort', 'none');
    expect(screen.queryByRole('button', { name: 'Clear filters' })).not.toBeInTheDocument();
  });
});

describe('Theses table — group filter', () => {
  it('filters to the pressed group pill, updates the count, and Clear filters resets it', async () => {
    const user = userEvent.setup();
    render(<Theses onOpenThesis={() => {}} />);
    await screen.findByText('All 3 theses');

    await user.click(screen.getByRole('button', { name: /^CMS$/ }));
    expect(await screen.findByText('1 of 3 theses')).toBeInTheDocument();
    expect(tableRowTitles()).toEqual(['Ana Thesis']);

    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(await screen.findByText('All 3 theses')).toBeInTheDocument();
  });
});

describe('Theses table — author filter', () => {
  it('filters by an author picked from the dropdown, removable via its chip', async () => {
    const user = userEvent.setup();
    render(<Theses onOpenThesis={() => {}} />);
    await screen.findByText('All 3 theses');

    const input = screen.getByPlaceholderText('Filter by author…');
    await user.type(input, 'ana');
    const option = await screen.findByRole('option', { name: 'Ana Reis' });
    await user.click(option);

    expect(await screen.findByText('1 of 3 theses')).toBeInTheDocument();
    expect(tableRowTitles()).toEqual(['Ana Thesis']);

    await user.click(screen.getByRole('button', { name: 'Remove Ana Reis' }));
    expect(await screen.findByText('All 3 theses')).toBeInTheDocument();
  });
});
