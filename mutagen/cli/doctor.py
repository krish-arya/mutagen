"""Environment diagnostics for ``mutagen doctor``.

Designed for the **PyPI-installed** experience: after ``pip install mutagen``
the heavy integrations (Anthropic SDK, mutmut, coverage, pytest) are *extras*,
so the most common first-run failure is "I installed mutagen but it can't find
mutmut." This command diagnoses exactly that — it inspects the *installed*
environment via :mod:`importlib`, checks the runtime tools (Python, git), and
reports which LLM provider key is present — then prints the precise remedy
(usually ``pip install 'mutagen[...]'``) for anything missing.

It performs no network calls and never prints secret values — only whether a
key is set.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass

# Provider -> the environment variable its API key is read from. Mirrors the
# per-provider defaults resolved in the config loader.
_PROVIDER_KEY_ENVS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

# Importable module -> the extra that provides it, for the remedy hint.
_OPTIONAL_DEPS: dict[str, str] = {
    "anthropic": "llm",
    "openai": "openai",
    "coverage": "coverage",
    "pytest": "sandbox",
    "mutmut": "mutation",
}


@dataclass(frozen=True, slots=True)
class Check:
    """A single diagnostic result.

    Attributes:
        name: Human-readable label for the thing checked.
        ok: Whether the check passed.
        detail: Status detail (version found, key source, etc.).
        remedy: How to fix it when ``ok`` is False; empty otherwise.
        fatal: Whether a failure here blocks any run (vs. only some features).
    """

    name: str
    ok: bool
    detail: str
    remedy: str = ""
    fatal: bool = False


def _check_python() -> Check:
    """Verify the interpreter meets the >=3.11 requirement."""
    v = sys.version_info
    version = f"{v.major}.{v.minor}.{v.micro}"
    ok = (v.major, v.minor) >= (3, 11)
    return Check(
        name="Python >= 3.11",
        ok=ok,
        detail=f"found {version}",
        remedy="" if ok else "Install Python 3.11 or newer.",
        fatal=not ok,
    )


def _check_git() -> Check:
    """Verify ``git`` is on PATH (needed to ingest remote repositories)."""
    path = shutil.which("git")
    return Check(
        name="git on PATH",
        ok=path is not None,
        detail=path or "not found",
        remedy=(
            ""
            if path
            else "Install git (only required to run against git URLs; "
            "local paths work without it)."
        ),
    )


def _check_module(module: str, extra: str) -> Check:
    """Report whether an optional dependency ``module`` is importable."""
    found = importlib.util.find_spec(module) is not None
    return Check(
        name=f"{module} installed",
        ok=found,
        detail="available" if found else "not installed",
        remedy="" if found else f"pip install 'mutagen[{extra}]'",
    )


def _check_provider_keys() -> Check:
    """Report which provider API keys are present in the environment.

    Never prints the key value — only the variable name(s) that are set.
    """
    present = [
        f"{provider} ({env})"
        for provider, env in _PROVIDER_KEY_ENVS.items()
        if os.environ.get(env)
    ]
    ok = bool(present)
    return Check(
        name="LLM provider key",
        ok=ok,
        detail=", ".join(present) if present else "none detected",
        remedy=(
            ""
            if ok
            else "Set one of: "
            + ", ".join(_PROVIDER_KEY_ENVS.values())
            + " (e.g. in a .env file or your shell)."
        ),
    )


def run_checks() -> list[Check]:
    """Run every diagnostic and return the results in display order."""
    checks = [_check_python(), _check_git()]
    checks += [_check_module(m, extra) for m, extra in _OPTIONAL_DEPS.items()]
    checks.append(_check_provider_keys())
    return checks


def doctor() -> int:
    """Print a diagnostic report and return a process exit code.

    Returns:
        ``0`` if nothing fatal is wrong, ``1`` if a fatal prerequisite (e.g.
        an unsupported Python version) is missing. Optional-dependency and
        provider-key warnings do not, by themselves, make this fail.
    """
    checks = run_checks()
    print("Mutagen environment check\n")
    for check in checks:
        mark = "OK " if check.ok else ("ERR" if check.fatal else "-- ")
        print(f"  [{mark}] {check.name}: {check.detail}")
        if not check.ok and check.remedy:
            print(f"          -> {check.remedy}")

    fatal = [c for c in checks if c.fatal and not c.ok]
    warnings = [c for c in checks if not c.fatal and not c.ok]
    print()
    if fatal:
        print("Found blocking problems above; mutagen cannot run until fixed.")
        return 1
    if warnings:
        print(
            "Core looks good. Some optional features need the extras noted "
            "above; install them as needed."
        )
    else:
        print("All checks passed. You're ready to run `mutagen run .`.")
    return 0
