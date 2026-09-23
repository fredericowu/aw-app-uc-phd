# Distribution migration — tekflox/private → fredericowu/public

**Architect delta plan. Distribution layer ONLY.** The app itself is built,
installed, verified by QA (82 tests, 100% coverage, every view driven live,
`doctor` exits 0). Nothing below changes how the app works. It changes where
it lives and who can get it.

This supersedes the distribution section of `docs/app-migration-plan.md`
(commit `8d21c03`) and nothing else in it. Frederico's 08:00 instruction —
*"eu quero a app publica no github fredericowu/ e no aw-marketplace publico
(de tekflox)"* — is the authority; the Product Owner's 08:42 comment on card
`3e45bf3b-9510-811d-8d16-ebf126984c0a` is the scoping.

---

## 0. The decision, in one paragraph

**Publish by re-homing, not by flipping a switch.** Create a *brand-new* repo
under `fredericowu`, created **private**, push a history that has already had
`docs/uc` removed, verify the scrub *against the remote*, and only then flip
that repo to public. `tekflox/aw-app-uc-phd` is **archived, never transferred
and never made public**, because it permanently holds the unscrubbed objects.
Then delete the private catalog entry, add the public one naming the new repo,
and move the running install across with the one call built for exactly this —
`POST /api/apps/aw-app-uc-phd/update`, which re-derives `signed` from the
catalog instead of carrying the old value forward.

The reason it is a new repo rather than a transfer + force-push is the only
irreversible step in this card. A force-push does not delete anything on
GitHub: the old objects stay reachable by SHA at `github.com/<owner>/<repo>/
commit/<sha>` and through the events API for an indeterminate period. A repo
that has *never contained* the PDFs cannot leak them no matter what we get
wrong. That property is worth more than the convenience of `gh repo transfer`.

---

## 1. ⚠️ HARD ORDERING CONSTRAINT — read this before touching anything

`docs/uc` holds University of Coimbra material (the PhD kick-off deck, an
Open Science / Open Access talk, a RAUC 2025 despacho). **No code reads them**
— confirmed by the Product Owner across the backend, the SPA, the `sql` files
and the manifest. They are scraper-repo leftovers.

They are in history. Enumerated, not assumed — every blob path that has ever
existed in this repo matching a doc:

```
docs/PhD-Kick-off.pdf                                        <- pre-move, commit 26bfc57
docs/uc/PhD-Kick-off.pdf
docs/uc/OpenScience_OpenAccess.pdf
docs/uc/comunicacao-cientifica.pdf
docs/uc/comunicacoes-gerais/RAUC-2025-alteracoes-despacho-10347-2026.pdf
```

Note the first line. The PO's brief named four commits (`36f399b`, `36637cb`,
`b6c97a3`, `4aa2e4d`); there is a **fifth**, `26bfc57`, which added the deck at
`docs/PhD-Kick-off.pdf` *before* `4aa2e4d` moved it into `docs/uc/`. A filter
scoped to `docs/uc` alone leaves that blob behind. This is why the gate below
is expressed as "**zero PDF blobs anywhere in history**" and not as "`docs/uc`
is gone" — the assertion has to be stronger than the enumeration, because the
enumeration is the part that can be wrong.

### The sequence. Do not reorder it. Do not run step 5 early.

| # | Step | Gate before moving on |
|---|---|---|
| 1 | Scrub history in a throwaway clone | local blob scan returns zero PDFs |
| 2 | Create `fredericowu/aw-app-uc-phd` **`--private`** | `gh repo view` says PRIVATE |
| 3 | Push scrubbed history + tag to it | push succeeds |
| 4 | **Re-clone from the remote** and scan *that* | zero PDF blobs in the clone |
| 5 | `gh repo edit --visibility public` | only after step 4 passed |
| 6 | Archive `tekflox/aw-app-uc-phd` | `isArchived: true` |

