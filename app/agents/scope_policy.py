"""Shared path-scope policy.

The deterministic validator and the CLI adapter must reach the *same* verdict
about whether an executor stayed inside its allowed paths, so the logic lives
here once. It previously existed twice (``validator._evaluate_scope_status``
and ``cli_adapter._evaluate_scope_from_files``), which is exactly how two
copies of a rule drift apart.

Scope enforcement is opt-in and staged:

- A task that declares no ``allowed_paths`` keeps the historical behaviour:
  the workspace root is the boundary (``WITHIN_SCOPE`` for anything inside it).
- A task that *does* declare paths gets those paths enforced, plus the shared
  cross-cutting files below.
- Enforcement itself is gated by ``PROJECTFORGE_SCOPE_MODE`` (default ``warn``):
  ``warn`` records a violation without failing the task, ``enforce`` fails it.
  Shipping straight to ``enforce`` risks false positives killing healthy tasks,
  which would destroy trust in the constraint plane faster than having none.
"""

from __future__ import annotations

import os
from pathlib import Path

WITHIN_SCOPE = "WITHIN_SCOPE"
NEEDS_REVIEW = "NEEDS_REVIEW"
SCOPE_VIOLATION = "SCOPE_VIOLATION"

SCOPE_MODE_ENV = "PROJECTFORGE_SCOPE_MODE"
SCOPE_MODE_WARN = "warn"
SCOPE_MODE_ENFORCE = "enforce"
DEFAULT_SCOPE_MODE = SCOPE_MODE_WARN

# Cross-cutting files any task may legitimately touch (dependency manifests,
# build config, docs). Omitting one turns a healthy task into a false
# violation, so this list is deliberately generous.
SHARED_PATHS: tuple[str, ...] = (
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "package-lock.json",
    "pom.xml",
    "build.gradle",
    "README.md",
    "CHANGELOG.md",
    ".gitignore",
    "Makefile",
    "Dockerfile",
)

# Package markers appear at arbitrary depths, so they cannot be expressed as a
# fixed path prefix and are matched by basename instead.
SHARED_BASENAMES: tuple[str, ...] = ("__init__.py",)


def resolve_scope_mode(explicit: str | None = None) -> str:
    """Resolve the scope enforcement mode: explicit > env > default (warn).

    Unknown values fall back to ``warn`` — the safe direction is to observe
    rather than to fail a task on a typo.
    """
    candidate = (explicit or "").strip().lower()
    if candidate in {SCOPE_MODE_WARN, SCOPE_MODE_ENFORCE}:
        return candidate
    raw = os.environ.get(SCOPE_MODE_ENV, "").strip().lower()
    if raw in {SCOPE_MODE_WARN, SCOPE_MODE_ENFORCE}:
        return raw
    return DEFAULT_SCOPE_MODE


def path_allowed(changed_path: str, allowed_path: str) -> bool:
    """True when ``changed_path`` is the allowed path or sits beneath it."""
    # Normalize separators so resolved Windows paths compare correctly.
    changed = changed_path.replace("\\", "/")
    allowed = allowed_path.replace("\\", "/")
    if changed == allowed or changed.startswith(allowed.rstrip("/") + "/"):
        return True
    return Path(changed).name in SHARED_BASENAMES


def normalize_declared_paths(declared: list[str] | None, workspace: Path | None) -> list[str]:
    """Resolve a task's declared allowed paths against the workspace.

    Entries that are absolute or contain ``..`` are dropped: a declaration we
    cannot trust must never become an enforcement decision. Returns an empty
    list when nothing usable remains, which the caller must treat as
    "unverifiable" rather than "violated".
    """
    if not declared:
        return []
    base = workspace.resolve() if workspace is not None else None
    resolved: list[str] = []
    for raw in declared:
        entry = str(raw).strip()
        if not entry:
            continue
        candidate = Path(entry)
        # `is_absolute()` alone is not enough on Windows: "/abs/path" has no
        # drive letter, so it reports False while still being rooted, and
        # `base / "/abs/path"` resolves to C:\abs\path — outside the workspace.
        # `anchor` catches rooted-without-drive, drive-relative ("C:foo") and
        # POSIX absolute paths alike.
        if candidate.is_absolute() or candidate.anchor or ".." in candidate.parts:
            continue
        if base is not None:
            resolved.append(str((base / candidate).resolve()))
        else:
            resolved.append(entry.replace("\\", "/").rstrip("/"))
    return resolved


def shared_paths_for(workspace: Path | None) -> list[str]:
    """Absolute (when a workspace is known) paths of the shared files."""
    if workspace is None:
        return [item.replace("\\", "/") for item in SHARED_PATHS]
    base = workspace.resolve()
    return [str((base / item).resolve()) for item in SHARED_PATHS]


def evaluate_scope(
    changed_files: list[str],
    allowed_paths: list[str],
    workspace: Path | None = None,
) -> str:
    """Verdict for the reported changes against the allowed paths.

    An empty ``allowed_paths`` means "nothing was declared": that is
    unverifiable, not a violation, so it yields NEEDS_REVIEW.
    """
    if not allowed_paths:
        return NEEDS_REVIEW
    base = workspace.resolve() if workspace is not None else None
    for changed in changed_files:
        candidates = [changed]
        if base is not None:
            # Reporters give workspace-relative paths while contracts carry
            # absolute allowed_paths; compare both forms.
            candidates.append(str((base / changed).resolve()))
        if not any(path_allowed(candidate, allowed) for candidate in candidates for allowed in allowed_paths):
            return SCOPE_VIOLATION
    return WITHIN_SCOPE
