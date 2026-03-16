"""Cross-platform helper to register and auto-start a RADcast worker."""

from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import shlex
import socket
import subprocess
import sys
from pathlib import Path

import requests


def default_worker_path(extra_paths: list[str] | None = None) -> str:
    preferred = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    existing = [segment for segment in os.environ.get("PATH", "").split(":") if segment]
    merged: list[str] = []
    for segment in (extra_paths or []) + preferred + existing:
        if segment not in merged:
            merged.append(segment)
    return ":".join(merged)


def normalize_platform(value: str) -> str:
    raw = value.strip().lower()
    if raw == "auto":
        name = platform.system().lower()
        if "windows" in name:
            return "windows"
        if "darwin" in name or "mac" in name:
            return "macos"
        return "linux"
    if raw in {"windows", "linux", "macos"}:
        return raw
    raise ValueError(f"Unsupported platform: {value}")


def build_worker_command_args(*, python_exe: Path, server_url: str, config_path: Path, poll_seconds: int) -> list[str]:
    return [
        str(python_exe),
        "-m",
        "radcast.worker_client",
        "--server-url",
        server_url.rstrip("/"),
        "--config-path",
        str(config_path),
        "--poll-seconds",
        str(max(1, int(poll_seconds))),
    ]


def linux_service_unit_text(*, python_exe: Path, server_url: str, config_path: Path, poll_seconds: int) -> str:
    command = shlex.join(
        build_worker_command_args(
            python_exe=python_exe,
            server_url=server_url,
            config_path=config_path,
            poll_seconds=poll_seconds,
        )
    )
    return (
        "[Unit]\n"
        "Description=RADcast Worker (user)\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"Environment=PATH={default_worker_path([str(python_exe.parent)])}\n"
        f"ExecStart={command}\n"
        "Restart=always\n"
        "RestartSec=5\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def macos_launch_agent_payload(*, label: str, python_exe: Path, server_url: str, config_path: Path, poll_seconds: int) -> dict[str, object]:
    logs_dir = config_path.parent
    logs_dir.mkdir(parents=True, exist_ok=True)
    environment = {"PATH": default_worker_path([str(python_exe.parent)])}
    environment.setdefault("RADCAST_ENHANCE_DEVICE", "cpu")
    return {
        "Label": label,
        "ProgramArguments": build_worker_command_args(
            python_exe=python_exe,
            server_url=server_url,
            config_path=config_path,
            poll_seconds=poll_seconds,
        ),
        "EnvironmentVariables": environment,
        "WorkingDirectory": str(logs_dir),
        "ProcessType": "Background",
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False, "Crashed": True},
        "StandardOutPath": str(logs_dir / "worker.log"),
        "StandardErrorPath": str(logs_dir / "worker.err.log"),
    }


def windows_task_command(*, python_exe: Path, server_url: str, config_path: Path, poll_seconds: int) -> str:
    return subprocess.list2cmdline(
        build_worker_command_args(
            python_exe=python_exe,
            server_url=server_url,
            config_path=config_path,
            poll_seconds=poll_seconds,
        )
    )


def current_python_executable() -> Path:
    # Preserve the venv launcher path instead of resolving the symlink target.
    return Path(sys.executable)


def _run_command(cmd: list[str], *, required: bool) -> bool:
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        if required:
            raise RuntimeError(f"Command not found: {cmd[0]}") from None
        return False
    if result.returncode != 0:
        if required:
            message = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise RuntimeError(f"Command failed ({' '.join(cmd)}): {message}")
        return False
    return True


