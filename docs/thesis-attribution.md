# Thesis author/supervisor -> CISUC research-group attribution

> **Status (2026-09-23): this file is now a test fixture, not an input.**
>
> Everything below still stands as the record of what was decided and why —
> nothing in it has been revised. What changed is who does the work. The
> name -> person join is no longer read from `docs/thesis-attribution.json`
> at request time; it is resolved once, offline, by a deterministic matcher
> (`analysis/name_match.py`), written into the `thesis_people` table in the
> seed by `python -m analysis.build_thesis_facts`, and read from there.
>
> The hand-verified file became the **golden fixture** that matcher is tested
> against (`tests/test_name_match.py`): all 36 matches below must come back
> with the same slugs, and none of the 14 unattributed names may be resolved.
> That is why the reasoning in each `note` field was worth writing — the
> matcher's rules are generalisations of it, and the file is the evidence
> they reproduce a careful human rather than merely look plausible.
>
> Why it had to stop being an input: the corpus is going from 18 theses to
> all 181 DEI doctoral theses, which is ~300 names. Hand verification does
> not scale, and a per-request YAML+JSON parse is not queryable — so the
> advisor view, the collaboration graph and the theme recommendation would
> each have had to re-implement this join their own way. They now query one
> table instead.
>
> **The matcher's rules and tiers are in `analysis/name_match.py`'s module
> docstring.** The method section below is what it implements; the two extra
> rules it needed (duplicate `people` rows, and the primary-given-name
> tie-break) were both generalised from `note` fields in the JSON, and are
> documented there.

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
rather than trusted to a script. This file is that verification record.

(As of 2026-09-23 the app no longer loads the machine-readable twin at
request time — see the status note at the top. It reads `thesis_people` in
the seed, which the matcher built and this file now guards.)

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

**36 of 50 unique names (72%) resolved; 14 (28%) are unattributed.**

The deterministic matcher reproduces that result exactly, and reports it in
tiers: **31 `exact`, 5 `confident`, 0 `ambiguous`, 14 `unmatched`**. The five
`confident` ones are the cases a rule beyond whole-token equality reached —
three standard initials (Arrais, Cardoso, Rebelo), one duplicate-row union
(Bicker), one primary-given-name tie-break (Antunes). Zero names are
ambiguous today; that tier exists because it will not stay zero at 181
theses.

All 14
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

Every project where that person appears contributes weight to that project's
group(s), a **`coordinator`** role counting 1.0 and a **`researcher`** role
0.4, and the result is normalised to sum 1 across their groups
(`sql/person_group_shares.sql`). So the output is "Marco Vieira is 70% SSE"
rather than "Marco Vieira is in all six groups".

This replaced a coordinator-first / researcher-fallback rule that returned a
flat *set*. The set was not wrong, it was unusable: several matched
supervisors are prolific, long-serving coordinators (e.g. Marília Curado,
Marco Vieira) whose own **coordinator**-role projects genuinely span 5–6 of
the 6 groups. That is the data speaking, not a matching bug — CISUC's senior
researchers coordinate across group boundaries over a career — but a set
cannot say that one of those groups holds fifteen of their projects and the
others one apiece. The weighted share can, and that is what makes an argmax
meaningful.

## From a person to a thesis — two signals, combined by agreement

Weighting fixed the person, not the thesis. Unioning even a weighted person's
groups onto their students still answered "where has this supervisor worked"
when the question is "what is this thesis about": measured across the 181
theses, the union gave a **mean of 2.70 of 6 groups per thesis, with 35
theses carrying all six**. A thesis tagged with all six groups carries no
information.

So a thesis's group is decided by **two independent signals**:

1. **People** — the weighted shares above, summed over the thesis's resolved
   names, a supervisor counting 1.0, an author 0.5, each scaled by the
   matcher's own `match_confidence`. Derived **live** on every request.
2. **Content** — TF-IDF cosine between the thesis's own text (title ×2,
   `thesis_keywords` ×3, both abstracts) and each group's project text
   (titles, synopses, `project_keywords` ×3), with IDF measured over the 181
   theses plus the 400 project documents. Built **offline** by
   `python -m analysis.build_group_affinity` into `thesis_group_affinity`.

Neither is trusted alone — the content ranking's median top-1-over-top-2
margin is under 10%, a real ranking but far too soft to be believed on its
own. What is trustworthy is **agreement**: the two pick the same group for
~66% of the theses that have both signals, far above the ~20% a coin flip
would give. So the combination is not a blend, it is a tier:

