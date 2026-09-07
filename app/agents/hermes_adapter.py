from __future__ import annotations

import subprocess
from pathlib import Path

from app.agents.cli_adapter import CliAgentAdapter
from app.agents.sandbox_policy import BwrapSandboxPolicy


class HermesAdapter(CliAgentAdapter):
    def __init__(
        self,
        workspace: Path | None = None,
        timeout_seconds: int = 900,
        sandbox_policy: BwrapSandboxPolicy | None = None,
    ) -> None:
        super().__init__(
            workspace=workspace,
            timeout_seconds=timeout_seconds,
            sandbox_policy=sandbox_policy
            or BwrapSandboxPolicy(
                cli_home=Path.home() / ".local",
                config_home=Path.home() / ".hermes",
            ),
        )
        self.hermes_cli = self.agent_binary

    def agent_name(self) -> str:
        return "hermes"

    def find_binary(self) -> str:
        for name in ["hermes", "hermes-agent", "hermes_cli"]:
            try:
                proc = subprocess.run(
                    [name, "--version"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=10,
                )
                if proc.returncode == 0:
                    return name
            except FileNotFoundError:
                continue
        raise RuntimeError("Hermes CLI not found in PATH")

    def build_argv(self, prompt: str) -> list[str]:
        return [
            self.agent_binary,
            "-z",
            prompt,
            "--in",
            "/workspace",
            "--safe-mode",
            "--accept-hooks",
            "--ignore-user-config",
            "--ignore-rules",
        ]
