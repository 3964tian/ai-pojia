#!/usr/bin/env python3
"""Install the vendored prompt library as Codex config profiles.

Upstream: MDX-Tom/gpt-instruct, commit 3ab84df64468bb74cc9eb4e5423660083953c44f (MIT).
Copyright (c) 2026 li lingbo
Copyright (c) 2026 yynxxxxx
Copyright (c) 2026 左手
See LICENSE and third_party/gpt-instruct/LICENSE.

Each library line becomes a pair of managed files in CODEX_HOME:

  <CODEX_HOME>/ai-pojia-<id>.md          byte-exact upstream prompt
  <CODEX_HOME>/<profile>.config.toml     layered profile selecting that prompt

Selecting a line is then a per-session flag: `codex -p <profile>`.
Nothing here edits the top-level config.toml, so an existing
model_instructions_file keeps working and no global switch is flipped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "prompts" / "library" / "source.json"
STATE = ".ai-pojia-library-state.json"
BACKUPS = ".ai-pojia-library-backups"
PROMPT_PREFIX = "ai-pojia-"
PROFILE_SUFFIX = ".config.toml"
SCHEMA = 1


class LibraryError(Exception):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prompt_name(line_id: str) -> str:
    return PROMPT_PREFIX + line_id + ".md"


def profile_name(profile: str) -> str:
    return profile + PROFILE_SUFFIX


def read_regular(path: Path) -> Optional[bytes]:
    if path.is_symlink():
        raise LibraryError("拒绝符号链接: {}".format(path))
    if not path.exists():
        return None
    if not stat.S_ISREG(path.lstat().st_mode):
        raise LibraryError("拒绝非普通文件: {}".format(path))
    return path.read_bytes()


def atomic_write(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise LibraryError("拒绝写入符号链接: {}".format(path))
    path.parent.mkdir(parents=True, exist_ok=True)
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


def load_manifest() -> List[Dict[str, Any]]:
    raw = read_regular(MANIFEST)
    if raw is None:
        raise LibraryError("清单缺失: {}".format(MANIFEST))
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise LibraryError("清单不是合法 JSON") from error
    if not isinstance(value, dict) or value.get("manifest_version") != 1:
        raise LibraryError("清单版本不受支持")
    lines = value.get("lines")
    if not isinstance(lines, list) or not lines:
        raise LibraryError("清单没有条目")
    seen_id, seen_profile = set(), set()
    for line in lines:
        if not isinstance(line, dict):
            raise LibraryError("清单条目结构无效")
        for key in ("id", "profile", "label", "prompt_file", "sha256", "bytes"):
            if key not in line:
                raise LibraryError("清单条目缺少字段: {}".format(key))
        if line["id"] in seen_id or line["profile"] in seen_profile:
            raise LibraryError("清单存在重复条目")
        if "." in line["profile"] or "/" in line["profile"] or not line["profile"]:
            # Codex rejects dotted profile names; keep the failure at install time.
            raise LibraryError("profile 名不合法: {}".format(line["profile"]))
        seen_id.add(line["id"])
        seen_profile.add(line["profile"])
    return lines


def source_bytes(line: Dict[str, Any]) -> bytes:
    path = ROOT / line["prompt_file"]
    data = read_regular(path)
    if data is None:
        raise LibraryError("提示词文件缺失: {}".format(line["prompt_file"]))
    if len(data) != line["bytes"] or digest(data) != line["sha256"]:
        raise LibraryError("提示词摘要与清单不符: {}".format(line["prompt_file"]))
    return data


def profile_body(line: Dict[str, Any], target: Path) -> bytes:
    text = (
        "# ai-pojia prompt library — generated file, do not hand-edit\n"
        "# line:     {id}\n"
        "# label:    {label}\n"
        "# upstream: MDX-Tom/gpt-instruct@3ab84df (MIT)\n"
        "# usage:    codex -p {profile}\n"
        "model_instructions_file = {value}\n"
    ).format(
        id=line["id"],
        label=line["label"],
        profile=line["profile"],
        value=json.dumps(str(target), ensure_ascii=False),
    )
    return text.encode("utf-8")


def load_state(root: Path) -> Dict[str, Any]:
    raw = read_regular(root / STATE)
    if raw is None:
        return {"schema_version": SCHEMA, "entries": {}}
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise LibraryError("库状态文件损坏") from error
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA:
        raise LibraryError("库状态版本不受支持")
    if not isinstance(value.get("entries"), dict):
        raise LibraryError("库状态结构无效")
    return value


def save_state(root: Path, entries: Dict[str, Any]) -> None:
    payload = {"schema_version": SCHEMA, "entries": entries}
    atomic_write(root / STATE, (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def backup(root: Path, names: List[str]) -> Optional[str]:
    existing = [(name, read_regular(root / name)) for name in names]
    existing = [(name, data) for name, data in existing if data is not None]
    if not existing:
        return None
    stamp = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = root / BACKUPS / stamp
    folder.mkdir(parents=True, mode=0o700)
    for name, data in existing:
        atomic_write(folder / name, data)
    return str(folder)


def plan(root: Path, lines: List[Dict[str, Any]], state: Dict[str, Any]) -> List[Dict[str, Any]]:
    owned = state["entries"]
    items = []
    for line in lines:
        target_prompt = root / prompt_name(line["id"])
        target_profile = root / profile_name(line["profile"])
        data = source_bytes(line)
        body = profile_body(line, target_prompt)
        for path, payload in ((target_prompt, data), (target_profile, body)):
            current = read_regular(path)
            if current is not None and digest(current) != digest(payload):
                entry = owned.get(line["id"])
                # Ownership is recorded by filename, so a drifted copy of our own
                # file is still ours to update; a foreign file is never overwritten.
                is_owned = bool(entry) and path.name in entry.get("files", {})
                if not is_owned:
                    raise LibraryError("同名文件存在且不归本安装器管理，未覆盖: {}".format(path))
        items.append({
            "id": line["id"],
            "profile": line["profile"],
            "label": line["label"],
            "prompt": target_prompt,
            "prompt_bytes": data,
            "profile_file": target_profile,
            "profile_bytes": body,
            "unchanged": read_regular(target_prompt) == data and read_regular(target_profile) == body,
        })
    return items


def install(root: Path, only: Optional[str], dry_run: bool) -> Dict[str, Any]:
    lines = load_manifest()
    if only is not None:
        lines = [line for line in lines if line["id"] == only or line["profile"] == only]
        if not lines:
            raise LibraryError("清单中没有该条目: {}".format(only))
    state = load_state(root)
    items = plan(root, lines, state)
    changed = [item for item in items if not item["unchanged"]]
    result: Dict[str, Any] = {
        "action": "install",
        "codex_dir": str(root),
        "entries": [{"id": item["id"], "profile": item["profile"], "label": item["label"],
                     "prompt": str(item["prompt"]), "profile_file": str(item["profile_file"]),
                     "changed": not item["unchanged"]} for item in items],
    }
    if not changed:
        result["status"] = "unchanged"
        return result
    if dry_run:
        result["status"] = "dry_run"
        return result
    root.mkdir(parents=True, exist_ok=True)
    names = [item["prompt"].name for item in changed] + [item["profile_file"].name for item in changed]
    saved = backup(root, names)
    entries = dict(state["entries"])
    for item in changed:
        atomic_write(item["prompt"], item["prompt_bytes"])
        atomic_write(item["profile_file"], item["profile_bytes"])
        entries[item["id"]] = {
            "profile": item["profile"],
            "label": item["label"],
            "files": {
                item["prompt"].name: digest(item["prompt_bytes"]),
                item["profile_file"].name: digest(item["profile_bytes"]),
            },
        }
    save_state(root, entries)
    result.update(status="installed", changed=[item["id"] for item in changed], backup=saved)
    return result


def doctor(root: Path) -> Dict[str, Any]:
    lines = load_manifest()
    state = load_state(root)
    owned = state["entries"]
    report = []
    healthy = True
    for line in lines:
        entry = owned.get(line["id"])
        target_prompt = root / prompt_name(line["id"])
        target_profile = root / profile_name(line["profile"])
        current_prompt = read_regular(target_prompt)
        current_profile = read_regular(target_profile)
        if entry is None:
            status = "missing"
        elif current_prompt is None or current_profile is None:
            status = "incomplete"
        elif digest(current_prompt) != entry["files"].get(target_prompt.name):
            status = "modified"
        elif digest(current_profile) != entry["files"].get(target_profile.name):
            status = "modified"
        else:
            status = "installed"
        healthy = healthy and status == "installed"
        report.append({"id": line["id"], "profile": line["profile"], "label": line["label"], "status": status,
                       "prompt": str(target_prompt), "profile_file": str(target_profile)})
    return {"action": "doctor", "codex_dir": str(root), "status": "installed" if healthy else "partial",
            "verification": "configuration-only", "entries": report}


def uninstall(root: Path, dry_run: bool) -> Dict[str, Any]:
    state = load_state(root)
    owned = state["entries"]
    if not owned:
        return {"action": "uninstall", "codex_dir": str(root), "status": "missing", "entries": []}
    removed, kept = [], []
    for line_id, entry in sorted(owned.items()):
        for name, expected in entry["files"].items():
            path = root / name
            current = read_regular(path)
            if current is None:
                continue
            if digest(current) != expected:
                kept.append(str(path))
                continue
            removed.append(str(path))
    if dry_run:
        return {"action": "uninstall", "codex_dir": str(root), "status": "dry_run",
                "would_remove": removed, "would_keep": kept}
    saved = backup(root, [Path(name).name for name in removed])
    for name in removed:
        (root / Path(name).name).unlink(missing_ok=True)
    for folder in (root / BACKUPS,):
        if folder.exists() and not any(folder.iterdir()):
            folder.rmdir()
    save_state(root, {})
    return {"action": "uninstall", "codex_dir": str(root), "status": "removed",
            "removed": removed, "kept": kept, "backup": saved}


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(
        description="把内置提示词库安装成 Codex profile；不修改顶层 config.toml。")
    cli.add_argument("--codex-dir", default=os.environ.get("CODEX_HOME") or str(Path.home() / ".codex"),
                     help="Codex 目录（默认 CODEX_HOME 或 ~/.codex）")
    cli.add_argument("--json", action="store_true", help="输出 JSON")
    commands = cli.add_subparsers(dest="command", required=True)
    for name, text in (("install", "安装或更新提示词库"), ("uninstall", "移除本安装器管理的文件"),
                       ("doctor", "只读检查安装状态"), ("list", "列出清单条目")):
        child = commands.add_parser(name, help=text)
        child.add_argument("--codex-dir", default=argparse.SUPPRESS)
        child.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        if name == "install":
            child.add_argument("--line", default=None, help="只安装指定条目 id 或 profile")
            child.add_argument("--dry-run", action="store_true", help="仅预览，零写入")
        if name == "uninstall":
            child.add_argument("--dry-run", action="store_true", help="仅预览，零写入")
    return cli


def main(argv: Optional[List[str]] = None) -> int:
    args = parser().parse_args(argv)
    root = Path(args.codex_dir).expanduser().absolute()
    try:
        if args.command == "install":
            output = install(root, args.line, args.dry_run)
        elif args.command == "uninstall":
            output = uninstall(root, args.dry_run)
        elif args.command == "doctor":
            output = doctor(root)
        else:
            output = {"action": "list", "entries": [
                {"id": line["id"], "profile": line["profile"], "stage": line.get("stage"),
                 "label": line["label"], "bytes": line["bytes"], "sha256": line["sha256"]}
                for line in load_manifest()]}
        code = 1 if output.get("status") in {"partial", "error"} else 0
    except (LibraryError, OSError, UnicodeError, ValueError) as error:
        output = {"action": args.command, "codex_dir": str(root), "status": "error", "error": str(error)}
        code = 1
    if args.json:
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    else:
        if output.get("status") == "error":
            print("error: {}".format(output["error"]))
        else:
            for entry in output.get("entries", []):
                if args.command == "list":
                    print("{:<22} {:<12} {:<9} {}".format(entry["id"], entry["profile"], entry.get("stage", ""), entry["label"]))
                else:
                    print("{:<22} {:<12} {}".format(entry["id"], entry["profile"], entry["status"]))
            if output.get("status"):
                print("status: {}".format(output["status"]))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
