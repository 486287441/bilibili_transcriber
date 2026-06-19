"""Windows autostart: Task Scheduler (preferred), Startup-folder shortcut, Registry Run fallback.

Startup-folder shortcuts show a readable name in Task Manager (e.g. 视频转文稿助手).
Registry Run entries often appear only as wscript.exe / Windows Script Host, which
is easy to disable by mistake.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import winreg
from pathlib import Path

import config
from server.settings_store import load_settings, update_settings

logger = logging.getLogger("server.autostart")

TASK_NAME = "BilibiliTranscriber"
REGISTRY_VALUE_NAME = "BilibiliTranscriber"
REGISTRY_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
SILENT_LAUNCHER_NAME = "launch_silent.vbs"
AUTOSTART_BAT_NAME = "start-autostart.bat"
STARTUP_SHORTCUT_NAME = "视频转文稿助手.lnk"
REGISTRY_ACCESS = winreg.KEY_READ | winreg.KEY_SET_VALUE
LEGACY_REGISTRY_NAMES = frozenset(
    {
        "BilibiliTranscriberTest",
    }
)


def _python_exe() -> Path:
    return Path(sys.executable).resolve()


def _project_root() -> Path:
    return config.PROJECT_ROOT.resolve()


def _autostart_bat() -> Path:
    return _project_root() / AUTOSTART_BAT_NAME


def _silent_launcher_vbs() -> Path:
    return _project_root() / SILENT_LAUNCHER_NAME


def _startup_folder() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _startup_shortcut_path() -> Path:
    return _startup_folder() / STARTUP_SHORTCUT_NAME


def _startup_shortcut_exists() -> bool:
    return _startup_shortcut_path().is_file()


def _create_startup_shortcut() -> None:
    vbs = _silent_launcher_vbs()
    if not vbs.is_file():
        raise RuntimeError(f"找不到静默启动脚本: {vbs}")
    shortcut = _startup_shortcut_path()
    root = _project_root()
    wscript = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wscript.exe"
    _startup_folder().mkdir(parents=True, exist_ok=True)
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{shortcut}'); "
        f"$s.TargetPath = '{wscript}'; "
        f"$s.Arguments = '//B \"{vbs}\"'; "
        f"$s.WorkingDirectory = '{root}'; "
        "$s.WindowStyle = 7; "
        "$s.Description = '视频转文稿助手 — 登录后后台启动'; "
        "$s.Save()"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0 or not shortcut.is_file():
        err = (result.stderr or result.stdout or "创建启动快捷方式失败").strip()
        raise RuntimeError(err)


def _delete_startup_shortcut() -> None:
    path = _startup_shortcut_path()
    if path.is_file():
        path.unlink()


def _build_launch_command() -> str:
    """Absolute paths; wscript //B runs VBS without script UI or console."""
    vbs = _silent_launcher_vbs()
    return f'wscript.exe //B "{vbs}"'


def _uses_legacy_launcher(command: str | None) -> bool:
    if not command:
        return False
    lowered = command.lower()
    if "launch_silent.vbs" in lowered:
        return False
    return "cmd /c" in lowered or "python.exe" in lowered or "-m server" in lowered


def _run_schtasks(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["schtasks", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _is_task_registered() -> bool:
    return _run_schtasks(["/Query", "/TN", TASK_NAME, "/FO", "LIST"]).returncode == 0


def _read_task_command() -> str | None:
    result = _run_schtasks(["/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"])
    if result.returncode != 0:
        return None
    for line in (result.stdout or "").splitlines():
        stripped = line.strip()
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key_lower = key.lower()
        if key_lower in ("task to run", "要运行的任务", "要執行的工作"):
            return value.strip()
    return None


def _read_registry_command() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_RUN_PATH, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, REGISTRY_VALUE_NAME)
            return str(value) if value else None
    except FileNotFoundError:
        return None
    except OSError:
        logger.exception("读取注册表自启项失败")
        return None


def _write_registry_command(command: str) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_RUN_PATH, 0, REGISTRY_ACCESS) as key:
        winreg.SetValueEx(key, REGISTRY_VALUE_NAME, 0, winreg.REG_SZ, command)


def _delete_registry_command() -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_RUN_PATH, 0, REGISTRY_ACCESS) as key:
            winreg.DeleteValue(key, REGISTRY_VALUE_NAME)
    except FileNotFoundError:
        pass


