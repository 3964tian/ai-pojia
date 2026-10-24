#!/usr/bin/env python3
"""Load or restore ai-pojia's packaged instruction profile, without changing tools.

Field-level configuration and atomic-write mechanics adapted from
MDX-Tom/gpt-instruct, commit 3ab84df64468bb74cc9eb4e5423660083953c44f (MIT).
Copyright (c) 2026 li lingbo
Copyright (c) 2026 yynxxxxx
Copyright (c) 2026 左手
See LICENSE and third_party/gpt-instruct/LICENSE.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any, Dict, Optional, Tuple
import uuid


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "prompts" / "ai-pojia.md"
PROFILE = "ai-pojia-instructions.md"
STATE = ".ai-pojia-prompt-state.json"
BACKUPS = ".ai-pojia-prompt-backups"
LOCK = ".ai-pojia-prompt.lock"
ASSIGNMENT = re.compile(r'''^\s*(?:model_instructions_file|"model_instructions_file"|'model_instructions_file')\s*=\s*(.*)$''')
VALUE = re.compile(r'''(?:"(?:[^"\\\r\n]|\\[^\r\n])*"|'[^'\r\n]*')\s*(?:\#.*)?$''')
DIGEST = re.compile(r"[a-f0-9]{64}\Z")
BACKUP_NAME = re.compile(r"[0-9]{8}T[0-9]{12}Z-[a-f0-9]{12}\Z")


class PromptError(Exception):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def directory(path: Path, *, absent_ok: bool = False) -> None:
    if path.is_symlink():
        raise PromptError("拒绝符号链接目录: {}".format(path))
    if not path.exists():
        if absent_ok:
            return
        raise PromptError("目录不存在: {}".format(path))
    if not path.is_dir():
        raise PromptError("路径不是目录: {}".format(path))


def read_regular(path: Path) -> Optional[bytes]:
    if path.is_symlink():
        raise PromptError("拒绝符号链接文件: {}".format(path))
    if not path.exists():
        return None
    if not stat.S_ISREG(path.lstat().st_mode):
        raise PromptError("拒绝非普通文件: {}".format(path))
    return path.read_bytes()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Adapted upstream atomic writer; binary mode also preserves Windows CRLF."""
    if path.is_symlink():
        raise PromptError("拒绝写入符号链接: {}".format(path))
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    descriptor, name = tempfile.mkstemp(prefix=".{}.".format(path.name), dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def instruction_slot(text: str) -> Tuple[Optional[int], int, list]:
    """Find an unambiguous root instruction field while tracking multiline values.

    This deliberately rejects unsupported instruction values rather than editing
    only their first line. Strings/arrays elsewhere are scanned so apparent table
    headers or instruction keys inside their contents are not treated as TOML.
    """
    lines = text.splitlines(keepends=True)
    if text.startswith("\ufeff"):
        raise PromptError("不支持带 BOM 的配置文件，请先另存为 UTF-8")
    found = None
    first_table = len(lines)
    quote = None
    triple = False
    depth = 0
    for number, raw in enumerate(lines):
        line = raw.rstrip("\r\n")
        if quote is None and depth == 0:
            stripped = line.lstrip()
            if stripped.startswith("["):
                first_table = number
                break
            match = ASSIGNMENT.match(line)
            if match:
                value = match.group(1)
                if found is not None:
                    raise PromptError("顶层 model_instructions_file 重复，未修改配置")
                if value.startswith(('"""', "'''")) or not VALUE.fullmatch(value):
                    raise PromptError("不支持多行或非字符串的 model_instructions_file，未修改配置")
                found = number
            elif re.match(r'''^\s*(?:model_instructions_file|"model_instructions_file"|'model_instructions_file')\s*\.''', line):
                raise PromptError("不支持以点号展开的 model_instructions_file，未修改配置")
            # Escaped quoted keys could alias the managed field. Do not guess.
            if re.match(r'^\s*"[^"\n]*\\[^"\n]*"\s*=', line):
                raise PromptError("不支持转义的顶层键名，未修改配置")
        index = 0
        while index < len(line):
            char = line[index]
            if quote:
                if quote == '"' and char == "\\":
                    index += 2
                    continue
                token = quote * (3 if triple else 1)
                if line.startswith(token, index):
                    index += len(token)
                    quote, triple = None, False
                    continue
                index += 1
                continue
            if char == "#":
                break
            if char in ('"', "'"):
                quote = char
                triple = line.startswith(char * 3, index)
                index += 3 if triple else 1
                continue
            if char in "[{":
                depth += 1
            elif char in "]}":
                depth -= 1
                if depth < 0:
                    raise PromptError("配置括号不平衡，未修改配置")
            index += 1
        if quote is not None and not triple:
            raise PromptError("配置包含未闭合单行字符串，未修改配置")
    if quote is not None or depth != 0:
        raise PromptError("配置含未闭合的多行值，未修改配置")
    return found, first_table, lines


def current_field(text: str) -> Optional[str]:
    index, _, lines = instruction_slot(text)
    return lines[index].rstrip("\r\n") if index is not None else None


def replace_field(text: str, replacement: Optional[str]) -> str:
    index, first_table, lines = instruction_slot(text)
    if index is not None:
        old = lines[index]
        ending = "\r\n" if old.endswith("\r\n") else "\n" if old.endswith("\n") else ""
        if replacement is None:
            del lines[index]
        else:
            lines[index] = replacement + ending
    elif replacement is not None:
        ending = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"
        if first_table and not lines[first_table - 1].endswith("\n"):
            lines[first_table - 1] += ending
        lines.insert(first_table, replacement + ending)
    return "".join(lines)


def managed_line(root: Path) -> str:
    return "model_instructions_file = " + json.dumps(str(root / PROFILE), ensure_ascii=False)


def read_state(root: Path) -> Optional[Dict[str, Any]]:
    raw = read_regular(root / STATE)
    if raw is None:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise PromptError("提示词管理状态损坏") from error
    expected = {"schema_version", "profile", "original_field", "config_before_existed",
                "config_before_sha256", "clean_config_sha256", "baseline_backup",
                "managed_line", "prompt_sha256", "installed_at"}
    if not isinstance(value, dict) or set(value) != expected:
        raise PromptError("提示词管理状态结构无效")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["profile"] != PROFILE:
        raise PromptError("提示词管理状态版本或身份无效")
    if type(value["config_before_existed"]) is not bool or value["managed_line"] != managed_line(root):
        raise PromptError("提示词管理路径或状态无效")
    for key in ("config_before_sha256", "clean_config_sha256", "prompt_sha256"):
        if not isinstance(value[key], str) or not DIGEST.fullmatch(value[key]):
            raise PromptError("提示词管理摘要无效")
    field = value["original_field"]
    if field is not None and (not isinstance(field, str) or "\n" in field or "\r" in field or current_field(field) != field):
        raise PromptError("保存的原指令字段无效")
    baseline = value["baseline_backup"]
    if value["config_before_existed"]:
        if not isinstance(baseline, str) or not BACKUP_NAME.fullmatch(baseline):
            raise PromptError("原配置备份路径无效")
    elif baseline is not None or field is not None or value["config_before_sha256"] != digest(b""):
        raise PromptError("原配置状态不一致")
    if not isinstance(value["installed_at"], str) or not value["installed_at"]:
        raise PromptError("提示词管理时间无效")
    return value


def source_bytes() -> bytes:
    directory(SOURCE.parent)
    data = read_regular(SOURCE)
    if data is None or not data.strip():
        raise PromptError("打包的提示词缺失或为空: {}".format(SOURCE))
    data.decode("utf-8")
    return data


def verify_managed(root: Path, state: Dict[str, Any]) -> bytes:
    config = read_regular(root / "config.toml")
    profile = read_regular(root / PROFILE)
    if config is None or profile is None:
        raise PromptError("受管配置或提示词缺失，已保留现场")
    if digest(profile) != state["prompt_sha256"]:
        raise PromptError("已安装提示词被修改，未覆盖或删除")
    if current_field(config.decode("utf-8")) != state["managed_line"]:
        raise PromptError("指令字段已被其他操作修改，未覆盖配置")
    return config


@contextmanager
def locked(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    directory(root)
    lock = root / LOCK
    try:
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise PromptError("另一安装操作正在进行，或上次中断留下锁文件: {}".format(lock)) from error
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def snapshot(root: Path) -> Dict[str, Optional[bytes]]:
    return {name: read_regular(root / name) for name in ("config.toml", PROFILE, STATE)}


def backup(root: Path, before: Dict[str, Optional[bytes]]) -> str:
    parent = root / BACKUPS
    directory(parent, absent_ok=True)
    parent.mkdir(mode=0o700, exist_ok=True)
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:12]
    destination = parent / name
    destination.mkdir(mode=0o700)
    for filename, data in before.items():
        if data is not None:
            atomic_write_bytes(destination / filename, data)
    return name


def apply_transaction(root: Path, before: Dict[str, Optional[bytes]], after: Dict[str, Optional[bytes]]) -> None:
    if snapshot(root) != before:
        raise PromptError("操作期间文件发生变化，未写入")
    try:
        for name, data in after.items():
            if data is None:
                (root / name).unlink(missing_ok=True)
            else:
                atomic_write_bytes(root / name, data)
    except BaseException as original:
        errors = []
        for name, data in before.items():
            try:
                if data is None:
                    (root / name).unlink(missing_ok=True)
                else:
                    atomic_write_bytes(root / name, data)
            except (PromptError, OSError) as error:
                errors.append(str(error))
        if errors:
            raise PromptError("写入失败，自动恢复也遇到错误；备份已保留: " + "; ".join(errors)) from original
        raise


def result(action: str, root: Path) -> Dict[str, Any]:
    return {"action": action, "codex_dir": str(root), "profile": str(root / PROFILE)}


def install(root: Path, dry_run: bool = False) -> Dict[str, Any]:
    directory(root, absent_ok=True)
    source = source_bytes()
    before = snapshot(root)
    state = read_state(root)
    raw_config = before["config.toml"]
    config = (raw_config or b"").decode("utf-8")
    previous = current_field(config)
    if state:
        verify_managed(root, state)
        if digest(source) == state["prompt_sha256"]:
            return dict(result("install", root), status="unchanged", source_sha256=digest(source))
    elif before[PROFILE] is not None:
        raise PromptError("同名提示词不受本安装器管理，未覆盖")
    directory(root / BACKUPS, absent_ok=True)
    if dry_run:
        return dict(result("install", root), status="dry_run", source_sha256=digest(source))
    with locked(root):
        if snapshot(root) != before:
            raise PromptError("操作期间文件发生变化，未写入")
        saved = backup(root, before)
        line = managed_line(root)
        new_config = replace_field(config, line).encode("utf-8")
        new_state = dict(state) if state else {
            "schema_version": 1, "profile": PROFILE, "original_field": previous,
            "config_before_existed": raw_config is not None,
            "config_before_sha256": digest(raw_config or b""),
            "clean_config_sha256": digest(new_config),
            "baseline_backup": saved if raw_config is not None else None,
            "managed_line": line,
            "installed_at": datetime.now(timezone.utc).isoformat(),
        }
        new_state["prompt_sha256"] = digest(source)
        after = {PROFILE: source, "config.toml": new_config,
                 STATE: (json.dumps(new_state, ensure_ascii=False, indent=2) + "\n").encode("utf-8")}
        apply_transaction(root, before, after)
    return dict(result("install", root), status="updated" if state else "installed",
                source_sha256=digest(source), backup=str(root / BACKUPS / saved))


def uninstall(root: Path, dry_run: bool = False) -> Dict[str, Any]:
    directory(root, absent_ok=True)
    before = snapshot(root)
    state = read_state(root)
    if not state:
        if before[PROFILE] is not None:
            raise PromptError("存在未受管的同名提示词，未删除")
        return dict(result("uninstall", root), status="missing")
    config = verify_managed(root, state)
    directory(root / BACKUPS)
    if digest(config) == state["clean_config_sha256"]:
        if state["config_before_existed"]:
            baseline = root / BACKUPS / state["baseline_backup"]
            directory(baseline)
            restored = read_regular(baseline / "config.toml")
            if restored is None or digest(restored) != state["config_before_sha256"]:
                raise PromptError("原配置备份缺失或摘要不符，未卸载")
        else:
            restored = None
    else:
        restored = replace_field(config.decode("utf-8"), state["original_field"]).encode("utf-8")
    if dry_run:
        return dict(result("uninstall", root), status="dry_run")
    with locked(root):
        if snapshot(root) != before:
            raise PromptError("操作期间文件发生变化，未写入")
        saved = backup(root, before)
        apply_transaction(root, before, {"config.toml": restored, PROFILE: None, STATE: None})
    return dict(result("uninstall", root), status="removed", backup=str(root / BACKUPS / saved))


def doctor(root: Path) -> Dict[str, Any]:
    directory(root, absent_ok=True)
    source = source_bytes()
    state = read_state(root)
    status = result("doctor", root)
    status.update(source_sha256=digest(source), source=str(SOURCE), python=sys.version.split()[0],
                  verification="configuration-only")
    if not state:
        if read_regular(root / PROFILE) is not None:
            raise PromptError("存在未受管的同名提示词")
        status.update(status="missing", configured=False)
        return status
    try:
        verify_managed(root, state)
    except PromptError as error:
        status.update(status="modified", configured=False, error=str(error))
        return status
    status.update(status="installed", configured=True, update_available=state["prompt_sha256"] != digest(source))
    return status


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="安装、检查或恢复 ai-pojia 自定义提示词配置")
    default = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
    cli.add_argument("--codex-dir", default=default)
    cli.add_argument("--json", action="store_true")
    children = cli.add_subparsers(dest="command", required=True)
    for command in ("install", "uninstall", "doctor"):
        child = children.add_parser(command)
        child.add_argument("--codex-dir", default=argparse.SUPPRESS)
        child.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        if command != "doctor":
            child.add_argument("--dry-run", action="store_true")
    return cli


def main(argv: Optional[list] = None) -> int:
    args = parser().parse_args(argv)
    root = Path(args.codex_dir).expanduser().absolute()
    try:
        if args.command == "install":
            output = install(root, args.dry_run)
        elif args.command == "uninstall":
            output = uninstall(root, args.dry_run)
        else:
            output = doctor(root)
        code = 1 if output["status"] == "modified" else 0
    except (PromptError, OSError, UnicodeError, ValueError) as error:
        output = dict(result(args.command, root), status="error", error=str(error))
        code = 1
    if args.json:
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    else:
        print("{}: {}".format(output["status"], output.get("error", "")))
        print("Profile: {}".format(output["profile"]))
        if "backup" in output:
            print("Backup: {}".format(output["backup"]))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