| tier | what it means | groups shown |
|---|---|---|
| `corroborated` | both signals picked the same group | 1 |
| `contested` | they picked different groups | 2, ranked, flagged |
| `people-only` | the thesis has no keywords and no abstract | 1 |
| `content-only` | none of its names resolved to a person | 1 |
| `unattributed` | neither signal exists | 0 |

Measured on the committed seed: `{corroborated: 108, contested: 56,
people-only: 6, content-only: 8, unattributed: 3}` — **mean 1.29 groups per
thesis, maximum 2, 3 unattributed.**

A blended single score was rejected: 56 of 181 theses show genuine
disagreement, and averaging two weak signals there produces a confident-
looking single group that neither signal actually supports.

The per-group thesis breakdown is still many-to-many (a contested thesis
counts towards both of its groups), same as every other per-group figure in
this app (`GROUP_MANY_TO_MANY_CAVEAT` in `uc_phd_app/api/projects.py`) — but
a thesis now contributes at most 2, not up to 6.

### Two clocks

The people half stays live; the content half is frozen in the seed. A
re-scrape of cisuc.uc.pt moves the first immediately and the second not at
all until `python -m analysis.build_group_affinity` re-runs. **That is a
seed-rebuild obligation, not an implementation detail** — the two halves can
silently drift, and it is the price of not recomputing TF-IDF over 400
synopses on every request.

### Why not the embeddings

`documents.abstract_embedding` already exists in Postgres and was rejected for
the content signal, for two reasons. First, `uc_phd_app/api/fit.py` already
measured that this all-computing corpus compresses embedding distance — top-1
to top-5 spans 0.007 — and six computing-group profiles would sit closer
together than two theses do; IDF does the opposite, actively up-weighting the
vocabulary that separates the groups. Second, it would couple the dashboard's
group column to Postgres availability, where today only `api/search.py` and
`api/fit.py` degrade to 503.

This is the falsifiable part of the decision: measure the embedding
top-1/top-2 margin against the lexical one `build_group_affinity` reports,
and if it wins, flip it.

### Known weakness

131 PT and 129 EN abstracts go into one token bag against a mostly-English
project corpus, so a PT-only thesis is scored on weaker evidence. That is part
of why the tier is shown at all rather than a bare group label.

---

## Identity coverage at 181 theses (measured 2026-09-24)

The corpus went from the 18 theses this document verified by hand to all 181
DEI doctoral theses, so ~300 names now pass through
`analysis/name_match.py` with no human verification. **The decision taken was
to accept the current matcher coverage**, change nothing in the matcher, and
spend the work on measuring at the grain the views consume and rendering the
gap where those views live. What follows is the measurement that decision
rests on, and the two rule changes that were implemented, measured and
rejected — recorded so nobody re-runs them.

### Why the 32.9% headline is the wrong number

93 of 283 distinct names unresolved (32.9%) pools two populations with
**opposite expected outcomes**. `people` holds *current CISUC staff*: a
doctoral student is not staff, so an unresolved author is the matcher being
right, while an unresolved supervisor is a real hole in the advisor and
collaboration views. One rate describes neither.

| grain | figure |
|---|---|
| Author names | 181 distinct, **59 unresolved (33%)** — expected, not a gap |
| Supervisor names | 126 distinct, **35 unresolved (28%)**, 0 ambiguous |
| **Supervision edges** | **194 / 241 resolved (80%)** — the honest headline for the advisor view |
| Theses listing ≥1 supervisor | 157 / 181 |
| …with ≥1 resolved supervisor | **143 / 157 (91%)** |
| …with *all* supervisors resolved | 114 / 157 (73%) |
| Co-supervision pairs (name grain) | 91 occurrences, **55 both-resolved (36 lost)** |
| Distinct supervisor **people** | **64**, from 91 resolved names |

A name appearing in both roles (24 of 283) is counted under each, which is why
181 + 126 > 283. All of it is derivable from the committed seed — no rebuild
needed — and it is now a query, `sql/thesis_attribution_coverage.sql`, rather
than a figure in a comment: every number above went stale once already.

**Two findings that reframed the work.**

1. *The resolved side already aliases correctly and no view exploits it.* 91
   resolved supervisor names collapse to 64 slugs; 26 slugs are reached by more
   than one variant. Edmundo Monteiro supervises **15** theses under 2 variants
   while the busiest single *name* is 10. `sql/collab_co_supervision.sql`
   already keys on `person_slug` and is correct; `uc_phd_app/theses.py`'s
   `by_name` keys on `name_raw`, which is right for rendering one thesis and
   **wrong for any ranking**. There is no advisor-ranking view yet — so this is
   a constraint for whoever builds one, not a bug to fix now. A ranking keyed
   on `name_raw` would under-report Edmundo Monteiro by a third and nothing
   would fail.
