"""Windows autostart via a named shortcut to the product launcher."""

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
STARTUP_ENTRY_NAME = "哔哩哔哩 Transcriber.lnk"
STARTUP_LAUNCHER_NAME = "哔哩哔哩 Transcriber.exe"
STARTUP_ICON_NAME = "favicon.ico"
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


def _startup_launcher() -> Path:
    return _project_root() / STARTUP_LAUNCHER_NAME


def _startup_icon() -> Path:
    return _project_root() / STARTUP_ICON_NAME


def _startup_folder() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _startup_entry_path() -> Path:
    return _startup_folder() / STARTUP_ENTRY_NAME


def _startup_entry_is_current() -> bool:
    path = _startup_entry_path()
    if not path.is_file():
        return False
    shortcut = _read_shortcut(path)
    if shortcut is None:
        return False
    target, icon = shortcut
    return target == str(_startup_launcher()) and icon == f"{_startup_icon()},0"


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
    shortcut = _read_shortcut(path)
    return shortcut[0] if shortcut else None


def _read_shortcut(path: Path) -> tuple[str, str] | None:
    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('"
        + str(path).replace("'", "''")
        + "'); Write-Output $s.TargetPath; Write-Output $s.IconLocation"
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
    fields = (result.stdout or "").splitlines()
    if not fields or not fields[0].strip():
        return None
    return fields[0].strip(), fields[1].strip() if len(fields) > 1 else ""


def _create_startup_entry() -> None:
    launcher = _startup_launcher()
    icon = _startup_icon()
    if not launcher.is_file():
        raise RuntimeError(f"找不到开机启动器: {launcher}")
    if not icon.is_file():
        raise RuntimeError(f"找不到开机启动图标: {icon}")
    _startup_folder().mkdir(parents=True, exist_ok=True)
    shortcut = _startup_entry_path()
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{str(shortcut).replace("'", "''")}'); "
        f"$s.TargetPath = '{str(launcher).replace("'", "''")}'; "
        f"$s.WorkingDirectory = '{str(_project_root()).replace("'", "''")}'; "
        f"$s.IconLocation = '{str(icon).replace("'", "''")},0'; "
        "$s.Description = 'Bilibili Transcriber - login startup'; "
        "$s.Save()"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0 or not _startup_entry_is_current():
        raise RuntimeError((result.stderr or result.stdout or "创建开机启动快捷方式失败").strip())


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
        "enabled": _startup_entry_path().is_file(),
        "method": "startup_folder" if _startup_entry_path().is_file() else None,
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
