# Security Policy

## Reporting a Vulnerability

If you believe you've found a security vulnerability in this repository,
please report it privately using GitHub's
[private vulnerability reporting](https://github.com/fredericowu/aw-app-uc-phd/security/advisories/new)
feature rather than opening a public issue.

We'll acknowledge your report and follow up with next steps as soon as
possible.

## Supported Versions

Only the latest version on `master` is supported. There are no maintained
release branches.

## `data/cisuc.sqlite3` is a public artefact

The committed seed database ships from this **public** repo and is published
to the marketplace on every release. Its current contents were scraped from
CISUC's own public project pages, so publishing them is fine.

That is a property of today's scrape, not of the pipeline. Nothing in CI
inspects what the scraper collected, so a future scrape that reaches a field
the site does not publish publicly would be published here on the next
release with nothing anywhere reporting it. Re-read what changed in
`data/cisuc.sqlite3` before releasing after a re-scrape.
