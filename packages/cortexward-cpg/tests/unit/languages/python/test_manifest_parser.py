"""Unit tests for dependency-manifest parsing.

Exercises each supported manifest format against real file content written
to `tmp_path` — no mocking of the filesystem or TOML/INI parsers, since the
whole point of this module is correctly reading real-world manifest syntax.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cortexward.languages.python import Dependency, DependencyKind, parse_dependencies

pytestmark = pytest.mark.unit


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


class TestPyprojectToml:
    def test_runtime_dependencies_are_parsed(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "pyproject.toml",
            '[project]\ndependencies = ["requests>=2.0", "pydantic~=2.0"]\n',
        )
        deps = parse_dependencies(path)
        assert Dependency("requests", ">=2.0", "pyproject.toml", DependencyKind.RUNTIME) in deps
        assert Dependency("pydantic", "~=2.0", "pyproject.toml", DependencyKind.RUNTIME) in deps

    def test_optional_dependencies_are_parsed_as_optional(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "pyproject.toml",
            '[project]\n[project.optional-dependencies]\ndev = ["pytest>=7.0", "ruff"]\n',
        )
        deps = parse_dependencies(path)
        assert Dependency("pytest", ">=7.0", "pyproject.toml", DependencyKind.OPTIONAL) in deps
        assert Dependency("ruff", None, "pyproject.toml", DependencyKind.OPTIONAL) in deps

    def test_a_dependency_with_no_version_constraint_has_none(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "pyproject.toml", '[project]\ndependencies = ["click"]\n')
        deps = parse_dependencies(path)
        assert Dependency("click", None, "pyproject.toml", DependencyKind.RUNTIME) in deps

    def test_a_pyproject_with_no_project_table_yields_no_dependencies(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "pyproject.toml", "[tool.ruff]\nline-length = 100\n")
        assert parse_dependencies(path) == ()

    def test_malformed_toml_yields_no_dependencies(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "pyproject.toml", "this is not [ valid toml\n")
        assert parse_dependencies(path) == ()

    def test_a_non_string_dependency_entry_is_skipped(self, tmp_path: Path) -> None:
        # `dependencies` should be a list of strings per PEP 621; a
        # malformed manifest with a non-string entry must not crash.
        path = _write(tmp_path, "pyproject.toml", '[project]\ndependencies = [123, "click"]\n')
        deps = parse_dependencies(path)
        assert deps == (Dependency("click", None, "pyproject.toml", DependencyKind.RUNTIME),)

    def test_an_unparseable_dependency_string_is_skipped(self, tmp_path: Path) -> None:
        # A leading underscore isn't a valid package-name start character;
        # the line is silently skipped, not guessed at.
        path = _write(tmp_path, "pyproject.toml", '[project]\ndependencies = ["_bad", "click"]\n')
        deps = parse_dependencies(path)
        assert deps == (Dependency("click", None, "pyproject.toml", DependencyKind.RUNTIME),)

    def test_a_non_list_optional_dependency_group_is_skipped(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "pyproject.toml",
            '[project]\n[project.optional-dependencies]\ndev = "not-a-list"\ntest = ["pytest"]\n',
        )
        deps = parse_dependencies(path)
        assert deps == (Dependency("pytest", None, "pyproject.toml", DependencyKind.OPTIONAL),)


class TestRequirementsTxt:
    def test_plain_and_versioned_requirements_are_parsed(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "requirements.txt", "requests==2.31.0\nclick\n")
        deps = parse_dependencies(path)
        assert (
            Dependency("requests", "==2.31.0", "requirements.txt", DependencyKind.RUNTIME) in deps
        )
        assert Dependency("click", None, "requirements.txt", DependencyKind.RUNTIME) in deps

    def test_comments_and_blank_lines_are_skipped(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path, "requirements.txt", "# a comment\n\nrequests==2.31.0  # inline comment\n"
        )
        deps = parse_dependencies(path)
        assert deps == (
            Dependency("requests", "==2.31.0", "requirements.txt", DependencyKind.RUNTIME),
        )

    def test_an_unparseable_line_is_skipped(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "requirements.txt", "_bad\nrequests\n")
        deps = parse_dependencies(path)
        assert deps == (Dependency("requests", None, "requirements.txt", DependencyKind.RUNTIME),)

    def test_option_lines_are_skipped(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "requirements.txt", "-r base.txt\n--hash=sha256:abc\nrequests\n")
        deps = parse_dependencies(path)
        assert deps == (Dependency("requests", None, "requirements.txt", DependencyKind.RUNTIME),)

    def test_requirements_dev_txt_is_classified_as_dev(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "requirements-dev.txt", "pytest\n")
        deps = parse_dependencies(path)
        assert deps == (Dependency("pytest", None, "requirements-dev.txt", DependencyKind.DEV),)


class TestSetupCfg:
    def test_install_requires_is_parsed_as_runtime(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "setup.cfg",
            "[options]\ninstall_requires =\n    requests>=2.0\n    click\n",
        )
        deps = parse_dependencies(path)
        assert Dependency("requests", ">=2.0", "setup.cfg", DependencyKind.RUNTIME) in deps
        assert Dependency("click", None, "setup.cfg", DependencyKind.RUNTIME) in deps

    def test_extras_require_is_parsed_as_optional(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "setup.cfg",
            "[options.extras_require]\ndev =\n    pytest>=7.0\n    ruff\n",
        )
        deps = parse_dependencies(path)
        assert Dependency("pytest", ">=7.0", "setup.cfg", DependencyKind.OPTIONAL) in deps
        assert Dependency("ruff", None, "setup.cfg", DependencyKind.OPTIONAL) in deps

    def test_a_setup_cfg_with_neither_section_yields_no_dependencies(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "setup.cfg", "[metadata]\nname = mypackage\n")
        assert parse_dependencies(path) == ()

    def test_malformed_ini_yields_no_dependencies(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "setup.cfg", "not valid ini [[[\n=broken\n")
        assert parse_dependencies(path) == ()


class TestPipfile:
    def test_packages_and_dev_packages_are_classified_separately(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "Pipfile",
            '[packages]\nrequests = ">=2.0"\nclick = "*"\n\n[dev-packages]\npytest = "*"\n',
        )
        deps = parse_dependencies(path)
        assert Dependency("requests", ">=2.0", "Pipfile", DependencyKind.RUNTIME) in deps
        assert Dependency("click", None, "Pipfile", DependencyKind.RUNTIME) in deps
        assert Dependency("pytest", None, "Pipfile", DependencyKind.DEV) in deps

    def test_a_pipfile_with_neither_table_yields_no_dependencies(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "Pipfile", '[requires]\npython_version = "3.11"\n')
        assert parse_dependencies(path) == ()


class TestUnsupportedManifests:
    def test_setup_py_is_explicitly_out_of_scope(self, tmp_path: Path) -> None:
        # Extracting install_requires from setup.py would require executing
        # it, which violates the non-execution guarantee (ADR-0004).
        path = _write(
            tmp_path,
            "setup.py",
            "from setuptools import setup\nsetup(install_requires=['requests'])\n",
        )
        assert parse_dependencies(path) == ()

    def test_an_unrecognized_filename_yields_no_dependencies(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "poetry.lock", "# not a manifest we parse\n")
        assert parse_dependencies(path) == ()

    def test_a_missing_file_yields_no_dependencies(self, tmp_path: Path) -> None:
        assert parse_dependencies(tmp_path / "pyproject.toml") == ()
