# Thesis author/supervisor -> CISUC research-group attribution

This is the reviewable record for S5's people join: for each of the 18
theses in `estudo_geral/`, does the author or a supervisor resolve to a
person in `data/cisuc.sqlite3`'s `people` table, and if so, which of the six
research groups does that person's own project history put them in?

**Why this exists as a separate document.** Estudo Geral has no
research-group field, and its CISUC community (`com_10316_27707`) holds zero
theses — theses deposit under the department (`com_10316_255`), not the
research centre (measured, not assumed; see the card). So "which DEI research
group does this thesis belong to" cannot come from Estudo Geral at all — it
has to come from joining the thesis's author/supervisor names against the
existing `people` + `project_people` + `project_groups` tables. With only 18
theses (50 unique names total) that join was verified by hand, name by name,
rather than trusted to a script. This file is that verification record —
`uc_phd_app/theses.py` loads the machine-readable twin,
`docs/thesis-attribution.json`, at request time; nothing here is re-derived
silently by the app.

## Matching method — exact only, no similarity scoring

A name only resolves if, after folding (lowercase, diacritics stripped) and
tokenizing:

1. The **surname** — the first word of the thesis's `"Surname, Given Names"`
   form — appears as a token in the candidate `people.name`, **and**
2. Every token of the candidate `people.name` (surname and given names,
   Portuguese connectors `de/da/do/dos/das/e` ignored) appears among the
   thesis name's tokens.

A single-letter token in `people.name` (e.g. `"F. Amilcar Cardoso"`) is
accepted as a standard initial abbreviation of the corresponding full given
name in the thesis's form (`"Cardoso, Fernando Amílcar Bandeira"` -> `F.` =
Fernando) — this was checked by hand for every such case, not applied as a
blanket rule.

**What this deliberately does NOT do:** no edit-distance / similarity
threshold, no partial substring matching, no cross-language transliteration.
Two near-misses were found and left unattributed rather than resolved, because
they fail exact matching even though they look likely:

- `Silva, Rodrigo Ronner Tertulino da` (thesis author) — `people` has a row
  `"Rodrigo Tertulino"` with slug `r-silva`. The **slug encodes "silva"** but
  the **display name does not** — an inconsistency in the existing `people`
  table, not something this card introduces. Left unattributed; a human
  should confirm whether `r-silva` really is this same person.
- `Simões, João Miguel Moreira de Carvalho Brás` (thesis author) — `people`
  has `"João Braz Simões"` (slug `joao-braz-simoes`). `Brás` vs `Braz` is a
  **spelling difference (z vs s), not an accent-only difference**, so it
  fails exact matching. Left unattributed.

Both are called out again inline in `docs/thesis-attribution.json`'s `note`
field for the two names.

## Result

**36 of 50 unique names (72%) resolved; 14 (28%) are unattributed.** All 14
unattributed names are thesis **authors** or **foreign/external
co-supervisors** (e.g. `Frerichs, Inéz`, `Morais, Antônio Higor Freire de`) —
expected, since PhD students and external collaborators are not CISUC
project staff. No DEI-internal supervisor was left unresolved except the two
flagged near-misses above.

