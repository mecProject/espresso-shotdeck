"""Command execution and service control wrappers."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Protocol, Sequence

from .errors import HealthCheckError, InstallError


@dataclass(slots=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    def run(
        self,
        command: Sequence[str],
        *,
        timeout: int | None = None,
        check: bool = True,
    ) -> CommandResult:
        completed = subprocess.run(
            list(command),
            timeout=timeout,
            check=False,
            capture_output=True,
            text=True,
        )
        result = CommandResult(
            command=tuple(command),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if check and completed.returncode != 0:
            raise InstallError(
                f"Command {' '.join(command)!r} failed with exit {completed.returncode}: {completed.stderr.strip()}"
            )
        return result


class ServiceController(Protocol):
    def stop(self) -> None:
        ...

    def start(self) -> None:
        ...

    def health_check(self, timeout_seconds: int) -> None:
        ...


class SystemctlServiceController:
    def __init__(self, service_name: str, runner: CommandRunner | None = None) -> None:
        self.service_name = service_name
        self.runner = runner or CommandRunner()

    def stop(self) -> None:
        self.runner.run(("systemctl", "stop", self.service_name), check=False)

    def start(self) -> None:
        self.runner.run(("systemctl", "start", self.service_name))

    def health_check(self, timeout_seconds: int) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            result = self.runner.run(
                ("systemctl", "is-active", self.service_name),
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip() == "active":
                return
            time.sleep(1)
        raise HealthCheckError(f"Service {self.service_name} did not become healthy within {timeout_seconds}s")


def run_hooks(
    runner: CommandRunner,
    commands: list[list[str]],
    *,
    timeout_seconds: int | None = None,
) -> None:
    for command in commands:
        runner.run(command, timeout=timeout_seconds)
