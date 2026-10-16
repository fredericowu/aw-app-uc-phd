"""``contributes.agents`` — the four PhD research agents this app declares.

Three model variants of one analyst role (Fable/Sonnet/Opus) sharing a single
prompt file, plus an arbiter with its own, all inside one group whose
``instructions_file`` carries the shared Braun & Clarke methodology. The shape
is copied from ``aw-app-agents-platform-runners``'s own
``tests/test_contributed_agents.py``, which is the reference for the
one-prompt-per-family pattern.

The test that earns its keep here is ``test_referenced_files_exist``. A
``system_prompt_file``/``instructions_file`` that does not resolve is **not** an
install failure: core's ``resolve_file_fields`` drops that single field with a
log warning (``src/apps/agents.py``) and the agent seeds with an **empty system
prompt**. It looks installed, it dispatches, and it behaves like a model that
is simply bad at the job. A renamed prompt file with no test on it is therefore
a silent regression, which is why the sentinel assertions below also check the
content is still in there rather than only that the paths exist.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]

#: One prompt, three model variants — the Telegram-family pattern.
RESEARCHER_SLUGS = {"phd-fable", "phd-sonnet", "phd-opus"}
ARBITER_SLUG = "phd-quality-researcher"

RESEARCHER_PROMPT = "prompts/agents/researcher.md"
ARBITER_PROMPT = "prompts/agents/quality-researcher.md"
GROUP_INSTRUCTIONS = "prompts/agents/researchers-group.md"

CONFIG_SLUG = "uc-phd-research-config"
GROUP_SLUG = "uc-phd-researchers"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((APP_DIR / "aw-app.json").read_text())


@pytest.fixture(scope="module")
def spec(manifest) -> dict:
    return manifest["contributes"]["agents"]


@pytest.fixture(scope="module")
def agents(spec) -> dict:
    return {agent["slug"]: agent for agent in spec["agents"]}


def test_declares_the_capability_the_contribution_needs(manifest):
    # Core rejects contributes.agents without it — the install fails rather
    # than silently dropping the declaration. `agents:contribute` is risk:low
    # (src/apps/capabilities.py), so this unsigned personal-account app can
    # hold it with no signing gate.
    assert "agents:contribute" in manifest["permissions"]


def test_ships_the_four_research_agents(spec):
    assert {agent["slug"] for agent in spec["agents"]} == RESEARCHER_SLUGS | {
        ARBITER_SLUG
    }


def test_referenced_files_exist(spec):
    """The one that matters: a path that does not resolve seeds an agent with
    an empty prompt and a single log warning — no install failure, no symptom
    except an agent that reads as incompetent.
    """
    refs = [
        (group["slug"], group["instructions_file"])
        for group in spec["groups"]
        if "instructions_file" in group
    ]
    refs += [
        (agent["slug"], agent["system_prompt_file"])
        for agent in spec["agents"]
        if "system_prompt_file" in agent
    ]
    assert refs, "nothing references a file — this test would pass vacuously"
    for slug, ref in refs:
        assert (APP_DIR / ref).is_file(), f"{slug} names {ref!r}, which is absent"


def test_the_three_model_variants_share_one_prompt(agents):
    """One role, three price points. The contract has to be byte-identical or
    the comparison between the variants stops meaning anything — a divergent
    prompt is a divergent analyst, not a divergent model.
    """
    for slug in RESEARCHER_SLUGS:
        assert agents[slug]["system_prompt_file"] == RESEARCHER_PROMPT, slug
    assert agents[ARBITER_SLUG]["system_prompt_file"] == ARBITER_PROMPT


def test_every_agent_names_the_config_and_group_this_app_declares(spec, agents):
    """A dangling `agent_config_slug` does not error — it produces an agent
    with no MCP surface, and a dangling `group_slug` one that inherits no
    methodology. Both read as a broken model rather than a broken manifest.
    """
    assert {config["slug"] for config in spec["agent_configs"]} == {CONFIG_SLUG}
    assert {group["slug"] for group in spec["groups"]} == {GROUP_SLUG}
    for slug, agent in agents.items():
        assert agent["agent_config_slug"] == CONFIG_SLUG, slug
        assert agent["group_slug"] == GROUP_SLUG, slug


def test_the_model_slugs_are_the_runner_app_s_three(agents):
    """Referenced, never declared: there is no `models` key here. Declaring
    `claude-runner-*` rows ourselves would have two apps reconciling the same
    rows against competing fingerprint baselines — see the design doc's
    rejected alternatives. Nothing validates a cross-app slug reference at
    seed time, so this pins the three strings instead.
    """
    assert agents["phd-fable"]["model_slug"] == "claude-runner-fable"
    assert agents["phd-sonnet"]["model_slug"] == "claude-runner-sonnet"
    assert agents["phd-opus"]["model_slug"] == "claude-runner-opus"
    # The arbiter is the deep model: it adjudicates, it does not just code.
    assert agents[ARBITER_SLUG]["model_slug"] == "claude-runner-opus"


def test_no_models_and_no_flows_are_declared(spec):
    assert "models" not in spec
    assert "agent_flows" not in spec


def test_the_runner_provider_is_a_declared_dependency(manifest):
    """It provides both the seeding surface and the model slugs above.
    `required: false` because without it nothing seeds at all — the references
    cannot dangle in a workspace where seeding happens — and the dashboard,
    catalogue and MCP tools work regardless.
    """
    deps = {dep["id"]: dep for dep in manifest["dependencies"]["apps"]}
    assert deps["agents-platform-runners"]["required"] is False
    assert deps["agents-platform-runners"]["reason"]


def test_every_agent_disables_the_harness_tools(agents):
    """Every runner-backed agent in aw-app-agents-platform-runners' own
    manifest carries this. Copied, not invented.
    """
    for slug, agent in agents.items():
        assert agent["disable_harness_tools"] is True, slug


def test_the_config_is_declared_by_reference_not_by_url(spec):
    """`mcp_servers: ["aw-gateway"]` makes the workspace resolve the live URL
    and bearer token from its own .mcp.json at activation — and re-assert them
    on every activation, which an inline `mcp_config` would not get. A frozen
    token means the gateway 401s, the client registers zero tools, and nothing
    logs it.
    """
    config = spec["agent_configs"][0]
    assert config["mcp_servers"] == ["aw-gateway"]
    assert "mcp_config" not in config
    assert "http" not in json.dumps(config), "declared by reference names no URL"


@pytest.mark.parametrize(
    "ref",
    [GROUP_INSTRUCTIONS, RESEARCHER_PROMPT, ARBITER_PROMPT],
)
def test_the_prompt_content_survives(ref):
    """Sentinels, so gutting the content fails a test instead of shipping four
    agents that seed fine and know nothing.

    "Braun" is also what the post-install check greps for on each seeded
    agent's `system_prompt` — the group's instructions are a separate field, so
    each agent prompt has to name the methodology itself to be verifiable.
    """
    text = (APP_DIR / ref).read_text()
    assert "Braun" in text
    assert "six" in text
    # Locators, never usernames — the activity's own ethics rule, and the one
    # finding the arbiter is told to report first.
    assert "usernames" in text


def test_the_group_instructions_carry_the_six_stages_and_the_lessons():
    """The methodology lives in ONE place (the group), inherited by all four.
    These are the course's own stage names, not a generic paraphrase.
    """
    text = (APP_DIR / GROUP_INSTRUCTIONS).read_text()
    for stage in (
        "Familiarise yourself with the data",
        "Generate (initial) codes",
        "Generate initial themes",
        "Review (initial) themes",
        "Define and name themes",
        "Write-up",
    ):
        assert stage in text, stage
    assert "cyclical" in text, "the process is iterative, not a pipeline"
    for lesson in (
        "Evidential bar",
        "Topic-summary self-check",
        "Method is not finding",
        "In-vivo wording",
        "No fabricated consensus",
        "Locators, never usernames",
    ):
        assert lesson in text, lesson


def test_no_shipped_prompt_points_at_scratch_space():
    """`.tmp/` survives container recreation but is not a durable store, and
    the experiment record the content came from lives there. The prompts have
    to stand alone — a prompt that cites a scratch path ages into an
    instruction to read a file that is gone.
    """
    for ref in (GROUP_INSTRUCTIONS, RESEARCHER_PROMPT, ARBITER_PROMPT):
        text = (APP_DIR / ref).read_text()
        assert "/opt/aw-workspace/.tmp" not in text, ref
        assert ".tmp/activity3" not in text, ref


def _walk(value, path=""):
    """Every (key-path, scalar) pair in a nested declaration."""
    if isinstance(value, dict):
        for key, val in value.items():
            yield from _walk(val, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for i, val in enumerate(value):
            yield from _walk(val, f"{path}[{i}]")
    else:
        yield path, value


def test_no_declaration_ships_a_credential(spec):
    """The same guard every contributing app carries — a token pasted into a
    manifest is public the moment the repo is, and this one is.

    Checks KEYS, not a substring of the blob: the config's own description
    explains that the token is resolved at activation, and an earlier version
    of this test elsewhere flagged exactly that sentence.
    """
    for key_path, value in _walk(spec):
        leaf = key_path.rsplit(".", 1)[-1].split("[")[0].lower()
        assert leaf not in (
            "token",
            "secret",
            "api_key",
            "apikey",
            "password",
            "authorization",
        ), key_path
        if isinstance(value, str):
            assert not value.lower().startswith("bearer "), key_path
