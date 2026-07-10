"""Unit tests for the versioned prompt-template loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.agents import MissingPromptInputError, PromptNotFoundError, load_prompt

pytestmark = pytest.mark.unit


class TestBundledPrompts:
    @pytest.mark.parametrize(
        ("name", "expected_inputs"),
        [
            ("planner", ("languages", "root")),
            ("verifier", ("cwe", "location", "message", "rule_id")),
            ("repair", ("cwe", "location", "message", "rule_id")),
            ("reviewer", ("finding_summary", "patch_description", "patch_diff")),
            (
                "coordinator",
                ("false_positive_count", "finding_count", "patch_count", "verified_count"),
            ),
        ],
    )
    def test_each_bundled_v1_prompt_loads_with_the_expected_inputs(
        self, name: str, expected_inputs: tuple[str, ...]
    ) -> None:
        template = load_prompt(name, "v1")
        assert template.name == name
        assert template.version == "v1"
        assert template.inputs == expected_inputs

    def test_content_hash_is_stable_across_loads(self) -> None:
        first = load_prompt("planner", "v1")
        second = load_prompt("planner", "v1")
        assert first.content_hash == second.content_hash

    def test_missing_prompt_raises(self) -> None:
        with pytest.raises(PromptNotFoundError):
            load_prompt("does-not-exist", "v1")

    def test_missing_version_raises(self) -> None:
        with pytest.raises(PromptNotFoundError):
            load_prompt("planner", "v99")


class TestRender:
    def test_render_substitutes_every_input(self) -> None:
        template = load_prompt("planner", "v1")
        rendered = template.render(root="/repo", languages="python, javascript")
        assert "/repo" in rendered
        assert "python, javascript" in rendered

    def test_render_raises_when_an_input_is_missing(self) -> None:
        template = load_prompt("planner", "v1")
        with pytest.raises(MissingPromptInputError, match="languages"):
            template.render(root="/repo")

    def test_render_ignores_extra_unused_values(self) -> None:
        template = load_prompt("planner", "v1")
        # Extra kwargs beyond the declared inputs must not raise.
        rendered = template.render(root="/repo", languages="python", unused="ignored")
        assert "/repo" in rendered


class TestCustomPromptsDir:
    def test_loads_from_a_custom_directory_when_given(self, tmp_path: Path) -> None:
        (tmp_path / "custom").mkdir()
        (tmp_path / "custom" / "v2.md").write_text("Hello, {name}!")
        template = load_prompt("custom", "v2", prompts_dir=tmp_path)
        assert template.inputs == ("name",)
        assert template.render(name="world") == "Hello, world!"
