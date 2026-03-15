from __future__ import annotations

from pathlib import Path

import radcast.worker_setup as worker_setup
from radcast.worker_setup import (
    build_worker_command_args,
    current_python_executable,
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
    assert payload["WorkingDirectory"] == str((tmp_path / ".radcast").resolve())
    assert payload["ProcessType"] == "Background"
    assert payload["KeepAlive"] == {"SuccessfulExit": False, "Crashed": True}


def test_current_python_executable_preserves_venv_launcher(monkeypatch):
    monkeypatch.setattr(worker_setup.sys, "executable", "/tmp/demo-venv/bin/python")
    assert current_python_executable() == Path("/tmp/demo-venv/bin/python")


def test_run_setup_uses_unresolved_current_python(monkeypatch, tmp_path: Path):
    recorded: dict[str, Path] = {}

    monkeypatch.setattr(worker_setup.sys, "executable", "/tmp/demo-venv/bin/python")
    monkeypatch.setattr(worker_setup, "_register_worker_if_needed", lambda **_: "registered")

    def fake_install_macos_autostart(**kwargs):
        recorded["python_exe"] = kwargs["python_exe"]
        return "installed"

    monkeypatch.setattr(worker_setup, "_install_macos_autostart", fake_install_macos_autostart)
    messages = worker_setup.run_setup(
        server_url="https://worker.example.com",
        invite_token="token",
        worker_name="demo-worker",
        config_path=tmp_path / "worker.json",
        platform_name="macos",
        poll_seconds=5,
    )

    assert messages == ["registered", "installed"]
    assert recorded["python_exe"] == Path("/tmp/demo-venv/bin/python")
