"""The standard declares one version, and every file agrees with it.

Three declarations had drifted: VERSION and the conformance test said 0.5.0, the README
badge still advertised 0.4.0 and pyproject.toml kept 0.1.1. A standard that cannot state
its own version is hard to cite, so the check is a test rather than a convention.
"""
import json
import re
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - older interpreters parse it manually
    tomllib = None

ROOT = Path(__file__).resolve().parent.parent


def _declared_version() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def _readme_badge_version() -> str:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r"badge/version-([0-9]+\.[0-9]+\.[0-9]+)-", readme)
    assert match, "README must carry a version badge"
    return match.group(1)


def _pyproject_version() -> str:
    raw = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if tomllib is not None:
        return str(tomllib.loads(raw)["project"]["version"])
    match = re.search(r'^version\s*=\s*"([^"]+)"', raw, re.MULTILINE)
    assert match, "pyproject.toml must declare a version"
    return match.group(1)


def test_version_is_declared_once_everywhere() -> None:
    declared = _declared_version()
    assert declared == _readme_badge_version(), "README badge disagrees with VERSION"
    assert declared == _pyproject_version(), "pyproject.toml disagrees with VERSION"


def test_changelog_covers_the_declared_version() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    declared = _declared_version()
    assert (f"## [{declared}]" in changelog) or ("## [Unreleased]" in changelog), (
        "CHANGELOG must either release the declared version or keep an Unreleased section"
    )