def _cleanup_legacy_registry_entries() -> list[str]:
    """Remove leftover Run-key entries that still launch via cmd/python.exe."""
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

                value_str = str(value)
                lowered = value_str.lower()
                is_legacy_name = name in LEGACY_REGISTRY_NAMES
                is_legacy_cmd = (
                    name != REGISTRY_VALUE_NAME
                    and root in lowered
                    and "launch_silent.vbs" not in lowered
                    and (
                        "cmd /c" in lowered
                        or "python.exe" in lowered
                        or "start.bat" in lowered
                    )
                )
                if is_legacy_name or is_legacy_cmd:
                    winreg.DeleteValue(key, name)
                    removed.append(name)
                    logger.info("已移除遗留开机自启项: %s", name)
                    continue
                index += 1
    except OSError:
        logger.exception("清理遗留注册表自启项失败")
    return removed


def _detect_method() -> str | None:
    if _is_task_registered():
        return "task_scheduler"
    if _startup_shortcut_exists():
        return "startup_folder"
    if _read_registry_command():
        return "registry"
    return None


def get_autostart_status() -> dict:
    method = _detect_method()
    settings = load_settings()
    enabled = method is not None and settings.autostart_enabled
    return {
        "enabled": enabled,
        "method": method,
        "settings_flag": settings.autostart_enabled,
    }


def refresh_autostart_if_needed() -> None:
    """Re-register when settings say enabled but launch command is the old cmd window."""
    settings = load_settings()
    if not settings.autostart_enabled:
        return
    if not _silent_launcher_vbs().is_file():
        logger.warning("静默启动脚本不存在: %s", _silent_launcher_vbs())
        return

    removed = _cleanup_legacy_registry_entries()
    if removed:
        logger.info("清理遗留自启项: %s", ", ".join(removed))

    method = _detect_method()
    if method is None:
        logger.info("设置已开启自启但系统项缺失，正在重新注册")
        try:
            enable_autostart()
        except Exception:
            logger.exception("重新注册自启失败")
        return

    expected = _build_launch_command()
    current: str | None = None
    if method == "task_scheduler":
        current = _read_task_command()
    elif method == "registry":
        current = _read_registry_command()
    elif method == "startup_folder":
        current = _build_launch_command()
    else:
        current = None

    if current is None:
        return
    if current.strip() == expected.strip():
        return
    if not _uses_legacy_launcher(current):
        return

    logger.info("迁移开机自启为静默启动（无终端窗口）")
    try:
        enable_autostart()
    except Exception:
        logger.exception("迁移静默自启失败")


def enable_autostart() -> dict:
    vbs = _silent_launcher_vbs()
    if not vbs.is_file():
        raise RuntimeError(f"找不到静默启动脚本: {vbs}")

    _cleanup_legacy_registry_entries()
    command = _build_launch_command()
    logger.info("注册开机自启: %s", vbs)

    task_result = _run_schtasks(
        [
            "/Create",
            "/TN",
            TASK_NAME,
            "/TR",
            command,
            "/SC",
            "ONLOGON",
            "/RL",
            "LIMITED",
            "/F",
        ]
    )
    if task_result.returncode == 0:
        _delete_registry_command()
        _delete_startup_shortcut()
        update_settings({"autostart_enabled": True})
        return get_autostart_status()

    task_err = (task_result.stderr or task_result.stdout or "").strip()
    logger.warning("计划任务注册失败，尝试「启动」文件夹快捷方式: %s", task_err)

    try:
        _create_startup_shortcut()
        _delete_registry_command()
    except RuntimeError as exc:
        logger.warning("启动文件夹注册失败，尝试注册表 Run 键: %s", exc)
        try:
            _write_registry_command(command)
            _delete_startup_shortcut()
        except OSError as reg_exc:
            raise RuntimeError(
                f"自启注册失败（计划任务、启动文件夹、注册表均不可用）: {exc}; {reg_exc}"
            ) from reg_exc

    if _is_task_registered():
        _run_schtasks(["/Delete", "/TN", TASK_NAME, "/F"])

    update_settings({"autostart_enabled": True})
    status = get_autostart_status()
    if status["method"] is None:
        raise RuntimeError("自启注册后状态异常")
    return status


def disable_autostart() -> dict:
    if _is_task_registered():
        result = _run_schtasks(["/Delete", "/TN", TASK_NAME, "/F"])
        if result.returncode != 0:
            msg = (result.stderr or result.stdout or "schtasks 删除失败").strip()
            logger.error("取消计划任务自启失败: %s", msg)

    try:
        _delete_registry_command()
        _delete_startup_shortcut()
        _cleanup_legacy_registry_entries()
    except OSError as exc:
        logger.error("删除注册表自启项失败: %s", exc)
        raise RuntimeError(f"取消自启失败: {exc}") from exc

    update_settings({"autostart_enabled": False})
    return get_autostart_status()


def run_task_now() -> None:
    """Simulate boot trigger when task_scheduler method is active."""
    result = _run_schtasks(["/Run", "/TN", TASK_NAME])
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "schtasks /Run 失败").strip()
        raise RuntimeError(msg)