def _register_worker_if_needed(*, server_url: str, invite_token: str | None, worker_name: str, config_path: Path) -> str:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists() and not invite_token:
        existing = json.loads(config_path.read_text(encoding="utf-8"))
        if existing.get("worker_id") and existing.get("api_key"):
            return "Reused existing worker credentials."
    if not invite_token:
        raise RuntimeError("Worker is not registered yet. Provide --invite-token for first-time setup.")

    response = requests.post(
        f"{server_url.rstrip('/')}/workers/register",
        json={"invite_token": invite_token, "worker_name": worker_name, "capabilities": ["enhance"]},
        timeout=30,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Worker registration failed: {response.status_code} {response.text[:400]}")
    payload = response.json()
    worker_id = payload.get("worker_id")
    api_key = payload.get("api_key")
    if not worker_id or not api_key:
        raise RuntimeError("Worker registration response missing worker_id/api_key")
    config_path.write_text(
        json.dumps(
            {
                "server_url": server_url.rstrip("/"),
                "worker_id": worker_id,
                "api_key": api_key,
                "worker_name": worker_name,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return "Registered a new worker and saved credentials."


def _install_linux_autostart(*, python_exe: Path, server_url: str, config_path: Path, poll_seconds: int) -> str:
    service_path = Path.home() / ".config" / "systemd" / "user" / "radcast-worker.service"
    service_path.parent.mkdir(parents=True, exist_ok=True)
    service_path.write_text(
        linux_service_unit_text(
            python_exe=python_exe,
            server_url=server_url,
            config_path=config_path,
            poll_seconds=poll_seconds,
        ),
        encoding="utf-8",
    )
    _run_command(["systemctl", "--user", "daemon-reload"], required=False)
    _run_command(["systemctl", "--user", "enable", "--now", "radcast-worker.service"], required=False)
    return f"Installed user service: {service_path}"


def _install_macos_autostart(*, python_exe: Path, server_url: str, config_path: Path, poll_seconds: int) -> str:
    label = "com.radcast.worker"
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    with plist_path.open("wb") as handle:
        plistlib.dump(
            macos_launch_agent_payload(
                label=label,
                python_exe=python_exe,
                server_url=server_url,
                config_path=config_path,
                poll_seconds=poll_seconds,
            ),
            handle,
            sort_keys=True,
        )
    uid = str(os.getuid())
    _run_command(["launchctl", "bootout", f"gui/{uid}", str(plist_path)], required=False)
    _run_command(["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)], required=False)
    _run_command(["launchctl", "enable", f"gui/{uid}/{label}"], required=False)
    _run_command(["launchctl", "kickstart", "-k", f"gui/{uid}/{label}"], required=False)
    return f"Installed LaunchAgent: {plist_path}"


def _install_windows_autostart(*, python_exe: Path, server_url: str, config_path: Path, poll_seconds: int) -> str:
    task_name = "RADcast Worker"
    command = windows_task_command(
        python_exe=python_exe,
        server_url=server_url,
        config_path=config_path,
        poll_seconds=poll_seconds,
    )
    _run_command(
        ["schtasks", "/Create", "/SC", "ONLOGON", "/RL", "LIMITED", "/TN", task_name, "/TR", command, "/F"],
        required=False,
    )
    return f"Registered Scheduled Task: {task_name}"


def run_setup(*, server_url: str, invite_token: str | None, worker_name: str, config_path: Path, platform_name: str, poll_seconds: int) -> list[str]:
    normalized_platform = normalize_platform(platform_name)
    python_exe = current_python_executable()
    messages = [
        _register_worker_if_needed(
            server_url=server_url,
            invite_token=invite_token,
            worker_name=worker_name,
            config_path=config_path,
        )
    ]
    if normalized_platform == "linux":
        messages.append(
            _install_linux_autostart(
                python_exe=python_exe,
                server_url=server_url,
                config_path=config_path,
                poll_seconds=poll_seconds,
            )
        )
    elif normalized_platform == "macos":
        messages.append(
            _install_macos_autostart(
                python_exe=python_exe,
                server_url=server_url,
                config_path=config_path,
                poll_seconds=poll_seconds,
            )
        )
    else:
        messages.append(
            _install_windows_autostart(
                python_exe=python_exe,
                server_url=server_url,
                config_path=config_path,
                poll_seconds=poll_seconds,
            )
        )
    return messages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install and register a RADcast worker")
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--invite-token")
    parser.add_argument("--worker-name", default=socket.gethostname())
    parser.add_argument("--platform", default="auto")
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--config-path", default=str(Path.home() / ".radcast" / "worker.json"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    messages = run_setup(
        server_url=args.server_url,
        invite_token=args.invite_token,
        worker_name=args.worker_name,
        config_path=Path(args.config_path),
        platform_name=args.platform,
        poll_seconds=max(1, args.poll_seconds),
    )
    for message in messages:
        print(message)


if __name__ == "__main__":
    main()