Step 2 creating it **private** is the whole safety valve. If the scrub is
wrong you find out at step 4, while it is still private, and you delete the
repo and start over at zero cost. Create it public and a bad push is public
the instant it lands — and the PO's constraint ("a scrub failure cannot be
discovered after publication") is violated by construction.

Step 4 re-clones *from GitHub* rather than re-scanning the local copy. Scanning
the thing you just built proves your script ran; scanning what the server
actually accepted proves what the world will be able to fetch. They are not
the same claim, and only the second one matters here.

### How to scrub

`git filter-repo` is **not installed** in this container (`which git-filter-repo`
→ nothing). Install it first (`pip install --user git-filter-repo`, or fetch the
single-file script). Do not reach for `git filter-branch` — it is deprecated,
it mishandles tags, and getting it subtly wrong here is expensive.

Work in `.tmp/uc-phd-scrub/` (workspace convention, `CLAUDE.md`), from a fresh
`git clone` of `/opt/aw-workspace/repos/aw-app-uc-phd`. **Do not rewrite history
in place under `repos/`** — that tree is shared by every concurrent agent in
this workspace, and it is the checkout a human may be looking at.

Remove `docs/uc` *and* `docs/PhD-Kick-off.pdf` with `--invert-paths`.
`filter-repo` rewrites the `v0.1.0` tag along with the commits, which is what
we want — the tag must point into the new history.

### The gate, stated as a command

The check that decides whether step 5 is allowed. Run it on the clone from
step 4, not on your working copy:

```
git rev-list --objects --all \
  | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' \
  | awk '$1=="blob"' | grep -i '\.pdf'
```

Empty output, or step 5 does not happen. Paste the output (or its emptiness)
into the card — QA has to be able to see that this ran.

Also sanity-check that the scrub removed *only* what it was meant to:
`data/cisuc.sqlite3` (the packaged seed, ~1.9 MB) and `ui/dist/assets/*.js`
must still be tracked afterwards. `data/cisuc.sqlite3` is load-bearing —
`uc_phd_app/paths.py:53` resolves the seed to `<repo>/data/cisuc.sqlite3`, and
without it a fresh install activates into `{"action": "no_seed"}` and serves an
empty app. Losing it would pass every test in this repo and fail in production.

The CISUC projects data itself stays. It was scraped from a public page.

---

## 2. 🔴 Blocker the brief did not anticipate: CI dies on the move, and one
## workflow must not follow the repo into public

All three workflows in `.github/workflows/` pin `runs-on: [self-hosted,
aw-baremetal]` — `test.yml:22`, `test.yml:62`, `security-scan.yml:26,47,67`,
and `release.yml` inherits it from the reusable workflow. Those runners live in
tekflox org runner group 3 (`aw-private`). **A GitHub org runner group can only
be shared with repositories in that org.** A personal-account repo cannot be
added to it — the `PUT /orgs/tekflox/actions/runner-groups/3/repositories/<id>`
call the Coder used at 08:28 has no equivalent for `fredericowu/*`.

So on the day of the move, the repo's verified-green Test CI stops running.
Not fails — *queues forever*, which is worse, because a queued check reads as
"still going" rather than "gone".

**Fix: `runs-on: ubuntu-latest` in `test.yml` and `security-scan.yml`.**
GitHub-hosted runners are free and unmetered on public repositories, so going
public is what pays for this. Both suites are ordinary Python + Node; nothing
in them needs the bare-metal host.

There is a second reason, and it is the one that makes this non-optional rather
than merely tidy. `test.yml:16` triggers on an unqualified `pull_request:`.
Today the repo is private, so only org members can open one. **Public + fork PR
+ self-hosted runner is arbitrary code execution on the bare-metal host that
runs this entire workspace** — `actions/checkout` fetches the stranger's branch
and `pytest tests/` runs it. Right now that is latent rather than live, because
the runners are unreachable from a personal repo anyway; but "unreachable by
accident of ownership" is not a control, and the first person who 'fixes' the
queueing by pointing it at a reachable runner arms it. Move to `ubuntu-latest`
in the same commit as the visibility flip, not after.

