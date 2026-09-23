"""uc_phd_app/profile.py — the seed/live split and the validation rules.

Two things here fail silently if they are wrong, so both are asserted rather
than assumed: the live profile must never resolve into the package dir (an app
update would wipe an edit), and a save must land atomically (a concurrent read
in another worker must never see half a file).
"""
from __future__ import annotations

import pytest
import yaml

from uc_phd_app import paths, profile


@pytest.fixture()
def seeded(isolated_data_dir):
    """A live profile copied from the real committed seed."""
    profile.ensure_seeded()
    return paths.live_profile_path()


# ── the seed/live split ─────────────────────────────────────────────────


def test_the_committed_seed_really_exists_and_parses():
    """The seed ships in the package; if it stops parsing, every Fit request
    fails at the first call rather than at review time."""
    data = profile.parse(paths.seed_profile_path().read_text(encoding="utf-8"))
    assert len(data["interests"]) >= 1
    assert data["body"]


def test_the_seed_lives_in_the_package_and_the_live_profile_does_not(isolated_data_dir):
    """Same invariant tests/test_paths.py asserts for the database. If these
    ever resolve to the same tree, the next app update silently discards an
    edited profile."""
    assert paths.seed_profile_path().is_relative_to(paths.PACKAGE_ROOT)
    assert not paths.live_profile_path().is_relative_to(paths.PACKAGE_ROOT)


def test_first_load_copies_the_seed_into_the_data_dir(isolated_data_dir):
    live = paths.live_profile_path()
    assert not live.exists()
    data = profile.load()
    assert live.is_file()
    assert data["interests"] == profile.seed_interests()
    assert data["differs_from_seed"] is False


def test_ensure_seeded_is_idempotent_and_does_not_clobber_an_edit(seeded):
    profile.save(["quantum error correction"])
    profile.ensure_seeded()
    assert profile.load()["interests"] == ["quantum error correction"]


def test_a_missing_seed_is_a_profile_error_not_a_crash(isolated_data_dir, monkeypatch):
    monkeypatch.setattr(paths, "seed_profile_path",
                        lambda: paths.data_dir() / "nope.md")
    with pytest.raises(profile.ProfileError, match="no committed profile seed"):
        profile.ensure_seeded()


# ── divergence from the committed baseline ──────────────────────────────


def test_an_edited_profile_reports_that_it_diverges_from_the_seed(seeded):
    data = profile.save(["computational creativity"])
    assert data["differs_from_seed"] is True
    assert data["seed_interests"] == profile.seed_interests()


def test_reset_restores_the_committed_baseline(seeded):
    profile.save(["computational creativity"])
    data = profile.reset_to_seed()
    assert data["interests"] == profile.seed_interests()
    assert data["differs_from_seed"] is False


def test_reset_without_a_seed_is_a_profile_error(seeded, monkeypatch):
    monkeypatch.setattr(paths, "seed_profile_path",
                        lambda: paths.data_dir() / "nope.md")
    with pytest.raises(profile.ProfileError, match="no committed profile seed"):
        profile.reset_to_seed()


def test_seed_interests_reports_none_when_the_seed_is_unreadable(seeded, monkeypatch):
    """Divergence reporting must never be a reason to fail a request — the
    live profile is what actually matters."""
    monkeypatch.setattr(paths, "seed_profile_path",
                        lambda: paths.data_dir() / "nope.md")
    assert profile.seed_interests() is None
    data = profile.load()
    assert data["differs_from_seed"] is False


# ── validation ──────────────────────────────────────────────────────────


def test_interests_must_be_a_list():
    with pytest.raises(profile.ProfileError, match="must be a list"):
        profile.validate_interests("artificial intelligence")


def test_a_non_text_interest_is_rejected():
    with pytest.raises(profile.ProfileError, match="is not text"):
        profile.validate_interests(["ai", 42])


