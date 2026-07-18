"""Windows autostart via the current user's Startup folder.

Task Manager shows the startup entry's executable/script name, not a .lnk
display name. We therefore place a product-named .bat directly in Startup;
it silently delegates to launch_silent.vbs in the project directory.
"""

from __future__ import annotations

import logging
import os
import subprocess
import winreg
from pathlib import Path

import config

logger = logging.getLogger("server.autostart")

TASK_NAME = "BilibiliTranscriber"
REGISTRY_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
SILENT_LAUNCHER_NAME = "launch_silent.vbs"
STARTUP_ENTRY_NAME = "哔哩哔哩 Transcriber.bat"
REGISTRY_ACCESS = winreg.KEY_READ | winreg.KEY_SET_VALUE
LEGACY_REGISTRY_NAMES = frozenset(
    {
        "BilibiliTranscriber",
        "BilibiliTranscriberTest",
    }
)


def _project_root() -> Path:
    return config.PROJECT_ROOT.resolve()


def _silent_launcher_vbs() -> Path:
    return _project_root() / SILENT_LAUNCHER_NAME


def _startup_folder() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _startup_entry_path() -> Path:
    return _startup_folder() / STARTUP_ENTRY_NAME


def _startup_entry_exists() -> bool:
    return _startup_entry_path().is_file()


def _build_launch_command() -> str:
    """Absolute wscript command used inside the Startup .bat."""
    vbs = _silent_launcher_vbs()
    return f'wscript.exe //B "{vbs}"'


def _expected_startup_bat_content() -> str:
    return f"@echo off\r\n{_build_launch_command()}\r\n"


def _startup_entry_is_current() -> bool:
    path = _startup_entry_path()
    if not path.is_file():
        return False
    try:
        return path.read_text(encoding="utf-8") == _expected_startup_bat_content()
    except OSError:
        return False


def _run_schtasks(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["schtasks", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _delete_task_scheduler_entry() -> bool:
    query = _run_schtasks(["/Query", "/TN", TASK_NAME, "/FO", "LIST"])
    if query.returncode != 0:
        return False
    result = _run_schtasks(["/Delete", "/TN", TASK_NAME, "/F"])
    if result.returncode != 0:
        logger.warning("删除遗留计划任务自启项失败: %s", (result.stderr or result.stdout).strip())
        return False
    logger.info("已移除遗留计划任务自启项: %s", TASK_NAME)
    return True


def _cleanup_legacy_registry_entries() -> list[str]:
    root = str(_project_root()).lower()
    removed: list[str] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_RUN_PATH, 0, REGISTRY_ACCESS) as key:
            index = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    break

                lowered = str(value).lower()
                should_remove = name in LEGACY_REGISTRY_NAMES or (
                    root in lowered
                    and (
                        "launch_silent.vbs" in lowered
                        or "cmd /c" in lowered
                        or "python.exe" in lowered
                        or "start.bat" in lowered
                    )
                )
                if should_remove:
                    winreg.DeleteValue(key, name)
                    removed.append(name)
                    logger.info("已移除遗留注册表自启项: %s", name)
                    continue
                index += 1
    except FileNotFoundError:
        pass
    except OSError:
        logger.exception("清理遗留注册表自启项失败")
    return removed


def _read_lnk_target(path: Path) -> str | None:
    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('"
        + str(path).replace("'", "''")
        + "'); Write-Output $s.TargetPath"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return None
    target = (result.stdout or "").strip()
    return target or None


def _create_startup_entry() -> None:
    vbs = _silent_launcher_vbs()
    if not vbs.is_file():
        raise RuntimeError(f"找不到静默启动脚本: {vbs}")

    _startup_folder().mkdir(parents=True, exist_ok=True)
    _startup_entry_path().write_text(_expected_startup_bat_content(), encoding="utf-8")


def _cleanup_old_startup_entries() -> list[str]:
    removed: list[str] = []
    folder = _startup_folder()
    if not folder.is_dir():
        return removed

    root = str(_project_root()).lower()
    current = _startup_entry_path().resolve()

    for path in folder.iterdir():
        if path.resolve() == current:
            continue

        if path.suffix.lower() == ".lnk":
            target = _read_lnk_target(path)
            if target and root in target.lower():
                try:
                    path.unlink()
                    removed.append(path.name)
                    logger.info("已移除遗留启动文件夹快捷方式: %s", path)
                except OSError:
                    logger.exception("删除遗留启动文件夹快捷方式失败: %s", path)
            continue

        if path.suffix.lower() != ".bat":
            continue

        name = path.name.lower()
        if path.name == STARTUP_ENTRY_NAME:
            continue
        if "bilibili" not in name and "transcriber" not in name and "转文稿" not in path.name:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        if root in text or "launch_silent.vbs" in text or "start.bat" in text:
            try:
                path.unlink()
                removed.append(path.name)
                logger.info("已移除遗留启动文件夹脚本: %s", path)
            except OSError:
                logger.exception("删除遗留启动文件夹脚本失败: %s", path)
    return removed


def cleanup_legacy_autostart_entries() -> list[str]:
    removed: list[str] = []
    if _delete_task_scheduler_entry():
        removed.append(f"task:{TASK_NAME}")
    removed.extend(f"registry:{name}" for name in _cleanup_legacy_registry_entries())
    removed.extend(f"startup:{name}" for name in _cleanup_old_startup_entries())
    return removed


def ensure_autostart() -> dict:
    """Keep the app registered as a readable Startup-folder entry."""
    cleanup_legacy_autostart_entries()
    if not _startup_entry_is_current():
        _create_startup_entry()
    status = get_autostart_status()
    if not status["enabled"]:
        raise RuntimeError("自启注册后状态异常")
    return status


def get_autostart_status() -> dict:
    return {
        "enabled": _startup_entry_exists(),
        "method": "startup_folder" if _startup_entry_exists() else None,
        "entry": str(_startup_entry_path()),
        "name": STARTUP_ENTRY_NAME,
    }


def refresh_autostart_if_needed() -> None:
    """Compatibility wrapper used by older callers."""
    try:
        ensure_autostart()
    except Exception:
        logger.exception("校准开机自启失败")


def enable_autostart() -> dict:
    """Compatibility wrapper; autostart is now always the Startup entry."""
    return ensure_autostart()


def disable_autostart() -> dict:
    """Compatibility wrapper retained for scripts/tests, not exposed in the UI."""
    cleanup_legacy_autostart_entries()
    path = _startup_entry_path()
    if path.is_file():
        path.unlink()
    return get_autostart_status()