This is in scope: it is the distribution change breaking something that
currently works, which is ours to carry, not a new feature.

---

## 3. The repo move

**Create `fredericowu/aw-app-uc-phd` fresh. Do not `gh repo transfer`.**

A transfer moves the *same* repo object, unscrubbed objects and all, into the
account that is about to host the public one. Every later mistake then has the
PDFs within reach. A new repo is a clean-room; the cost is losing GitHub's
automatic redirect from the old URL, which is worth nothing here because the
old URL is six hours old, private, and referenced by exactly one thing we are
deleting anyway (the private catalog entry).

**The old repo: archive it.** Archiving is immediate, reversible, and stops
any accidental push or release from landing there while the catalog still has
stale references in flight.

**Recommend deleting it afterwards, but do not delete it in this run.** Its
only unique content is precisely the material we just decided must not be
distributed, and it has no issues, PRs, forks or dependents — so keeping it is
liability without upside. But deletion is irreversible and needs `delete_repo`,
and the Coder should not be exercising that scope on a judgement call. Put the
recommendation on the card and let Frederico say yes.

**Manifest edit:** `aw-app.json` → `"publisher": "TekFlox"` becomes
`"publisher": "fredericowu"`. This is the one manifest line that changes, and
it matters because `sync_catalog_entry.py` copies `publisher` verbatim into
the catalog entry that every workspace on the public marketplace will read.
Keeping "TekFlox" on an app owned by a personal account is just wrong metadata.

**Do not bump the version.** No app behaviour changed, and — see §5 — the
update route explicitly handles a same-version trust change. A bump would be a
claim that something shipped.

**Re-point the local checkout by deleting and re-cloning**, not with `git remote
set-url` + `git reset --hard`. The scrubbed history has entirely different
SHAs, the old objects would linger in the local object store, and a fresh clone
doubles as independent evidence that what is published is what we think is
published. (`git reset --hard` in a bind-mounted tree here has bitten before —
it orphans inodes other processes still hold.)

---

## 4. The catalog

Two edits, and the **order between them is load-bearing**.

### 4a. Remove the entry from `tekflox/aw-marketplace-private` FIRST

Not hygiene. Load-bearing, and the mechanism is not obvious:

- `marketplace_sources()` (`src/apps/catalog.py:107-131`) puts **registry
  sources before env-derived ones**. This workspace has `tekflox-private`
  registered (`.aw-workspace/marketplace_sources.json`), so the merge order is
  `tekflox/aw-marketplace-private@master` **then** `tekflox/aw-marketplace@master`.
- `_merge_sources` (`src/apps/catalog.py:369-381`) dedupes by app id,
  **first source wins** — `if app_id in seen: continue`.
- `is_marketplace_app` (`src/apps/catalog.py:463-497`) requires
  `app["_source"] == official`, where official is the *public* repo.

So while both entries exist, the merged catalog resolves `aw-app-uc-phd` to the
**private** entry, `_source` is the private spec, and the workspace answers
`signed: false` — no matter how correct the public entry is.

Worse than merely not working: `aw-backend`'s twin
(`repos/aw-backend/src/api/marketplace_catalog.py:79-91`) reads **only** the
public catalog and matches on `(app_id, row.repo)`. Once the install row names
`fredericowu/aw-app-uc-phd` it will answer `signed: true` while the workspace
answers `false`. `Reconciler.reconcile` treats exactly that disagreement as
drift (`src/apps/reconciler.py:1054-1060`, `loaded.signed != spec.signed`) and
responds with uninstall + install — **on every pass**. That is the reinstall
loop the PO asked us to avoid, it is reachable from here, and leaving the
private entry in place is the thing that causes it. `catalog.py:478-486` warns
about this case in prose; this is it, concretely.

Touch nothing else in that catalog. `crispal`'s entry is not ours.

### 4b. Add the entry to `tekflox/aw-marketplace`

