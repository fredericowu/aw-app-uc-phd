"""Offline build steps: code that runs once, by hand, and commits its output.

Everything here is the same shape as ``scraper/`` and
``estudo_geral_extractor/`` — a CLI you invoke deliberately, never something
the app imports at request time. The app reads the *result* out of the seed
database.
"""
