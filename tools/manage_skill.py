#!/usr/bin/env python3
"""Install the ai-pojia Skill without changing the host's model configuration.

The atomic_write_text helper is adapted from MDX-Tom/gpt-instruct,
commit 3ab84df64468bb74cc9eb4e5423660083953c44f (MIT).
Copyright (c) 2026 li lingbo
Copyright (c) 2026 yynxxxxx
Copyright (c) 2026 左手
See LICENSE and third_party/gpt-instruct/LICENSE in this distribution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "skills" / "ai-pojia"
SKILL_NAME = "ai-pojia"
STATE_NAME = ".ai-pojia-install.json"
BACKUPS_NAME = ".ai-pojia-backups"
SCHEMA_VERSION = 1
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class InstallError(Exception):
    """A refusal that preserves existing user files."""


def atomic_write_text(path: Path, text: str, *, follow_symlink: bool = False) -> None:
    """Atomically update text, following symlinks only for explicitly trusted paths."""
    if path.is_symlink() and not follow_symlink:
        raise OSError("refusing to overwrite symlink: {}".format(path))
    write_path = path.resolve(strict=False) if path.is_symlink() else path
    previous_mode = write_path.stat().st_mode & 0o777 if write_path.exists() else 0o600
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".{}.".format(write_path.name),
        dir=write_path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, previous_mode)
        os.replace(temporary_path, write_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def default_skills_dir() -> Path:
    codex_dir = os.environ.get("CODEX_HOME")
    return (Path(codex_dir).expanduser() if codex_dir else Path.home() / ".codex") / "skills"


def checked_directory(path: Path, *, missing_ok: bool = False) -> None:
    if path.is_symlink():
        raise InstallError("拒绝符号链接目录 / symlink directory: {}".format(path))
    if not path.exists():
        if missing_ok:
            return
        raise InstallError("目录不存在 / missing directory: {}".format(path))
    if not path.is_dir():
        raise InstallError("路径不是目录 / not a directory: {}".format(path))


def safe_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return False
    path = PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).drive or str(path) != value:
        return False
    if any(part in (".", "..") or ":" in part for part in path.parts):
        return False
    return bool(path.parts) and value != STATE_NAME


def inventory(root: Path, *, installed: bool = False) -> Dict[str, str]:
    """Hash regular payload files and reject links, special files and empty payloads."""
    checked_directory(root)
    files: Dict[str, str] = {}
    for directory, dirnames, filenames in os.walk(str(root), followlinks=False):
        directory_path = Path(directory)
        for name in sorted(dirnames + filenames):
            entry = directory_path / name
            mode = entry.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise InstallError("拒绝符号链接 / symlink: {}".format(entry))
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise InstallError("拒绝特殊文件 / non-regular file: {}".format(entry))
            relative = entry.relative_to(root).as_posix()
            if relative == STATE_NAME:
                if installed:
                    continue
                raise InstallError("源目录不能携带安装状态文件 / source contains install state")
            if not safe_relative_path(relative):
                raise InstallError("不支持的文件路径 / unsupported path: {}".format(relative))
            files[relative] = hashlib.sha256(entry.read_bytes()).hexdigest()
    if "SKILL.md" not in files:
        raise InstallError("缺少 SKILL.md / missing SKILL.md: {}".format(root))
    return dict(sorted(files.items()))


def load_state(target: Path) -> Dict[str, Any]:
    marker = target / STATE_NAME
    if marker.is_symlink():
        raise InstallError("拒绝符号链接状态文件 / symlink install state")
    if not marker.is_file():
        raise InstallError("已有目录不受本安装器管理，未覆盖 / unmanaged existing directory: {}".format(target))
    try:
        state = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise InstallError("安装状态文件损坏 / invalid install state: {}".format(error)) from error
    expected = {"schema_version", "skill", "files", "installed_at", "source"}
    if not isinstance(state, dict) or set(state) != expected:
        raise InstallError("安装状态结构无效 / invalid install-state schema")
    if type(state["schema_version"]) is not int or state["schema_version"] != SCHEMA_VERSION:
        raise InstallError("不支持的安装状态版本 / unsupported install-state version")
    if state["skill"] != SKILL_NAME or state["source"] != "skills/ai-pojia":
        raise InstallError("安装状态身份不匹配 / install-state identity mismatch")
    if not isinstance(state["installed_at"], str) or not state["installed_at"]:
        raise InstallError("安装时间字段无效 / invalid install timestamp")
    files = state["files"]
    if not isinstance(files, dict) or not files or "SKILL.md" not in files:
        raise InstallError("安装文件清单无效 / empty or invalid payload manifest")
    for relative, digest in files.items():
        if not safe_relative_path(relative) or not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise InstallError("安装文件清单路径或哈希无效 / invalid manifest path or hash")
    return state


def verify_owned(target: Path) -> Tuple[Dict[str, Any], Dict[str, str]]:
    checked_directory(target)
    state = load_state(target)
    current = inventory(target, installed=True)
    if current != state["files"]:
        changed = sorted(name for name in set(current) | set(state["files"])
                         if current.get(name) != state["files"].get(name))
        raise InstallError("安装目录有新增、缺失或修改文件，已保留 / modified installation: {}".format(", ".join(changed)))
    return state, current


def backup_destination(skills_dir: Path) -> Path:
    backups = skills_dir / BACKUPS_NAME
    checked_directory(backups, missing_ok=True)
    backups.mkdir(exist_ok=True)
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return backups / (SKILL_NAME + "-" + suffix + "-" + uuid.uuid4().hex[:8])


def base_result(action: str, skills_dir: Path) -> Dict[str, Any]:
    return {"action": action, "skill": SKILL_NAME,
            "destination": str(skills_dir / SKILL_NAME)}


def install(skills_dir: Path, dry_run: bool) -> Dict[str, Any]:
    checked_directory(skills_dir, missing_ok=True)
    source_files = inventory(SOURCE)
    target = skills_dir / SKILL_NAME
    if target.is_symlink():
        raise InstallError("拒绝符号链接安装目标 / symlink target: {}".format(target))
    result = base_result("install", skills_dir)
    exists = target.exists()
    if exists:
        _, current = verify_owned(target)
        if current == source_files:
            result.update(status="unchanged", message="已安装相同内容 / already installed")
            return result
        checked_directory(skills_dir / BACKUPS_NAME, missing_ok=True)
    if dry_run:
        result.update(status="dry_run", planned_status="updated" if exists else "installed",
                      files=len(source_files), message="仅预览，未写入 / no files written")
        return result

    skills_dir.mkdir(parents=True, exist_ok=True)
    checked_directory(skills_dir)
    staging = Path(tempfile.mkdtemp(prefix=".ai-pojia-staging-", dir=skills_dir))
    backup: Optional[Path] = None
    try:
        for relative in source_files:
            original = SOURCE / relative
            if original.is_symlink():
                raise InstallError("复制时发现源符号链接 / source symlink during copy")
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, destination)
        if inventory(staging) != source_files:
            raise InstallError("复制期间源内容变化，未安装 / source changed during copy")
        state = {"schema_version": SCHEMA_VERSION, "skill": SKILL_NAME,
                 "files": source_files, "installed_at": datetime.now(timezone.utc).isoformat(),
                 "source": "skills/ai-pojia"}
        atomic_write_text(staging / STATE_NAME, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        if exists:
            verify_owned(target)
            backup = backup_destination(skills_dir)
            os.replace(target, backup)
        elif target.exists() or target.is_symlink():
            raise InstallError("安装目标已出现，未覆盖 / destination appeared during install")
        try:
            os.replace(staging, target)
        except BaseException:
            if backup is not None and not target.exists() and not target.is_symlink():
                os.replace(backup, target)
            raise
        result.update(status="updated" if exists else "installed", files=len(source_files),
                      message="安装完成，请开启新会话 / installed; start a new session")
        if backup is not None:
            result["backup"] = str(backup)
        return result
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def uninstall(skills_dir: Path, dry_run: bool) -> Dict[str, Any]:
    checked_directory(skills_dir, missing_ok=True)
    target = skills_dir / SKILL_NAME
    result = base_result("uninstall", skills_dir)
    if target.is_symlink():
        raise InstallError("拒绝符号链接安装目标 / symlink target")
    if not target.exists():
        result.update(status="missing", message="未安装，无需卸载 / not installed")
        return result
    verify_owned(target)
    checked_directory(skills_dir / BACKUPS_NAME, missing_ok=True)
    if dry_run:
        result.update(status="dry_run", planned_status="removed", message="仅预览，未写入 / no files written")
        return result
    backup = backup_destination(skills_dir)
    verify_owned(target)
    os.replace(target, backup)
    result.update(status="removed", backup=str(backup), message="已卸载并归档 / uninstalled and archived")
    return result


def doctor(skills_dir: Path) -> Dict[str, Any]:
    checked_directory(skills_dir, missing_ok=True)
    source_files = inventory(SOURCE)
    target = skills_dir / SKILL_NAME
    result = base_result("doctor", skills_dir)
    result.update(source=str(SOURCE), source_files=len(source_files), python=sys.version.split()[0])
    if target.is_symlink():
        raise InstallError("拒绝符号链接安装目标 / symlink target")
    if not target.exists():
        result.update(status="missing", message="源文件有效，Skill 尚未安装 / source valid; not installed")
        return result
    try:
        _, current = verify_owned(target)
    except InstallError as error:
        result.update(status="modified", message=str(error))
        return result
    result.update(status="installed", update_available=current != source_files,
                  message="安装完整 / installation intact")
    return result


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="安装、检查或卸载 ai-pojia Skill；不修改模型配置。")
    cli.add_argument("--skills-dir", default=str(default_skills_dir()), help="Skill 目录（默认 CODEX_HOME/skills）")
    cli.add_argument("--json", action="store_true", help="输出 JSON")
    commands = cli.add_subparsers(dest="command", required=True)
    for command, description in (("install", "安装或更新 Skill"),
                                  ("uninstall", "验证并归档已安装 Skill"),
                                  ("doctor", "只读检查源文件和安装状态")):
        child = commands.add_parser(command, help=description)
        child.add_argument("--skills-dir", default=argparse.SUPPRESS, help="Skill 目录")
        child.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="输出 JSON")
        if command != "doctor":
            child.add_argument("--dry-run", action="store_true", help="仅预览，零写入")
    return cli


def main(argv: Optional[list] = None) -> int:
    arguments = parser().parse_args(argv)
    skills_dir = Path(arguments.skills_dir).expanduser().absolute()
    try:
        if arguments.command == "install":
            result = install(skills_dir, arguments.dry_run)
        elif arguments.command == "uninstall":
            result = uninstall(skills_dir, arguments.dry_run)
        else:
            result = doctor(skills_dir)
        code = 1 if result["status"] == "modified" else 0
    except (InstallError, OSError, ValueError) as error:
        result = base_result(arguments.command, skills_dir)
        result.update(status="error", error=str(error))
        code = 1
    if arguments.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print("{}: {}".format(result["status"], result.get("message", result.get("error", ""))))
        print("Skill: {}".format(result["destination"]))
        if "backup" in result:
            print("归档 / backup: {}".format(result["backup"]))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
