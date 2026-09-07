from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol


class SandboxUnavailableError(RuntimeError):
    pass


class SandboxPolicy(Protocol):
    def is_available(self) -> bool: ...

    def wrap(self, workspace: Path, command: list[str]) -> list[str]: ...


class NullSandboxPolicy:
    def is_available(self) -> bool:
        return True

    def wrap(self, workspace: Path, command: list[str]) -> list[str]:
        return list(command)


class BwrapSandboxPolicy:
    """bubblewrap mount/pid/ipc isolation that keeps the host network
    namespace (the agent must reach its LLM API). Verified against live
    Hermes runs; on Ubuntu >= 24.04 bwrap additionally needs an AppArmor
    profile permitting unprivileged user namespaces."""

    def __init__(self, cli_home: Path | None = None, config_home: Path | None = None) -> None:
        self._cli_home = cli_home
        self._config_home = config_home

    def is_available(self) -> bool:
        return shutil.which("bwrap") is not None

    def wrap(self, workspace: Path, command: list[str]) -> list[str]:
        if not self.is_available():
            raise SandboxUnavailableError(
                "bubblewrap (bwrap) is not available on this platform. "
                "Workspace-isolated execution requires Linux with bwrap installed."
            )
        workspace = workspace.resolve()
        sandbox_cmd = [
            "bwrap",
            "--unshare-ipc",
            "--unshare-pid",
            "--new-session",
            "--setenv", "HOME", "/workspace",
            "--bind", str(workspace), "/workspace",
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64",
            "--ro-bind", "/sbin", "/sbin",
            "--proc", "/proc",
            "--dev", "/dev",
            "--chdir", "/workspace",
        ]
        for etc_file in ("/etc/resolv.conf", "/etc/hosts"):
            if Path(etc_file).exists():
                sandbox_cmd.extend(["--ro-bind", etc_file, etc_file])
        if self._cli_home is not None and self._cli_home.exists():
            sandbox_cmd.extend(["--ro-bind", str(self._cli_home), str(self._cli_home)])
        if self._config_home is not None and self._config_home.exists():
            sandbox_cmd.extend(["--ro-bind", str(self._config_home), str(self._config_home)])
            # Agents resolve their config/auth relative to HOME, so expose
            # the real config home inside the sandbox at /workspace/.hermes.
            sandbox_cmd.extend(["--bind", str(self._config_home), "/workspace/.hermes"])
        sandbox_cmd.extend(command)
        return sandbox_cmd