Generate it with `repos/aw-marketplace/scripts/sync_catalog_entry.py` — the
same script CI runs — rather than hand-writing JSON. `apply_to_catalog` appends
a conservative first entry when the id is absent, which is our case.

**The `repo` field must read exactly `fredericowu/aw-app-uc-phd`.** aw-backend
compares it with `==` and no normalisation (`marketplace_catalog.py:89`); the
workspace lowercases both sides (`catalog.py:492`). The strict one wins. A
stray capital, or a leftover `tekflox/`, leaves the app unsigned after all this
work, and the symptom is a silent `signed: false` rather than an error.

`ref` stays `v0.1.0`, pointing at the rewritten tag in the new repo.

Validate before opening the PR: `python3 tests/validate_apps.py apps.json` from
`repos/aw-marketplace`. The release workflow runs this for a reason — entries
have merged before that failed the schema, because the only enforcement was a
downstream check nobody had to wait for.

This PR needs a **human merge**. See §6 — that is correct behaviour here, not
an obstacle.

---

## 5. Moving the running install across — one call, not uninstall/install

Current row: `repo=tekflox/aw-app-uc-phd`, `ref=v0.1.0`, `signed=false`, both
permissions granted, data dir seeded. Target: same app, `repo=fredericowu/...`,
`signed=true`.

**Do not hand-roll uninstall + install.** Use:

```
POST /api/apps/aw-app-uc-phd/update
```

`src/apps/routes.py:830-930`. It does precisely this job:

- re-resolves the catalog entry with `get_catalog(force=True)` (:852),
- takes `catalog_repo` from it (:863),
- computes `trust_is_stale = loaded.signed != is_marketplace_app(slug,
  catalog_repo)` (:873) — so a **same-version trust change is not a no-op**,
  which is exactly our situation and the reason no version bump is needed,
- writes a new `AppSpec` carrying the **new repo** and
  `signed=is_marketplace_app(...)` **re-derived, not carried over** (:910; the
  comment there records the 2026-08-13 `tasks` incident where sticky trust left
  an app permanently unsigned with no escape but a config-wiping reinstall),
- pushes the desired row to the cloud registry and reconciles.

`reconcile` then sees `trust_changed` and does one clean upgrade cycle.

Nothing to do about the CLI: `aw-workspace-cli marketplace install
aw-app-uc-phd --update` drives this same route.

### The seeded SQLite survives — assert it, don't assume it

The upgrade is uninstall + install internally, so this needs to be checked
rather than hoped:

- `_uninstall_provisioned` removes `apps_root()/<slug>` (the package dir) and
  the mirror/cloud rows. It **never touches** `AW_WORKSPACE_HOME/data/<app_id>/`
  (`src/apps/reconciler.py:884-923`).
- The live DB is at `.aw-workspace/data/aw-app-uc-phd/cisuc.sqlite3`
  (`uc_phd_app/paths.py:39-58`), outside the package dir by design.
- On reinstall, `ensure_seeded()` finds `live.is_file()`, reads the stamp
  (`app_version` `0.1.0`), and `_version_tuple(version) <= _version_tuple(
  seeded_version)` returns `{"action": "kept"}` — no copy, no overwrite
  (`uc_phd_app/seed.py:95-125`).
- Config also survives: uninstall snapshots it via `config_store.save()` before
  dropping the rows, and install reads it back (`reconciler.py:895-907`).

**Coder: record the DB's inode and mtime before and after, and assert both are
unchanged.** "The app still works" does not distinguish "we kept the data" from
"we silently re-seeded over it" — the seed and the live DB are byte-identical
today, so the failure is invisible right up until someone runs the scraper.

### Sequencing, and why it will look broken for a few minutes