| # | Name | Role seen as | Status | Resolved to |
|---|---|---|---|---|
| 1 | Abbasi, Maryam | supervisor | matched | maryam-abbasi |
| 2 | Abreu, Pedro Manuel Henriques da Cunha | supervisor | matched | Pedro%20Henriques%20Abreu |
| 3 | Antunes, Nuno Manuel dos Santos | supervisor | matched | NunoAntunes |
| 4 | Arrais, Joel Perdiz | supervisor | matched | joelarrais |
| 5 | Baptista, Tiago Rodrigues | supervisor | matched | tiago-baptista |
| 6 | Bicker, João Manuel Frade Belo | supervisor | matched | joao-bicker + joao-bicker-1 (duplicate rows in `people`) |
| 7 | Cardoso, Fernando Amílcar Bandeira | supervisor | matched | f-cardoso |
| 8 | Carvalho, Paulo Fernando Pereira de | supervisor | matched | paulo-carvalho |
| 9 | Castelhano, João Miguel Seabra | supervisor | matched | joao-castelhano |
| 10 | Costa, Ernesto Jorge Fernandes | supervisor | matched | ernesto-costa |
| 11 | Cruz, Tiago José dos Santos Martins da | supervisor | matched | tjcruz |
| 12 | Cunha, Paulo José Osório Rupino da | supervisor | matched | paulo-cunha |
| 13 | Curado, Marília Pascoal | supervisor | matched | marilia-curado |
| 14 | Dib, Mário Alberto da Silveira | author | **unattributed** | — |
| 15 | Flora, José Eduardo Ferreira | author | matched | jeflora |
| 16 | Frerichs, Inéz | supervisor | **unattributed** | — (likely foreign co-supervisor) |
| 17 | Godinho, Noé Paulo Lopes | author | matched | noe-godinho |
| 18 | Gomes, Anabela de Jesus | supervisor | matched | anabela-gomes |
| 19 | Gonçalves, Charles Ferreira | author | matched | charles-goncalves |
| 20 | Granjal, António Jorge da Costa | supervisor | matched | jorge-granjal |
| 21 | Hijazi, Haytham Wael Ismail | author | matched | h-hijazi |
| 22 | Ivaki, Naghmeh Ramezani | supervisor | matched | naghmeh-ivaki |
| 23 | Júnior, Ivanilson França Vieira | author | **unattributed** | — |
| 24 | Machado, Fernando Jorge Penousal Martins | supervisor | matched | penousal-machado |
| 25 | Madeira, Henrique Santos do Carmo | supervisor | matched | henrique-madeira |
| 26 | Medeiros, Júlio Cordeiro | author | **unattributed** | — |
| 27 | Mendes, António José Nunes | supervisor | matched | antonio-mendes |
| 28 | Moraes, Caroline Relva de | author | **unattributed** | — |
| 29 | Morais, Antônio Higor Freire de | supervisor | **unattributed** | — (likely foreign co-supervisor) |
| 30 | Paiva, Rui Pedro Pinto de Carvalho e | supervisor | matched | rui-pedro-paiva |
| 31 | Paquete, Luís Filipe dos Santos Coelho | supervisor | matched | luis-paquete |
| 32 | Pereira, Tiago Oliveira | author | **unattributed** | — |
| 33 | Pessoa, Diogo Rafael Mendes | author | matched | d-pessoa |
| 34 | Prates, Pedro André Dias | supervisor | matched | pedro-prates |
| 35 | Proença, Jorge Diogo Gomes | author | matched | jorge-proenca-1 |
| 36 | Ramos, Isabel Maria Pinto | supervisor | **unattributed** | — |
| 37 | Rebelo, Sérgio Miguel Martins | author | matched | sergio-rebelo |
| 38 | Ribeiro, Bernardete Martins | supervisor | matched | bernardete-ribeiro |
| 39 | Rodrigues, Ana Cláudia Leitão Teixeira | author | matched | ana-rodrigues |
| 40 | Rosero, Raúl Homero Llasag | author | **unattributed** | — |
| 41 | Santos, Joana Cristo dos | author | **unattributed** | — |
| 42 | Santos, Miriam Raquel Seoane Pereira Seguro | supervisor | matched | miriam-santos-1 |
| 43 | Silva, Catarina Helena Branco Simões da | supervisor | matched | catarina |
| 44 | Silva, Leonardo Soares e | author | **unattributed** | — |
| 45 | Silva, Rodrigo Ronner Tertulino da | author | **unattributed (near-miss)** | — |
| 46 | Simões, João Miguel Moreira de Carvalho Brás | author | **unattributed (near-miss)** | — |
| 47 | Simões, Paulo Alexandre Ferreira | supervisor | matched | paulo-simoes |
| 48 | Teixeira, César Alexandre Domingues | author | matched | cesar-teixeira |
| 49 | Travasso, Rui Davide Martins | supervisor | **unattributed** | — |
| 50 | Vieira, Marco Paulo Amorim | supervisor | matched | marco-vieira |

Full reasoning for every "matched" ambiguity and every "unattributed" line is
in the `note` field of the matching entry in `docs/thesis-attribution.json`.

## From a matched person to a research group

A matched name does not carry a group by itself — `people` has no group
column. The app derives it live (never cached in this file) from the same
authoritative tables the rest of the dashboard already uses:

1. Groups of every project where that person is listed as **`coordinator`**
   (their own led work — the strongest identity signal, and the same
   restriction `sql/top_coordinators.sql` already applies for the same
   reason: a person's *team-member* history across decades of unrelated
   projects would flood them into all six groups and say nothing).
2. If they never coordinated a scraped project, fall back to the groups of
   projects where they are listed as **`researcher`**.

**This is a real, reportable finding, not a clean signal.** Several matched
supervisors are prolific, long-serving coordinators (e.g. Marília Curado,
Marco Vieira) whose own **coordinator**-role projects already span 5–6 of the
6 groups — so even the tighter coordinator-first signal still lands some
theses in most or all groups. That is the data speaking, not a matching bug:
CISUC's senior researchers coordinate across group boundaries over a career.
The per-group thesis breakdown is many-to-many for exactly this reason, same
as every other per-group figure in this app (`GROUP_MANY_TO_MANY_CAVEAT` in
`uc_phd_app/api/projects.py`), and the dashboard surfaces that caveat rather
than picking one group arbitrarily.

A thesis's own resolved group(s) = the union of every matched author's and
every matched supervisor's groups on that thesis. A thesis with no matched
name at all (none of author/supervisors resolve) shows as **Unattributed**.
In practice, because most theses have 2–3 supervisors and DEI's small size
means most supervisors do resolve, **every one of the 18 theses has at least
one matched name** — 0 theses are fully unattributed at the thesis level,
even though 14 of the 50 individual names are. Both facts are shown in the
dashboard: per-name status is visible in the underlying data, and the
per-group breakdown chart's total will not sum to 18 net of overlap because
of the many-to-many shape above.
