#!/usr/bin/env python3
"""Install ai-pojia's instruction profile and Skill through their managed CLIs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any, Optional


ROOT = Path(__file__).resolve().parent
COMPONENTS = ("prompt", "skill")
LABELS = {"prompt": "提示词", "skill": "Skill"}


def child_command(component: str, action: str, codex_dir: Path, *, dry_run: bool = False) -> list[str]:
    command = [sys.executable, str(ROOT / "tools" / ("manage_" + component + ".py")), action]
    if component == "prompt":
        command.extend(["--codex-dir", str(codex_dir)])
    else:
        command.extend(["--skills-dir", str(codex_dir / "skills")])
    command.append("--json")
    if dry_run and action != "doctor":
        command.append("--dry-run")
    return command


def invoke(component: str, action: str, codex_dir: Path, *, dry_run: bool = False) -> tuple[dict[str, Any], bool]:
    """Never echo a child traceback, raw stdout, stderr, or configuration contents."""
    try:
        completed = subprocess.run(
            child_command(component, action, codex_dir, dry_run=dry_run),
            capture_output=True, text=True, encoding="utf-8", check=False,
        )
    except (OSError, UnicodeError):
        return {"status": "error", "error": "无法运行{}管理工具，请检查 Python 和工具文件。".format(LABELS[component])}, False
    try:
        output = json.loads(completed.stdout)
        if not isinstance(output, dict) or not isinstance(output.get("status"), str):
            raise ValueError("invalid tool result")
    except (ValueError, UnicodeError):
        return {"status": "error", "error": "{}管理工具未返回有效 JSON；未输出工具原文。".format(LABELS[component]),
                "exit_code": completed.returncode}, False
    output["exit_code"] = completed.returncode
    valid = {"installed", "updated", "unchanged", "dry_run", "removed", "missing"}
    return output, completed.returncode == 0 and output["status"] in valid


def recovery_actions(codex_dir: Path, action: str) -> list[dict[str, Any]]:
    base = [sys.executable, str(ROOT / "install.py")]
    return [
        {"description": "先只读检查当前状态", "argv": base + ["--doctor", "--codex-dir", str(codex_dir)]},
        {"description": "处理冲突后继续{}".format("安装" if action == "install" else "卸载"),
         "argv": base + ["--" + action, "--codex-dir", str(codex_dir)]},
    ]


def skill_source_hashes() -> dict[str, str]:
    """Hash only packaged source files; child doctor already validates this tree."""
    source = ROOT / "skills" / "ai-pojia"
    hashes: dict[str, str] = {}
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise OSError("source link")
        if path.is_file():
            hashes[path.relative_to(source).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def execute(action: str, codex_dir: Path, dry_run: bool = False) -> tuple[dict[str, Any], int]:
    output: dict[str, Any] = {
        "action": action, "codex_dir": str(codex_dir), "dry_run": dry_run,
        "components": {}, "completed_components": [], "changed_components": [],
        "model_tested": False,
    }
    if action == "doctor":
        okay = True
        for component in COMPONENTS:
            data, success = invoke(component, action, codex_dir)
            output["components"][component] = data
            okay = okay and success
        output["source_hashes"] = {"prompt_sha256": output["components"]["prompt"].get("source_sha256")}
        if output["components"]["skill"].get("exit_code") == 0:
            try:
                output["source_hashes"]["skill_files_sha256"] = skill_source_hashes()
            except OSError:
                okay = False
                output["error"] = "检查期间 Skill 源文件发生变化，请重新检查。"
        enabled = bool(output["components"]["prompt"].get("configured", output["components"]["prompt"].get("loaded", False)))
        skill_installed = output["components"]["skill"].get("status") == "installed"
        output.update(status="checked" if okay else "error", prompt_enabled=enabled, skill_installed=skill_installed,
                      message="只检查本地文件、配置与源文件摘要；未调用模型。")
        return output, 0 if okay else 1

    if action == "install":
        preflight: dict[str, Any] = {}
        passed = True
        for component in COMPONENTS:
            data, success = invoke(component, action, codex_dir, dry_run=True)
            preflight[component] = data
            passed = passed and success
        output["preflight"] = preflight
        if not passed:
            output.update(status="error", components=preflight, message="安装预检未通过，未执行安装写入。",
                          recovery_commands=recovery_actions(codex_dir, action))
            return output, 1
        if dry_run:
            output.update(status="dry_run", components=preflight, message="预检通过；仅预览，未写入。")
            return output, 0

    # Uninstall intentionally closes the prompt before checking/removing the Skill.
    # An edited Skill must not keep an otherwise removable prompt enabled.
    for component in COMPONENTS:
        data, success = invoke(component, action, codex_dir, dry_run=dry_run)
        output["components"][component] = data
        if not success:
            output.update(status="partial" if output["completed_components"] else "error",
                          failed_component=component, recovery_commands=recovery_actions(codex_dir, action),
                          message="{}处理失败；已完成的组件保持当前状态，未自动回滚。".format(LABELS[component]))
            if action == "install" and "prompt" in output["completed_components"]:
                output["recovery_commands"].append({
                    "description": "如需关闭已加载提示词，恢复最初记录的指令字段（不会回到本次更新前的提示词版本）",
                    "argv": child_command("prompt", "uninstall", codex_dir),
                })
            return output, 1
        if not dry_run:
            output["completed_components"].append(component)
            if data["status"] in {"installed", "updated", "removed"}:
                output["changed_components"].append(component)
    if dry_run:
        output.update(status="dry_run", message="仅预览，未写入。")
    elif action == "uninstall":
        output.update(status="removed" if output["changed_components"] else "unchanged",
                      message="提示词已关闭，Skill 已卸载。")
    else:
        statuses = {data["status"] for data in output["components"].values()}
        output.update(status="unchanged" if statuses == {"unchanged"} else "updated" if "updated" in statuses else "installed",
                      message="提示词和 Skill 已安装。请重启 Codex 或新开会话。")
    return output, 0


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="一键安装 AI破甲提示词与 Skill；默认执行安装。")
    actions = cli.add_mutually_exclusive_group()
    actions.add_argument("--install", dest="action", action="store_const", const="install", help="安装或更新两项组件（默认）")
    actions.add_argument("--uninstall", dest="action", action="store_const", const="uninstall", help="先关闭提示词，再卸载 Skill")
    actions.add_argument("--doctor", dest="action", action="store_const", const="doctor", help="只读检查安装状态与源文件摘要")
    cli.set_defaults(action="install")
    cli.add_argument("--codex-dir", default=os.environ.get("CODEX_HOME") or str(Path.home() / ".codex"), help="Codex 目录（默认 CODEX_HOME 或 ~/.codex）")
    cli.add_argument("--dry-run", action="store_true", help="仅预览，零写入")
    cli.add_argument("--json", action="store_true", help="输出 JSON，供脚本与测试读取")
    return cli


def main(argv: Optional[list[str]] = None) -> int:
    args = parser().parse_args(argv)
    codex_dir = Path(args.codex_dir).expanduser().absolute()
    output, code = execute(args.action, codex_dir, args.dry_run)
    if args.json:
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    else:
        print(output["message"])
        for component, data in output["components"].items():
            print("{}：{}".format(LABELS[component], data.get("error", data.get("message", data["status"]))))
        if args.action == "doctor":
            print("提示词启用：{}；Skill 已安装：{}。".format("是" if output["prompt_enabled"] else "否", "是" if output["skill_installed"] else "否"))
            print("源文件摘要：" + json.dumps(output["source_hashes"], ensure_ascii=False, sort_keys=True))
        if code:
            for recovery in output.get("recovery_commands", []):
                print(recovery["description"] + "：")
                print(shlex.join(recovery["argv"]))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