The catalog reaches this workspace through GitHub's raw CDN, which lags merges
by up to ~5 minutes; `get_catalog(force=True)` bypasses the local 300s TTL but
not the CDN. So: merge both catalog PRs → confirm the raw `apps.json` URLs
actually reflect them → *then* call update. Calling it early resolves the stale
catalog, finds `trust_is_stale` false and the version equal, and returns
**`{"status": "no-op"}`** (:876-880) — a success response that changed nothing.
That is the one failure here that looks like success; if you see `no-op`, the
catalog had not landed yet.

---

## 6. The release credential — the honest answer

**It does not get solved in this card, and it is not one problem.**

1. **The runner.** `app-release.yml` in `tekflox/aw-marketplace` hardcodes
   `runs-on: [self-hosted, aw-baremetal]`. Personal repos cannot reach tekflox's
   org runner group. No token fixes this; the job queues forever. Unlike
   `test.yml`, we cannot fix it locally — `runs-on` lives inside the reusable
   workflow, not in our caller.
2. **The secret.** `secrets: inherit` on a personal repo inherits repo and
   environment secrets only; there are no org secrets to inherit. So
   `MARKETPLACE_SYNC_TOKEN` would have to be a repo-level secret on
   `fredericowu/aw-app-uc-phd`.
3. **What that secret must be able to do.** Push a branch to and open a PR on
   `tekflox/aw-marketplace` — i.e. **write access to a tekflox org repo, stored
   inside a repo Frederico owns personally.** That is a privilege decision, and
   it is his, not a Coder's. It was the right call to refuse at 08:28 and it is
   the right call now.
4. **Auto-merge will not fire either**, and that one is *good news*. The
   auto-merge step is gated `startsWith(github.repository, 'tekflox/')`, which a
   `fredericowu/*` repo does not match. The sync PR opens and waits for a human.
   For a catalog that every workspace in the world reads, a human gate on a
   non-org contributor is the behaviour you want. Do not try to defeat it.

**Decision: do not wire release CI. Change `release.yml` to
`workflow_dispatch`-only, point its `catalog_repo` at the public catalog, and
write items 1–3 into the file as a comment explaining why it cannot run yet.**

Dispatch-only, rather than deleted, because the moment the privilege question
is answered it is one setting away from working — and because the reasoning is
worth more in the file than on a card. Leaving the `push: master` trigger would
make master permanently red and teach everyone to ignore red CI on this repo.

Hand-sync `v0.1.0` into the public catalog with `sync_catalog_entry.py` (§4b),
exactly as the Coder did at 08:28 for the private one. This is a legitimate
stopgap, not a workaround — the script is the same one CI would run.

**Raise to Frederico, do not decide:** if he wants release CI green, the
smallest shape is a **fine-grained** PAT scoped to `tekflox/aw-marketplace`
(Contents: write, Pull requests: write) plus `fredericowu/aw-app-uc-phd`
(Contents: write), stored as a repo secret — far narrower than the full-scope
`admin:org` / `delete_repo` PAT that was correctly refused. It still does not
solve (1). **Do not mint, store, or widen any token to make this pass.** If
someone later wants (1) fixed properly, that is a `runs_on` input on
`tekflox/aw-marketplace`'s reusable workflow — a change affecting 50+ apps, and
its own card.

---

## 7. Fold in while you are here (does NOT gate anything)

`test_concurrent_activation_never_leaves_a_partial_database` passes with
`_atomic_copy` reverted to a plain `shutil.copyfile`, so it proves nothing —
QA mutation-tested this. The 8-thread barrier races `ensure_seeded()`, but
`live.is_file()` short-circuits after the first writer and every writer copies
identical bytes, so no reader ever observes a torn file.

To make it real, the test has to observe a *reader* mid-write: have the racing
threads open and query the live DB while a writer is copying a **deliberately
different, larger** payload, and assert the reader either sees the complete old
file or the complete new one, never a short read. Mutation-test the result —
revert `_atomic_copy` and confirm it goes red.

**Ship the distribution change even if this is still weak.** PO was explicit.

---

## 8. What this closes off

- **Release automation stays manual until a human privilege call is made.**
  Every catalog update for this app is hand-run and hand-merged. That is the
  real price of the personal namespace, and it recurs on every version.