def test_an_empty_list_is_rejected():
    with pytest.raises(profile.ProfileError, match="at least one interest"):
        profile.validate_interests([])


def test_blank_and_whitespace_only_interests_are_dropped():
    assert profile.validate_interests(["  ai  ", "   ", ""]) == ["ai"]


def test_internal_whitespace_is_normalised():
    assert profile.validate_interests(["secure\n  software   architecture"]) == [
        "secure software architecture"]


def test_too_many_interests_are_rejected():
    with pytest.raises(profile.ProfileError, match="too many"):
        profile.validate_interests([f"topic {i}" for i in range(profile.MAX_INTERESTS + 1)])


def test_a_pasted_paragraph_is_rejected_rather_than_silently_averaged():
    """The facet split exists because one long averaged vector ranks badly.
    Pasting a paragraph into a single interest line would quietly recreate
    exactly that, so it fails loudly instead."""
    with pytest.raises(profile.ProfileError, match="not a paragraph"):
        profile.validate_interests(["x" * (profile.MAX_INTEREST_CHARS + 1)])


# ── parsing / rendering ─────────────────────────────────────────────────


def test_missing_front_matter_delimiters_are_rejected():
    with pytest.raises(profile.ProfileError, match="no YAML front matter"):
        profile.parse("interests:\n- ai\n")


def test_unterminated_front_matter_is_rejected():
    with pytest.raises(profile.ProfileError, match="not terminated"):
        profile.parse("---\ninterests:\n- ai\n")


def test_non_mapping_front_matter_is_rejected():
    with pytest.raises(profile.ProfileError, match="not a mapping"):
        profile.parse("---\n- just\n- a\n- list\n---\n\nbody\n")


def test_render_round_trips_through_parse():
    text = profile.render(["ai", "security"], "Some prose.", {"source": "cv"})
    data = profile.parse(text)
    assert data["interests"] == ["ai", "security"]
    assert data["body"] == "Some prose."
    assert data["front_matter"]["source"] == "cv"


def test_saving_preserves_provenance_keys_from_the_seed(seeded):
    """An edit to the interest list must not silently drop the record of
    where the profile came from."""
    before = profile.load()["front_matter"]
    profile.save(["ai"])
    after = profile.load()["front_matter"]
    assert after.get("source") == before.get("source")
    assert after.get("seeded_from") == before.get("seeded_from")


def test_saving_keeps_the_body_unless_it_is_replaced(seeded):
    body = profile.load()["body"]
    profile.save(["ai"])
    assert profile.load()["body"] == body
    profile.save(["ai"], "replaced prose")
    assert profile.load()["body"] == "replaced prose"


# ── the parts that fail silently ────────────────────────────────────────


def test_a_save_lands_atomically_and_leaves_no_temp_file(seeded):
    """os.replace, not a truncate-and-write: a GET /api/fit in another worker
    must never observe a half-written profile."""
    profile.save(["ai", "security"])
    leftovers = list(paths.data_dir().glob(".profile-*"))
    assert leftovers == []
    assert yaml.safe_load(
        seeded.read_text(encoding="utf-8").split("---\n")[1])["interests"] == [
            "ai", "security"]


def test_load_is_not_cached_so_another_workers_write_is_seen(seeded):
    """Nothing is memoised in module state — at WORKERS>1 there is no
    cross-process invalidation, so a stale module-level cache would serve a
    profile that was edited seconds ago in a different process."""
    assert profile.load()["interests"] == profile.seed_interests()
    # Simulate the other worker by writing the file directly.
    seeded.write_text(profile.render(["edited elsewhere"], "body"), encoding="utf-8")
    assert profile.load()["interests"] == ["edited elsewhere"]


def test_save_rejects_a_bad_list_before_touching_the_file(seeded):
    before = seeded.read_text(encoding="utf-8")
    with pytest.raises(profile.ProfileError):
        profile.save([])
    assert seeded.read_text(encoding="utf-8") == before
