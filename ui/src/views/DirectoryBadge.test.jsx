// The unit badge on a resolved person who is NOT a CISUC member.
//
// Two things a reader must never be told, and both are one careless change
// away: that a Faculty of Economics professor is a CISUC member (the link
// alone implies it), and that they belong to a CISUC research group (the
// badge sits where a group chip would). So the test asserts the badge
// appears, that it carries the live directory page, and that a CISUC person
// gets nothing at all.
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { PersonList } from './Theses.jsx';
import { DirectoryBadge, ResolvedPersonName } from '../components.jsx';

const UC_PERSON = {
  name: 'Santos, Boaventura de Sousa',
  status: 'matched',
  match_status: 'exact',
  confidence: 1.0,
  note: 'via UC directory feuc: …',
  matched: [{ slug: 'uc--feuc--boaventura-de-sousa-santos', name: 'Boaventura de Sousa Santos' }],
  groups: [],
  group_shares: {},
  directory: {
    source: 'feuc',
    unit_name: 'Faculdade de Economia (FEUC)',
    listing_url: 'https://www.uc.pt/feuc/pessoas-e-servicos/docentes/',
    person_url: null,
    units: [
      {
        source: 'feuc',
        unit_name: 'Faculdade de Economia (FEUC)',
        listing_url: 'https://www.uc.pt/feuc/pessoas-e-servicos/docentes/',
        person_url: null,
      },
    ],
  },
};

const CISUC_PERSON = {
  name: 'Lovelace, Ada',
  status: 'matched',
  match_status: 'exact',
  confidence: 1.0,
  note: 'exact',
  matched: [{ slug: 'ada', name: 'Ada Lovelace' }],
  groups: ['NCS'],
  group_shares: { NCS: 1 },
};

describe('DirectoryBadge', () => {
  it('names the unit and carries the live directory page in its tooltip', () => {
    render(<DirectoryBadge directory={UC_PERSON.directory} />);
    const badge = screen.getByText('FEUC');
    expect(badge.getAttribute('title')).toContain('Faculdade de Economia (FEUC)');
    expect(badge.getAttribute('title')).toContain('not a CISUC member');
    expect(badge.getAttribute('title')).toContain(
      'https://www.uc.pt/feuc/pessoas-e-servicos/docentes/',
    );
  });

  it('renders nothing when the payload carries no directory — i.e. a CISUC person', () => {
    const { container } = render(<DirectoryBadge directory={undefined} />);
    expect(container.textContent).toBe('');
  });
});

describe('ResolvedPersonName with a UC-directory person', () => {
  it('links the profile like any resolved person AND shows the unit', () => {
    render(<ResolvedPersonName person={UC_PERSON} />);
    const link = screen.getByRole('link', { name: 'Santos, Boaventura de Sousa' });
    expect(link.getAttribute('href')).toBe(
      '#/people/uc--feuc--boaventura-de-sousa-santos',
    );
    expect(screen.getByText('FEUC')).toBeTruthy();
  });

  it('shows no badge for a CISUC person', () => {
    render(<ResolvedPersonName person={CISUC_PERSON} />);
    expect(screen.getByRole('link', { name: 'Lovelace, Ada' })).toBeTruthy();
    expect(screen.queryByText('FEUC')).toBeNull();
  });
});

describe('PersonList', () => {
  it('never renders an "(unattributed)" marker next to a UC-resolved name', () => {
    render(<PersonList people={[UC_PERSON]} />);
    expect(screen.queryByText(/unattributed/)).toBeNull();
    expect(screen.getByText('FEUC')).toBeTruthy();
  });
});