- **The app leaves the org's blast radius for good things too** — org secrets,
  the shared self-hosted runners, org-wide security policy and Dependabot
  configuration. Public GitHub-hosted runners cover CI, but anything that
  assumed "all our apps are under tekflox" now has an exception.
- **The name and description are public forever.** The public catalog is a
  public file; removal is possible, un-indexing is not.
- **The private-catalog path is no longer available to this app without
  undoing all of it.** If it ever has to go private again: new repo, entry
  moved back, another trust flip — and everything already fetched stays
  fetched.
- **The seed DB is now shipped from a public repo.** ~1.9 MB of CISUC project
  data, publicly scraped and fine to publish today. But `data/cisuc.sqlite3` is
  now a *public* artefact, so any future scrape that pulls a non-public field
  publishes it on the next release with nothing in the pipeline to notice.
  Worth a `SECURITY.md` line.

---

## 9. Risks for the Coder — the non-obvious ones

1. **The fifth commit.** `26bfc57` has the deck at `docs/PhD-Kick-off.pdf`,
   outside `docs/uc`. The PO's list of four is incomplete. Filter on both
   paths; gate on "zero PDF blobs", which catches a sixth if there is one.
2. **`no-op` is the silent failure of §5.** A success response that changed
   nothing, caused by calling update before the CDN served the new catalog.
   Check `signed` afterwards; do not trust the 200.
3. **Leaving the private entry in place produces a reinstall loop**, not a
   harmless duplicate — the two trust oracles disagree permanently and
   `reconcile` fights itself every pass (§4a).
4. **`repo` string matching is exact on the aw-backend side.** No lowercasing,
   no normalisation. A casing slip costs you `signed: false` with no error
   anywhere.
5. **Do not rewrite history in `repos/aw-app-uc-phd`.** Shared working tree,
   concurrent agents, and it is the checkout a human may have open.
6. **Do not `git reset --hard` to re-point the local clone.** Delete and
   re-clone. Bind-mounted inodes have been orphaned this way before.
7. **`data/cisuc.sqlite3` must survive the scrub.** It is the packaged seed
   (`uc_phd_app/paths.py:53`). Losing it passes every test in this repo and
   produces an empty app on a fresh install.
8. **`ui/dist` is committed and gated** by `test.yml`'s `ui-dist-is-current`
   job. If you touch `ui/src` for any reason, rebuild — and note that gate only
   runs again once §2's `runs-on` fix lands.
9. **Archive, do not transfer, the old repo.** A transfer carries the
   unscrubbed objects into the account hosting the public repo.
10. **Assert the DB's inode and mtime across the update.** "It still works"
    cannot tell "kept" from "silently re-seeded".

---

## 10. Done means

- `gh repo view fredericowu/aw-app-uc-phd --json owner,visibility` → owner
  `fredericowu`, visibility `PUBLIC`.
- The PDF blob scan, run against a **fresh clone of the public remote**,
  returns nothing. Output pasted on the card.
- `tekflox/aw-marketplace` `apps.json` contains `aw-app-uc-phd` with
  `repo: fredericowu/aw-app-uc-phd`; `tekflox/aw-marketplace-private` no longer
  contains it; `crispal`'s entry is untouched.
- `GET /api/apps` reports `signed: true` for `aw-app-uc-phd`, with
  `permissions: ["fs:workspace-data", "routes:register"]` and **nothing
  refused**.
- `aw-workspace-cli doctor` exits 0.
- The live DB at `.aw-workspace/data/aw-app-uc-phd/cisuc.sqlite3` has the same
  inode and mtime it had before the update.
- `test.yml` and `security-scan.yml` run on `ubuntu-latest`; a Test run on the
  new repo is green.
- `tekflox/aw-app-uc-phd` is archived, with a card note recommending deletion.
- `release.yml` is dispatch-only, targets the public catalog, and carries the
  §6 explanation. **No new token was minted, stored or widened.**
