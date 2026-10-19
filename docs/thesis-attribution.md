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

### The `exact` tier means token-set EQUALITY (amended 2026-10-15)

Rule 2 above is **asymmetric**: the candidate's tokens have to be covered by
the thesis name, not the other way round, because the CISUC form is routinely
the shorter one. That asymmetry still decides whether a slug is assigned — it
is the workhorse: of the 190 distinct names the matcher resolves across the
181-thesis corpus, 106 rest on it — 122 of 213 at the once-per-role grain
`sql/thesis_match_tiers.sql` reports (82 of 122 authors, 40 of 91
supervisors). What it no longer decides is the *tier*:

- **`exact` (1.0)** — the two folded token sets are **equal**. Neither name
  carries a name the other does not. (Sets, not counts, so a thesis name that
  repeats a token — `"Pereira, Francisco Colunas Pereira da Câmara"` — is
  still an equality rather than a phantom extra given name.)
- **`confident` (0.8)** — a single candidate fits on **strict subset**
  coverage and/or via an initial. The slug is still assigned; the note names
  the thesis tokens the candidate cannot corroborate.

Subset coverage cannot *prove* identity, and saying 1.0 claimed it did.

### One `people` row authors at most one thesis

Tier honesty describes the weakness; it does not catch it. The corpus-level
invariant does, in `analysis/build_thesis_facts.py`
(`resolve_author_conflicts`): after every name is matched, any `person_slug`
claimed as **author** by more than one thesis is a false merge, because two
different people wrote those two theses. Resolution:

- exactly one claimant whose name is a **set-equality** with the `people`
  row → it keeps the slug; every other claimant is demoted to
  `ambiguous` / NULL slug with a note naming the conflict;
- zero or several set-equal claimants → **all** claimants are demoted.

**Supervisors are exempt.** One supervisor across many theses is the normal
case and the entire point of the advisor view.

The escape hatch, when a genuine multi-thesis author appears in this corpus:
the build demotes both claims and lists the conflict in `author_conflicts`,
and the backstop in `scraper/schema.sql` refuses to let a re-merge be
committed at all. That is loud by design — a real second thesis has to be a
human decision recorded somewhere, not something the matcher quietly absorbs.

**It appeared in 2026-10, and that somewhere is now
`data/multi_thesis_authors.json`.** The corpus grew to 2690 theses including
the university-wide collection, and João Rodrigues Campos's MSc dissertation
(`10316/83144`, 2017) and doctoral thesis (`10316/100421`, 2022) are both
deposited under the identical author string "Campos, João Rodrigues de" —
both token-set-equal to the CISUC row, so the gate found two set-equality
claimants, could prefer neither and withdrew both links. The fourth curated
file records the reviewed fact that this is one graduate with two deposits,
keyed on the slug with an **exhaustive** list of handles; a claim on that
slug for a handle the entry does not list is demoted exactly as before.
`analysis/multi_thesis_authors.py` explains why this is a reviewed per-person
fact and not the rule it looks like it could be ("claims that are
byte-identical are safe" — rejected: byte-identical is the *maximally*
similar pair of claims in a corpus whose core trap is that similarity is not
identity).

The backstop changed shape with it. It was a partial UNIQUE index,
`idx_one_thesis_per_resolved_author` ON `thesis_people(person_slug)`; a
SQLite partial-index predicate cannot subquery, so it cannot ask whether a
pair has been reviewed, and it is now a BEFORE INSERT trigger,
`trg_one_thesis_per_resolved_author`, which reads the `multi_thesis_authors`
seed table. With that table empty the trigger is exactly the old index. Note that
`people.slug` was **already** the primary key of `people`; a unique student
slug was never the missing piece. The defect was the other direction, a wrong
many-people → one-slug *mapping*, which no key on `people` can see.

### The motivating case: `pedro-martins`

One CISUC row, `"Pedro Martins"`, was claimed by two theses at `exact`/1.0,
which is what turned 181 theses into "180 Students":

| Handle | Year | Thesis author name | Topic | Supervisor |
|---|---|---|---|---|
| `10316/23751` | 2014 | `Martins, Pedro` | local image feature detection (computer vision) | Paulo de Carvalho |
| `10316/29090` | 2016 | `Martins, Pedro Miguel de Oliveira` | elastic ETL for data warehouses | Pedro Furtado |

The 2014 name is a token-set equality with the CISUC row and keeps the slug;
the 2016 name is a strict subset claim and is demoted. The corroborating
evidence is the CISUC row's own project history: ArthroNav and C-BASED, both
computer vision, and **zero** ETL or data-warehousing projects. The matcher
does not read that — it keeps the set-equal claim on the name alone — but a
human checking the decision has it.

The riskier residue is the class this *cannot* see: a two-token CISUC row
matched to a longer thesis name where the real second person is simply not in
the corpus. The build report lists every one of them as
`minimal_evidence_matches` (81 at time of writing) for spot-checking, rather
than pretending they are ruled out.

## Result