2. *The unresolved tail is flat, which kills directed human verification.* The
   35 unresolved names form **31 likely-person clusters over 47 lost edges**;
   the largest is 6 edges (`Correia, António [Dourado [Pereira]]`), then 4,
   then 3, and **25 of 31 are 1–2 edges**. Every one of the top 9 supervisors
   by thesis count is already `exact`. There is no "verify the top N" slice:
   ~31 human decisions to recover 19% of the graph. The only slice with real
   leverage is the top 2 clusters — 2 decisions for 10 edges — a reasonable
   future card *if* the advisor view ships and those holes are visibly
   annoying.

**A ceiling no matcher can raise.** `people` is current staff, so edge
resolution degrades by decade: **1990s 60%, 2000s 64%, 2010s 79%, 2020s 89%**.
8 of the 35 unresolved supervisors (Braun, Domingo-Pascual, Pentikousis,
Zerlauth, Frerichs, Cerejeira, Phithakkitnukoon, Travasso) share no surname
token with any row in `people` at all — external co-supervisors, correctly
absent.

### Two rejected relaxations — do not re-run these

Both were implemented against the real corpus and measured. Both bought a
handful of edges with a **confidently wrong person**, which is the one failure
mode this whole module exists to prevent.

**A. Relax the stray-initial rule.** `_fits()` rejects a candidate whose
single-letter token abbreviates no *thesis* given name, so `"Fonseca, Carlos"`
misses `Carlos M. Fonseca`. Patching exactly that: **+4 of 241 edges
(80% → 82%)**, no new ambiguity. It also resolves `"Fonseca, José Carlos"` to
**`Carlos M. Fonseca`** — wrong, because `people` separately holds `José Carlos
Coelho Martins da Fonseca`, which rule 2 rejects on `coelho`/`martins`, so no
ambiguity flag catches it. 4 edges for one silent misattribution.

**B. Thesis-side alias clustering.** Link an unresolved name to an
already-resolved variant of the same person (`"Oliveira, Marília Pascoal
Curado de"` → `marilia-curado`). Best of the three on paper: **+13 edges
(80% → 86%)**, 8 unique recoveries, co-supervision pairs 60 → 67, **0 new
people invented**. It also produces `"Cruz, Luís Alberto da Silva"` →
**`Luís Silva`**. Luís Cruz is not Luís Silva: a shared primary given name
plus a token-subset relation is not identity. Rejected.

**C. A hand-written lookup table to force 100%** was ruled out by the Product
Owner before any of this, and the two measurements above are the independent
case for it: every automated shortcut to a higher number produced a wrong
person.

### The golden fixture can no longer police rule changes

**Both rejected rules left `tests/test_name_match.py` completely green.** This
document's machine-readable twin covers the 18-thesis cohort, and every false
positive above involves a name outside it. The fixture's role is unchanged and
it is still the most valuable artefact in the repo — but "the golden fixture
passes" must never again be read as "this rule change is safe at 181". A rule
change now has to be measured over all 181 theses for what it newly matches
*and* inspected for what it matches wrongly. The same warning is on
`tests/test_name_match.py`'s module docstring, where a coder will actually meet
it.

### What this makes harder later

- **Coverage is now a published number** (`/api/theses`'s `identity_coverage`,
  rendered on the Theses view). A corpus extension that drops 80% to 70% is a
  visible regression — that is the point, but the reindex inherits a figure to
  defend.
- **The multi-grain metric is more code than one dict.** A future third role
  (examiner, co-author) has to be added in three places: the SQL, the payload,
  the tile.
- **S7's group attribution sits on top of this layer** and carries this
  coverage as a multiplier. It should quote it rather than re-derive it.

### Out of scope here, and bigger: 24 theses name no supervisor at all

**24 of 181 theses (1997–2013; 23 of them also have no extracted full text)
carry no supervisor in their front matter.** That is an *extraction* gap, not a
matching one, and at ~1.5 supervisors per thesis it is worth roughly 36 edges —
comparable to the entire 47-edge unmatched loss. It is also why "79% of all 181
theses have a resolved supervisor" understates the matcher: against the 157
that actually list one it is 91%. Routed to the Product Owner as a separate
card against the Estudo Geral extractor; it likely buys more advisor-view
coverage than any identity work remaining.
