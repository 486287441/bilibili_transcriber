"""One-off probe: which autostart registration methods work on this machine."""
from __future__ import annotations

import json
import subprocess
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VBS = ROOT / "launch_silent.vbs"
COMMAND = f'wscript.exe //B "{VBS}"'
TASK = "BilibiliTranscriberTest"
REG_NAME = "BilibiliTranscriberTest"
REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def test_schtasks() -> dict:
    create = subprocess.run(
        ["schtasks", "/Create", "/TN", TASK, "/TR", COMMAND, "/SC", "ONLOGON", "/RL", "LIMITED", "/F"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if create.returncode != 0:
        return {
            "ok": False,
            "stage": "create",
            "code": create.returncode,
            "stderr": (create.stderr or create.stdout or "").strip(),
        }
    query = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK, "/FO", "LIST"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    delete = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK, "/F"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "ok": query.returncode == 0 and delete.returncode == 0,
        "stage": "done",
        "query_code": query.returncode,
        "delete_code": delete.returncode,
    }


def test_registry() -> dict:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE | winreg.KEY_READ
        ) as key:
            winreg.SetValueEx(key, REG_NAME, 0, winreg.REG_SZ, COMMAND)
            read, _ = winreg.QueryValueEx(key, REG_NAME)
            winreg.DeleteValue(key, REG_NAME)
        return {"ok": True, "read_back": read}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def test_startup_folder() -> dict:
    import os

    startup = (
        Path(os.environ["APPDATA"])
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )
    shortcut = startup / "BilibiliTranscriberTest.lnk"
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{shortcut}'); "
        f"$s.TargetPath = '{VBS}'; "
        f"$s.WorkingDirectory = '{ROOT}'; "
        "$s.WindowStyle = 7; "
        "$s.Save()"
    )
    create = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if create.returncode != 0 or not shortcut.is_file():
        return {
            "ok": False,
            "code": create.returncode,
            "stderr": (create.stderr or create.stdout or "").strip(),
        }
    shortcut.unlink()
    return {"ok": True}


def main() -> None:
    print(
        json.dumps(
            {
                "task_scheduler": test_schtasks(),
                "registry_hkcu_run": test_registry(),
                "startup_folder": test_startup_folder(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