> **Amended at the people-directory card (2026-10-15): 43 of 50 resolved, 7
> unattributed.** The counts in this section and the table below are the
> original record and are left as written — but `people` has since gained a
> second source. It was built only from scraped *project* pages, so "no person
> in the people table shares the surname X" — the reasoning behind most of the
> 14 — was a statement about a pool that could not contain a PhD student who
> never worked on a scraped project. `scraper/people.py` now also ingests
> CISUC's own ~740-person People directory, and 7 of the 14 resolved against
> candidates that had never been available: Dib, Júnior, Medeiros, Pereira
> (Tiago Oliveira), Rosero, Santos (Joana Cristo dos) and Silva (Leonardo
> Soares e). **No rule in `analysis/name_match.py` was changed.** Each was
> checked by hand against the thesis and the person's own CISUC page before
> `docs/thesis-attribution.json` was moved to `matched`; the evidence is in
> each entry's `note`. The widened pool also made `Moraes, Caroline Relva de`
> `ambiguous` — CISUC lists that one human twice — which is the designed
> answer and still not a resolution. Live tiers are asserted in
> `tests/test_name_match.py`, which is the number to trust over this
> paragraph.

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

### The floor the subset rule may not stand on alone (2026-10-19)

A and B are relaxations that were rejected. This one is a **tightening that
was accepted**, and it belongs next to them because it is the same lesson read
from the other side: the subset rule's weakest shape had been shipping wrong
people, and nothing in a name could have told anyone which ones.

