from __future__ import annotations

from pathlib import Path

from radcast.worker_setup import (
    build_worker_command_args,
    default_worker_path,
    linux_service_unit_text,
    macos_launch_agent_payload,
    windows_task_command,
)


def test_build_worker_command_args_contains_required_flags():
    args = build_worker_command_args(
        python_exe=Path("/usr/bin/python3"),
        server_url="https://worker.example.com",
        config_path=Path("/home/user/.radcast/worker.json"),
        poll_seconds=5,
    )
    assert args[1:3] == ["-m", "radcast.worker_client"]
    assert "https://worker.example.com" in args
    assert "/home/user/.radcast/worker.json" in args


def test_default_worker_path_includes_homebrew_and_system_paths():
    value = default_worker_path()
    assert "/opt/homebrew/bin" in value
    assert "/usr/bin" in value


def test_linux_service_unit_references_worker_module():
    text = linux_service_unit_text(
        python_exe=Path("/usr/bin/python3"),
        server_url="https://worker.example.com",
        config_path=Path("/home/user/.radcast/worker.json"),
        poll_seconds=5,
    )
    assert "radcast.worker_client" in text
    assert "https://worker.example.com" in text


def test_windows_task_command_references_worker_module_and_flags():
    command = windows_task_command(
        python_exe=Path(r"C:\Python\python.exe"),
        server_url="https://worker.example.com",
        config_path=Path(r"C:\Users\demo\.radcast\worker.json"),
        poll_seconds=5,
    )
    assert "radcast.worker_client" in command
    assert "worker.json" in command


def test_macos_launch_agent_payload_sets_program_arguments(tmp_path: Path):
    payload = macos_launch_agent_payload(
        label="com.radcast.worker",
        python_exe=Path("/usr/bin/python3"),
        server_url="https://worker.example.com",
        config_path=tmp_path / ".radcast" / "worker.json",
        poll_seconds=5,
    )
    assert payload["Label"] == "com.radcast.worker"
    assert "ProgramArguments" in payload
    assert "PATH" in payload["EnvironmentVariables"]