**The failure.** The pass-2 UC-directory pool (v0.23.0) publishes **312 of its
1449 people under a bare "Given Surname"** — surname plus first given name,
nothing else. `_fits()` accepts such a candidate for *every* thesis name
sharing that given name and surname, because condition 2 ("every candidate
token is accounted for by the thesis name") is trivially satisfied when the
candidate carries no middle names to contradict. In the live seed that merged
distinct real humans onto one slug: `uc--feuc--joao-pedro-amaral-cabouco-
rodrigues`, published bare as "João Rodrigues", held both "Rodrigues, João
Paulo Correia" and "Rodrigues, João Manuel Coutinho"; `uc--fctuc-deec--luis-
cruz`, published bare as "Luís Cruz", held "Cruz, Luís Alberto da Silva" —
**this document's own sentinel false positive, reproduced through a path its
guard never covered**. CISUC's pool had the same rule and a far lower bare-name
rate, which is why it fired here first.

**The rule.** At the pass-2 acceptance seam
(`build_thesis_facts.people_rows`, *not* inside `match_name`/`_fits`), a
`confident` UC-pool match is **demoted to report-only** — the row keeps its
pass-1 `unmatched` verdict, exactly as a pass-2 `ambiguous` already does — when
all three hold:

1. the candidate's pool display tokens ⊆ **floor** = surname tokens ∪ {first
   given token}, which `minimal_evidence_matches()` already named as the
   weakest evidence this matcher ever acts on. `build_thesis_facts.
   floor_tokens()` is now that one definition, read by both;
2. the thesis token set is a **strict** superset — there exist given names the
   candidate cannot confirm;
3. **nothing richer corroborates the thesis name.** The pool flattens a human
   to one `people.name`, but `directory_listings.name_as_published` keeps every
   unit's verbatim form and `person_full_names` keeps the reviewed one; if any
   of those accounts for every thesis token (`_fits_full`'s convention,
   thesis-side initials excused), the match stands as `confident` and its
   `match_note` names the listing that saved it.

Set-equal (`exact`) rows are **not** demoted: a bare thesis mention has no
middle names to contradict, it is the evidence grade pass 1 has always
accepted, and two bare candidates already come out `ambiguous`. They are
reported instead, in `uc_pool_minimal_evidence`. Pass 1 is untouched,
deliberately — the row-diff gate for this change was zero pass-1 changes.

**Why 3 is not relaxation B.** B compared thesis names against published
display names and thereby *created* matches ("Cruz, Luís Alberto da Silva" ->
"Luís Silva"). This comparison runs only on candidates `_fits()` has already
accepted, and only to choose between *confident* and *demoted*: it can
withhold a demotion, it can never turn a rejection into a fit.
`tests/test_uc_directory_match.py::test_corroboration_can_never_turn_a_
rejected_candidate_into_a_match` hands the richest possible corroboration to a
rejected candidate and asserts it buys nothing.

**Measured over the 2690-thesis corpus** (rebuild of the committed seed at
`3f87407`, row-diffed):

| | before | after |
|---|---|---|
| Resolved supervisor rows | 2093 | **2000** |
| …of them pass-2 (UC pool) | 1471 | **1378** |
| Pass-1 rows changed | — | **0** |
| Author rows changed | — | **0** |
| Demoted rows | — | **93** (49 names, 39 slugs) |
| Kept at the floor | — | 167 (127 set-equal `exact`, 40 corroborated) |

The whole delta is pass-2 supervisor rows losing a slug. All three confirmed
merges go, the Cruz sentinel included; Elísio Estanque's 15 rows survive (8
set-equal `exact`, 7 rescued by FEUC's "Elísio Guerreiro Estanque" where CES
publishes him bare) and so does the correct Góis row `10316/114758`, rescued by
FEUC's full published form. A fourth real merge fell out of the demotions
list: "Carvalho, António José Olaio (Correia de)" — the artist António Olaio —
had been credited to a different FEUC professor published bare as "António
Carvalho", 14 rows of it.

**The coverage number drops, and that is the correct direction.** The removed
edges were wrong or unverifiable. **312 bare-published UC people are now
structurally unresolvable for a richer thesis form until curated**, and the
`uc_pool_bare_floor_demotions` report key is the shopping list for that: a
demoted true match is rescued the house way, by a sourced
`data/person_full_names.json` entry, never by loosening the rule.

### The accepted fourth option: a reviewed person-alias table (2026-10-15)

A, B and C above all failed for the same reason — they tried to derive an
identity decision from the names. The thing that actually worked was to stop
deriving it.

**`data/person_aliases.json`** records, per pair of `people` rows, whether
CISUC is listing one human twice: `verdict: "same"` with a chosen `canonical`
slug and the `evidence` behind it, or `verdict: "distinct"` for the pairs that
look the same and are not. `analysis/person_aliases.py` validates it against
the live roster and writes the `same` rows into `person_aliases(from_slug,
to_slug, evidence)` inside the seed; `scraper/schema.sql` adds a
`people_canonical` view (one row per human) next to it. The matcher collapses
candidates that all share one canonical identity
(`name_match._one_canonical`), `build_thesis_facts.people_rows` writes the
**canonical** slug — which is what makes `resolve_author_conflicts` and
`trg_one_thesis_per_resolved_author` see one person rather than two slugs —
and the profile aggregates across the group with the merge stated on the page.

**Why this is not option C in disguise.** C was a table of *thesis name ->
person*, forcing the matcher's output. This is a table of *person -> person*,
upstream of any thesis, correcting an inconsistency in the **source**: both
slugs are real CISUC directory entries with live URLs, and the merge is
checkable against them by anyone. The matching rules are untouched, and a name
no rule resolves is still unresolved.

**Measured over all 181 theses, before and after:**

| | before | after |
|---|---|---|
| `exact` | 85 | 85 |
| `confident` | 143 | **147** |
| `ambiguous` | 8 | **4** |
| `unmatched` | 47 | 47 |
| `thesis_people` rows | 429 | **426** |
| `author_conflicts` | 0 | 0 |

Every changed row was inspected by hand. The four names that moved from
`ambiguous` to `confident` are exactly the four whose only two candidates were
one human: `Moraes, Caroline Relva de`, `Paredes, Simão Pedro Mendes Cruz
Reis`, `Silva, Jorge Miguel Sá`, `Simões, Marco António Machado`. The three
lost rows are `filipius-1` duplicates of `filipe-araujo` rows that survive.
Nothing became unmatched, nothing was demoted, and no new author conflict
appeared.

**Detection is suggest-only, permanently.** `scraper/people.py`'s
`possible_duplicates()` flags same-surname, subset-compatible, primary-given-
compatible pairs (49 on the live 905-row roster) and reports them as
`possible_duplicates` in the sync counts. It must never merge, and the
counterexample is in the data: `simao-paredes`/`s-paredes` publish the **same
ORCID** and are one person, while `nuno-silva-1` (nsilva@criticalsoftware.com,
Adaptive Computation) and `nuno-silva-4` (npsilva@dei.uc.pt, Software and
Systems Engineering) satisfy every one of those conditions and are two
different people. The Kanban card that commissioned this work listed that
second pair as a known duplicate; the CISUC pages say otherwise, which is
precisely why the verdict is a human's.

`Silva, Nuno Pedro de Jesus` therefore stays `ambiguous`, correctly: four
real, distinct people fit that name. The remaining three ambiguous names
(`Craveiro, Olga Marina Freitas`, `Martins, Pedro Miguel de Oliveira`,
`Nunes, Paulo Jorge Costa`) are flagged suspects nobody has reviewed yet —
`pedro-martins`/`pedro-martins-2` being the family this document's own
motivating case says are **different** people. They are left alone.

#### Amendment (2026-10-15): the 12th verdict, and the consumer it exposed

`teresa-pessoa` / `teresa-pessoa-1` — both literally "Teresa Pessoa" — were
reported by `possible_duplicates()` (1 of its 39 open suspects) and nobody had
read that output, so the pair reached production as **two bars in the
Coordinators chart**. Ruled `same`, canonical `teresa-pessoa`: one CiênciaVitae
CV (Ciência ID A013-8BAE-FF03, ORCID 0000-0002-5252-3618, FPCE-UC) accounts for
all four projects and both of the two disjoint publication sets the two CISUC
pages carry, and `tpeassoa@fpce.uc.pt` on the first page is a typo for the
`tpessoa@fpce.uc.pt` the second one publishes — the address printed under her
name in *Comunicar* 38 (2012), and found nowhere else on the web. The mailbox
rule that settled the five original `same` verdicts could not settle this one:
the two local parts differ, and neither page publishes a category, a group or
an ORCID. Evidence from outside CISUC is sometimes the only evidence there is.

The verdict alone did not fix the chart. **Every one of the five original
`same` pairs keeps all its project history on one slug** (`filipe-araujo` has
16 projects, `filipius-1` none), so no committed family had ever exercised a
*project-keyed* consumer that fails to resolve — and `sql/top_coordinators.sql`
was exactly that: it joined `people` directly, so `teresa-pessoa` (TKCOM) and
`teresa-pessoa-1` (STAR) drew one bar each. It now resolves through
`person_aliases` and reads `people_canonical`, and
`tests/test_routes.py::test_coordinators_resolve_through_person_aliases`
coordinates one fixture human under both slugs — including both slugs on the
same project — so the regression cannot come back silently. 107 coordinator
bars -> 106; thesis facts unchanged (Teresa authors and supervises nothing in
the corpus). The "standing tax on every new consumer" below is the general
case; this was the first unpaid bill.

### The fifth option: a reviewed full-legal-name table (2026-10-15)

The alias table above fixes CISUC listing one human **twice**. A second,
unrelated source defect went with it: CISUC sometimes lists a human **once,
under a name that is not a truncation of theirs**.

| CISUC publishes | the person's full legal name | Estudo Geral writes |
|---|---|---|
| António Dourado | António Dourado Pereira Correia | Correia, António [Dourado [Pereira]] |
| Marilia Curado | Marília Pascoal Curado de Oliveira | Oliveira, Marília Pascoal Curado de |
| Fernando Boavida | Fernando Pedro Lopes Boavida Fernandes | Fernandes, Fernando Pedro Lopes Boavida |
| Penousal Machado | Fernando Jorge Penousal Martins Machado | Machado, Fernando |

The two forms **share no surname token at all**, so `_fits()` rule 1 rejects
them before any of its other logic runs. This is the largest single cluster in
the unresolved tail — "Correia, António [Dourado [Pereira]]" is the 6-edge
cluster the measurement above named as one of the only two slices with real
leverage.

**`data/person_full_names.json`** records, per `people` slug, that person's
full legal name and the citable source it was read off.
`analysis/person_full_names.py` validates it against the live roster and
writes `person_full_names(slug, full_name, evidence)` into the seed.
`name_match._fits_full()` is the one comparison allowed to read it: the
**mirror** of `_fits()` — the thesis name must be a subset of the full name,
rather than the other way round — which is correct here precisely because a
legal name is a complete form like the thesis form, and unlike CISUC's
truncated display form. The display name still gets the first say; the
reviewed full name is a fallback, never an override.

**Why this is not measured-rejected relaxation B.** It is the same comparison
B made, and B produced `"Cruz, Luís Alberto da Silva"` -> **`Luís Silva`**.
The load-bearing difference is the **gate**: `_fits_full()` runs only against
a full name a human reviewed and sourced, never against `people.name`. Luís
Silva has no reviewed full name carrying "cruz", so B's false match is
structurally unreachable rather than merely unlucky. The boundary is the whole
design, and `tests/test_person_full_names.py` replays that exact false
positive to assert it stays unreachable. A match this way caps at
`confident`, never `exact`, even on token-set equality: what it agrees with is
a reviewed declaration, not the identity CISUC itself publishes.

**Why the mechanism is a curated file and not a bio scrape.** 3 of these 4
people were reported as having their legal name verbatim in CISUC's own bio
("Full name: X (short: Y)"). Measured on the live pages on 2026-10-15: only
`antonio-dourado`'s does. `marilia-curado`, `fernando-boavida` and
`penousal-machado` all serve a Short Bio block that never states the legal
name, and 3 more spot-checked pages likewise. A 740-page scrape plus a parser
would recover 1 of the 4. Dourado's entry cites the bio URL as its *source*;
nothing scrapes it.

**Measured over all 181 theses, before and after** (distinct names, the
matcher's own report card):

| | before | after |
|---|---|---|
| `exact` | 85 | 85 |
| `confident` | 147 | **153** |
| `ambiguous` | 4 | 4 |
| `unmatched` | 47 | **41** |
| `thesis_people` rows | 426 | 426 |
| `author_conflicts` | 0 | 0 |

At the grains the views consume (`sql/thesis_attribution_coverage.sql`):

| | before | after |
|---|---|---|
| **Supervision edges resolved** | **198 / 241 (82%)** | **211 / 241 (88%)** |
| Supervisor names resolved | 93 / 126 | **99 / 126** |
| Author names resolved | 162 / 181 | **163 / 181** |
| Theses with ≥1 resolved supervisor | 146 / 157 | **152 / 157** |
| Theses with *all* supervisors resolved | 118 / 157 | **131 / 157** |
| Co-supervision pairs both-resolved | 56 / 91 | **63 / 91** |
| Distinct supervisor people | 65 | **66** |

**Every changed row was inspected by hand, and there are exactly 14.** All 14
are `unmatched` -> `confident`: no row appeared, none disappeared, no slug
changed from one slug to another, nothing was demoted, no name became
ambiguous, and no new author conflict appeared. Six are António Dourado
(10316/27608, /1764, /10153, /1758, /1760, /23583 — 2001-2015, all adaptive
control, neuro-fuzzy systems or seizure prediction, each with a CISUC
co-supervisor or author from his own circle); four are Marília Curado
(10316/1748 as **author** — her own 2005 QoS-routing PhD, supervised by
Edmundo Monteiro, matching the 2005 UC PhD her bio records — plus /22105,
/95281, /95282 as supervisor, three of them co-supervised with Edmundo
Monteiro); two are Fernando Boavida (10316/1757, whose author Jorge Miguel Sá
Silva he supervised, and /24526, co-supervised with Paulo Simões); two are
Penousal Machado (10316/31166 and /41880).

The last of those is the one that needed evidence beyond a domain argument —
10316/41880 is NLP/question-answering, not his usual area. Its own title page
settles it: *"supervised by Professor Paulo Jorge de Sousa Gomes and Professor
**Fernando Jorge Penousal Martins Machado**"*, the full name verbatim, for a
thesis Estudo Geral files under the bare "Machado, Fernando".

#### Amendment (2026-10-16): eleven more entries, and a thesis-side initial

The 45-name sweep (every unattributed author/supervisor researched one per
name) produced a second, larger batch of this same shape and one narrow rule
change. **Eleven entries added**, taking the file from 4 to 15: `f-cardoso`,
`carlos-fonseca`, `maria-marcelino`, `antonio-mendes`, `karima-velasquez`,
`bruno-direito`, `mario-zenha-rela`, `jorge-silva`, `r-silva`,
`fernando-barros`, `francisco-pereira-1`. No `person_aliases.json` change was
needed — the `j-silva`/`jorge-silva` pair the sweep flagged as a possible
CISUC duplicate was already in it.

Six of the eleven are **not** the Dourado shape. They are the opposite
defect, and they are what closes the Backlog card
`matching:uc-phd-fits-extra-cisuc-initial`: CISUC publishes a form that is
*longer* than the Estudo Geral one, so `_fits()` rejects the directory row
because the thesis name cannot account for a middle name or an initial the
thesis never mentions ("Cardoso, Amílcar" vs `F. Amilcar Cardoso`;
"Fonseca, Carlos" vs `Carlos M. Fonseca`; "Mendes, António" vs
`Antonio Jose Mendes`). Relaxing `_fits()` for that is measured-rejected
relaxation A. Recording the person's **complete** name is not: the thesis
form is then a subset of it and `_fits_full` resolves it inside the existing
gate. For Cardoso and Fonseca the complete name is strictly longer than the
display form and had to be sourced — CiênciaVitae declares "FERNANDO AMÍLCAR
BANDEIRA CARDOSO", and White Rose eTheses files Fonseca's 1995 Sheffield
doctorate under "Fonseca, Carlos Manuel Mira da". For Mendes, Marcelino,
Zenha-Rela and Francisco Pereira the complete name is what UC's own faculty
directory and their own CiênciaVitae records publish, which the entries say
explicitly rather than implying a longer form nobody verified.

**The one rule change: `_fits_full` rule 2 now accounts for a single-letter
THESIS token that prefixes a full-name token** — "Pereira, Francisco B." for
Francisco **B**aptista Pereira. One entry (`francisco-pereira-1`) resolves
both of the corpus's unmatched Francisco Pereira rows, and that row is the
only one that needs this. The asymmetry is deliberate and is now in
`_fits_full`'s docstring: an **entry-side** letter stays a typo, because a
reviewed legal name is recorded in full by the human who sourced it, and
excusing one would let this comparison run against what is effectively
`people.name` — relaxation B. A letter in the *thesis* name is a different
thing: the deposited record abbreviated, not the curator, and `_fits()`
already excuses exactly that convention on the CISUC side
(`_is_initial_of`). Relaxation A's false match stays unreachable for the
reason it already was — "josé" is a word, not a letter, and it appears in no
reviewed full name carrying "fonseca" —
and `tests/test_name_match.py` asserts "Fonseca, José Carlos" does not fit
`carlos-fonseca`'s new entry.

**Measured over all 181 theses, before and after** (distinct names):

| | before | after |
|---|---|---|
| `exact` | 85 | 85 |
| `confident` | 153 | **165** |
| `ambiguous` | 4 | 4 |
| `unmatched` | 41 | **29** |
| `thesis_people` rows | 426 | 426 |
| `author_conflicts` | 0 | 0 |

At the grains the views consume: supervision edges resolved **211 → 221 of
241** (88% → 92%), supervisor names 99 → 107 of 126, author names 163 → 167
of 181.

**Every changed row was inspected by hand, and there are exactly 14** — all
`unmatched` -> `confident`, no row added or removed, no slug changed from one
slug to another, nothing demoted, nothing newly ambiguous, no new author
conflict: Cardoso ×2 (10316/1747, /9599), Zenha-Rela ×2 (/24888, /29594),
and one each for Fonseca-Carlos (/32725), Marcelino and Mendes (both /79528),
Velasquez-Castro (/95282), Direito-Leitão (/23583), Silva-Jorge (/28862),
Silva-Rodrigo-Tertulino (/118766), Silva-Fernando-Barros (/1901), and the two
Francisco Pereira rows (/87416 and /29450). The golden fixture's tier
distribution is untouched at {exact 7, confident 36, ambiguous 1, unmatched
6} — none of the 50 hand-verified names is affected, and display-name fits
are still tried before full-name fits.

**Both known false positives stay dead**, re-checked by name rather than by
count: "Fonseca, José Carlos" and "Cruz, Luís Alberto da Silva" remain
`unmatched`. Note for whoever picks this up next — `people` *does* hold
`jose-fonseca-1`, "José Carlos Coelho Martins da Fonseca", whose display name
is a superset of the thesis form exactly like `antonio-mendes`'s, so a
reviewed full name could legitimately resolve him. That was outside this
card's scope and deliberately not done; he is a genuinely different human
from `carlos-fonseca`, which is the thing the relaxation got wrong.

**`alvaro-rocha` still cannot be done at all.** His CISUC page is live
(https://www.cisuc.uc.pt/en/people/alvaro-rocha, 200 on 2026-10-16) but he is
absent from the 740-row People directory the scraper reads — re-fetched
directly from `scraper/people.py`'s own endpoint on 2026-10-16 and confirmed:
zero rows for him. There is therefore no slug to attach a full name to, and
a `person_full_names` entry would be refused by its own validator. He stays
`unmatched`, blocked on the directory-source card, and gets no
`external_people` entry either: he is a real CISUC person, not an external
one, and recording him as external would be wrong the moment the sync is
fixed.

### The sixth option: researched external identities, for display only (2026-10-16)

The 45-name sweep's other 29 mentions are the ones no identity table can
help, because the directory is **right** to be silent: an ISEP professor who
co-supervised one thesis, a CERN project leader, a UFPB academic, two
Critical Software founders, graduates who left. They stay `unmatched`
forever and nothing should match them. What was still wrong was the
*display* — the app printed a bare "(unattributed)" next to a person whose
name, affiliation and source are now known.

**`data/external_people.json`** records, per thesis **mention**, that
person's published name, affiliation, the citable page it was read off, an
optional caveat, and the evidence. `analysis/external_people.py` validates it
against the `thesis_people` rows the same build just wrote and writes
`external_people(handle, name_raw, role, display_name, affiliation,
source_url, note, evidence)` into the seed. `uc_phd_app/theses.py` attaches
it as `external` on an unattributed person entry, and the two `PersonList`
components render it in place of the bare label.

**Why this is not option C.** C mapped a thesis *name* to a person and forced
the matcher's output. This maps one thesis *mention* to display metadata:

- **No `person_slug`, and no column for one.** The table structurally cannot
  override, shadow or second-guess a matcher verdict, and `identity_coverage`
  does not move — an external person is correctly unresolved, not newly
  resolved. `IDENTITY_COVERAGE_NOTE` now says so on the page itself.
- **The loader refuses an entry whose row is not `unmatched`.** A future
  matcher improvement that resolves one of these names breaks the build until
  the obsolete entry is removed, instead of leaving a stale external claim
  beside a real CISUC person. That is the mechanism that keeps the two layers
  from ever disagreeing silently.
- **`analysis/name_match.py` never imports it**, asserted at the import graph
  in `tests/test_external_people.py`.
- **The key is a mention, not a name**, so a future thesis carrying the same
  string inherits nothing. Same-name-different-person is this corpus's core
  trap: "Martins, Pedro" is two different people two years apart. The
  accepted cost is duplication — Torsten Braun supervises two theses and so
  has two entries, which is why the file holds 29 entries for 28 people.

Rejected alternatives: **overloading `match_note`**, which is machine-written
and replaced on every rebuild, so a human sentence in it would be destroyed
by the next build; and **an external-person registry with invented slugs**,
which is option C with a parallel identity space and no directory to validate
against.

Three entries carry a `note` rather than a clean claim, and that is the field
doing its job: Gonçalo Quadros's three middle names are not verified against
any primary record (only "Gonçalo Quadros" appears in public bios, so the
identification rests on the company's founding record plus the matching 2002
UC doctorate); João Carreira has no personal institutional page at all;
and Konstantia Barmpatsalou is not external to CISUC at all — she is a CISUC
doctoral alumna with no directory row, kept in this file because there is no
slug to attach and nothing to match against.

#### What this makes harder later

- A **third** human-maintained identity artefact, after
  `docs/thesis-attribution.json` and `data/person_aliases.json`. A wrong
  `full_name` silently lands a wrong person at `confident`. The mitigations
  are structural — mandatory evidence, a loud loader, the display-coverage
  check, and the measured diff above — but the curation surface grows and
  somebody owns it forever.
- `confident` now includes matches grounded in a reviewed declaration rather
  than purely in the published names. Anyone reading that tier as "derived
  from CISUC's own display name" is slightly wrong from here on; the note on
  each row carries the distinction, naming the file and the full name.
- Deliberately does not scale: every future dropped-surname person costs a
  human entry. That is consistent with the flat tail measured above (25 of 31
  unresolved clusters are 1-2 edges) and with the standing no-forced-100%
  ruling. The ceiling after this is ~92%, not 100% — roughly 19 of the 43
  originally-unmatched edges are externals, departed staff, or genuinely
  unresolvable from the name text.
- `Person` now carries two names. Every consumer must keep rendering `.name`
  (what CISUC publishes) and never `full_name`, which is evidence rather than
  a label. `docs/graph-db-plan.md` has one more table to port.

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
- **`people.slug` no longer means "one human."** Every count over people, and
  every person-keyed join, has to resolve through `person_aliases` or read
  `people_canonical` — the view exists so there is one obvious place to do
  that, but it is a standing tax on every new consumer. `docs/graph-db-plan.md`
  must port the indirection, not flatten it.
- **A second human-maintained identity artefact** now lives beside
  `docs/thesis-attribution.json`. A wrong `same` entry silently merges two real
  people at the `confident` tier, which is why `evidence` is a required field
  and the loader refuses an entry it cannot act on rather than skipping it — a
  skipped entry would silently *un-merge* a person and still report a
  successful build.

### Out of scope here, and bigger: 24 theses name no supervisor at all

**24 of 181 theses (1997–2013; 23 of them also have no extracted full text)
carry no supervisor in their front matter.** That is an *extraction* gap, not a
matching one, and at ~1.5 supervisors per thesis it is worth roughly 36 edges —
comparable to the entire 47-edge unmatched loss. It is also why "79% of all 181
theses have a resolved supervisor" understates the matcher: against the 157
that actually list one it is 91%. Routed to the Product Owner as a separate
card against the Estudo Geral extractor; it likely buys more advisor-view
coverage than any identity work remaining.

---

## Amendment, 2026-10-19: a second directory, and what `exact` now means

Card `3fd5bf3b-9510-8113-a699-ec378da4a0c9` added UC's per-unit staff
directories to the candidate pool. The design is
`docs/design/uc-phd-non-cisuc-uc-directories.md` in the workspace repo; this
section records what changed about the *method* this document describes,
because three sentences above are no longer literally true.

**`people` is no longer one directory.** It holds CISUC's own roster plus
whatever `scraper/uc_directories/` has harvested, and the two are told apart
by a join: a row with no `directory_listings` row is a CISUC person exactly
as before (`scraper/schema.sql`). Every claim of the form "absent from
`people`" now has to say *which* directory it means. The slug namespaces are
disjoint by construction (`uc--<source>--<name-slug>`) and the harvester
refuses a collision, so no CISUC row can be overwritten by a UC one.

**Matching runs twice, and the order is a semantic fact.** Pass 1 is the
CISUC pool and is byte-for-byte what it always was — that is what keeps every
number in this document comparable. Pass 2 runs the *unmodified* `match_name`
over the UC pool, and only for a `supervisor` mention pass 1 left
`unmatched`. It is never consulted for an author (a doctoral student is not
staff), never for a pass-1 `ambiguous` name (more candidates cannot separate
two that already fit), and never for a name pass 1 resolved (the CISUC
verdict stands). That last one is a *source-precedence* rule rather than a
quality judgement, and it is not silent: `cross_directory_fits` in the build
report lists every pass-1 resolved name a UC row also fits — reported, never
acted on. If that list ever shows systematic pass-1 wrong-person matches,
that is the evidence, and the only evidence, that reopens the merged-pool
decision.

**`exact`'s definition drifted, and this is the correction.** Above it reads
"the token sets are equal" and meant equality with *CISUC's* published
identity. It now means equality with the published form of **whichever
directory answered** — so an `exact` supervisor may be exact against a
Faculty of Economics staff page. The tier still says nothing about source;
the source is carried by the `match_note` prefix (`via UC directory feuc: …`)
and by the `directory_listings` join, and every coverage figure is split
`cisuc` / `uc_directory` so no aggregate can blur them.

**One rule was tightened, and tightening is the only direction allowed.**
`Person` gained a `source` field and `_one_folded_name` now additionally
requires one source. That rule existed for CISUC listing one human twice,
which is evidence about one site's data entry; "João Silva" at FDUC and
"João Silva" at FFUC is two people until a human says otherwise. Withholding
a collapse can only turn a `confident` into an `ambiguous`, so it buys zero
edges — and on the legacy corpus it is a no-op by construction, which is why
the golden fixture stayed green unedited. Cross-source pairs that *are* one
human are merged the house way: a `person_aliases` verdict with evidence,
which `_one_canonical` already honours across sources.

**The two rejected relaxations stay rejected, and so does option C.** No rule
in `_fits`/`_fits_full` was loosened. The lever was pool size, exactly as the
Product Owner scoped it. One consequence is worth writing down because it is
now measurable rather than hypothetical: the **superset shape** — the
directory publishes "João Carlos Freitas Arriscado Nunes" and the thesis
writes "Nunes, João Arriscado", so `_fits` rule 2 rejects a candidate
carrying given names the thesis omits — is the single largest remaining
cause of unresolved supervisors, and it is the open backlog card
`matching:uc-phd-fits-extra-cisuc-initial`. Measured on the 2690-thesis
corpus against the 1340-person UC pool: enabling the mirror comparison for
UC rows would resolve **168 more names / 278 more edges** and move 25 names
from `unmatched` to `ambiguous`. It was NOT shipped, because for a UC person
the published form *is* the full form, so a `person_full_names` entry per
slug would be a rule change wearing a curated instrument's clothes — and
because the sample contains exactly the failure this document exists to
prevent ("Almeida, Ana de" → "Ana Cristina Ferreira de Almeida", plausible
and unverified). That measurement is the Product Owner's to spend, not a
Coder's.

## Amendment, 2026-10-19: a reviewed `distinct` verdict now outranks the duplicate-row rule

Card `3fe5bf3b-9510-8137-b4cc-f53bbbbe4ec4`. The dashboard tile read "2,690
Theses / 2,686 Students" while `thesis_people WHERE role='author'` held
**2691** rows — one thesis with two authors, which the corpus invariant says
is impossible.

**What was wrong.** `data/person_aliases.json` carries both verdicts, but
only the `same` half was ever read by anything that matches. A `distinct`
verdict wrote no alias row, so it reached the matcher as *nothing at all* —
and `_one_folded_name` went on reading two `people` rows with one folded name
and one source as "a duplicate in the scraped source, not two people. All of
them are kept." For `nuno-silva-1` / `nuno-silva-2` — both published "Nuno
Silva", both CISUC, and reviewed as **two different humans** with different
mailboxes — that returned both at the `confident` tier, and
`build_thesis_facts.people_rows` writes one row per returned candidate. One
thesis mention therefore became two rows under two unrelated real people.

The inflated row count was the cheap half of the damage. Anything that joins
on `person_slug` — `sql/partner_thesis_links.sql`,
`sql/thesis_attribution_coverage.sql`, `_person_group_shares` in
`uc_phd_app/theses.py` — saw both slugs independently, so each affected
thesis was attributed in full to two people, one of whom had nothing to do
with it. `uc_phd_app/theses.py::_resolve_person_rows` groups by `name_raw`
within a thesis and the frontend reads `matched[0]`, which is exactly why the
tile showed 4 repeat students and not 5: the bug was hidden from the one
number that would have reported it.

**The fix, and why it is the only direction allowed.**
`person_aliases.distinct_pairs()` exposes the `distinct` half as sorted slug
pairs; `build()` passes it to `people_rows` and into `match_name`, which
hands it to `_same_person_twice`. A pair a human has ruled different humans
is checked *first* and settles it — no name rule gets to say two rows are one
human after somebody read both CISUC pages and wrote down that they are not.
The matcher stays a pure function of a name, a pool and that reviewed fact:
it reads no file, and with the set empty its behaviour is byte-for-byte
today's, which is what keeps every number above comparable.

Like `_one_folded_name`'s own source test, this can only ever **withhold** a
collapse, so it buys zero edges and the worst it can do is turn a `confident`
into an `ambiguous` — which is what more than one real person fitting a name
has always meant. No rule in `_fits`/`_fits_full` was touched, and the golden
fixture stayed green unedited.

The lookup is on both a row's slug **and** its canonical, because the
`luis-rodrigues` family records the `distinct` verdict against
`luis-rodrigues-3` while `luis-rodrigues` is a reviewed `same` of it. A
review is a fact about the humans, not about which of their rows somebody
happened to open.

**Measured over all 2690 theses, before and after** (distinct names, the
matcher's own report card):

| | before | after |
|---|---|---|
| `exact` | 116 | 116 |
| `confident` | 408 | **404** |
| `ambiguous` | 11 | **15** |
| `unmatched` | 4453 | 4453 |
| `thesis_people` rows | 7265 | **7260** |
| `author` rows | 2691 | **2690** (= `theses`) |
| `author_conflicts` | 29 | 29 |

`cross_directory_fits` goes 64 -> 62 in the build report, which is the two
demoted names dropping out of a list that only ever covers pass-1 *resolved*
names. Report-only, nothing written.

Every changed row was inspected. Exactly five `(handle, name_raw, role)`
mentions — four distinct names — went from two `confident` rows to one
`ambiguous` row carrying no slug, and nothing else in any table moved:

| handle | role | name_raw | was | now |
|---|---|---|---|---|
| 10316/24923 | author | Silva, João Nuno Cruz Matos Calvão da | `nuno-silva-1` + `nuno-silva-2` | ambiguous |
| 10316/101744 | supervisor | Silva, Nuno Miguel Barateiro Gonçalves | `nuno-silva-1` + `nuno-silva-2` | ambiguous |
| 10316/121216 | supervisor | Silva, João Nuno Cruz Matos Calvão da | `nuno-silva-1` + `nuno-silva-2` | ambiguous |
| 10316/123784 | supervisor | Silva, João Nuno Mestre Fernandes da | `nuno-silva-1` + `nuno-silva-2` | ambiguous |
| 10316/10200 | supervisor | Rodrigues, Luís Eduardo Teixeira | `luis-rodrigues-2` + `luis-rodrigues-3` | ambiguous |

Five rows is the whole blast radius in `thesis_people`, exhaustively: a
`GROUP BY handle, name_raw, role HAVING COUNT(*) > 1` over the rebuilt seed
returns nothing. `joao-bicker` / `joao-bicker-1` — a genuine scraped-source
duplicate under a `same` verdict — is untouched, and so is every pair with no
verdict at all; only a recorded `distinct` changes behaviour.

**One downstream figure moved, and it is the finding rather than a cost.**
For four of the five theses — `10316/24923`, `10316/101744`, `10316/121216`,
`10316/123784` — the wrong match was the **only** CISUC-resolved name they
carried, so they leave the audit's CISUC-touching universe:
`cisuc_touching_theses` 569 -> 565, `supervisor_edges` 1055 -> 1050,
`matched_edges` 626 -> 622, `matched_edges_uc_directory` 95 -> 93,
`ambiguous_edges` 3 -> 4 (`analysis/audit_unmatched_supervisors.py`). Those
four were never CISUC-attributed by anything real. The genuinely unmatched
tail every triage figure is about does not move at all — 331 edges, 279
names — and `10316/10200` stays in the universe because `filipe-araujo`
resolves on it independently.

**What this makes harder later.** `match_name` is no longer a function of two
arguments, and a new caller that forgets the third gets the old, wrong answer
silently. The default is empty rather than required on purpose — the tests
and the golden fixture call it with a pool they built themselves, where no
reviewed verdict applies — so the fence is
`tests/test_person_aliases.py::test_a_reviewed_distinct_pair_with_one_display_name_is_ambiguous_not_both`
and its control, which fail if the plumbing is dropped anywhere between
`build()` and the rule.
