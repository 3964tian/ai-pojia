"""Verify prompt deployment through its CLI without using a real Codex profile."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = PROJECT_ROOT / "tools" / "manage_prompt.py"
PROMPT_NAME = "ai-pojia-instructions.md"
STATE_NAME = ".ai-pojia-prompt-state.json"
BACKUPS_NAME = ".ai-pojia-prompt-backups"
FIXTURE_PROMPT = "# Fixture instructions\n\nInspect the user's own demo and report evidence.\n示例文本。\n"
PROVIDER_CONFIG = (
    "# User configuration; formatting belongs to the user.\n"
    'model = "fixture-model"\n'
    'model_provider = "fixture-provider" # retain this comment\n'
    "\n"
    "[model_providers.fixture-provider]\n"
    'name = "Fixture provider"\n'
    'base_url = "https://example.invalid/v1"\n'
    "\n"
    "[profiles.review]\n"
    'model = "review-model"\n'
    'model_instructions_file = "profile-owned.md" # nested field\n'
)


def snapshot(root: Path) -> dict[str, tuple[str, bytes | str]]:
    if not root.exists() and not root.is_symlink():
        return {}
    result: dict[str, tuple[str, bytes | str]] = {}
    for path in [root, *root.rglob("*")]:
        name = "." if path == root else path.relative_to(root).as_posix()
        if path.is_symlink():
            result[name] = ("link", os.readlink(path))
        elif path.is_dir():
            result[name] = ("directory", "")
        else:
            result[name] = ("file", path.read_bytes())
    return result


def root_instruction(text: str) -> str | None:
    """Read only the root key, independently of any same-named profile setting."""
    table = re.search(r"(?m)^\s*\[", text)
    root = text[: table.start()] if table else text
    for line in root.splitlines():
        match = re.match(r"^\s*model_instructions_file\s*=\s*(.+)$", line)
        if match:
            if tomllib is not None:
                return tomllib.loads(line)["model_instructions_file"]
            # All fixtures and the expected generated assignment use quoted strings.
            literal = re.match(r'''(?:"(?:\\.|[^"\\])*"|'[^']*')''', match.group(1))
            if literal:
                return ast.literal_eval(literal.group(0))
            raise AssertionError("The root instruction value is not a quoted string")
    return None


class ManagePromptCLITest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ai-pojia-prompt-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repository"
        self.script = self.repo / "tools" / "manage_prompt.py"
        self.script.parent.mkdir(parents=True)
        shutil.copy2(INSTALLER, self.script)
        self.source = self.repo / "prompts" / "ai-pojia.md"
        self.source.parent.mkdir()
        self.source.write_text(FIXTURE_PROMPT, encoding="utf-8")
        (self.repo / "plugin.json").write_text(
            json.dumps({"name": "ai-pojia", "version": "0.1.0"}), encoding="utf-8"
        )
        self.codex = self.root / "Codex user data with spaces"
        self.config = self.codex / "config.toml"
        self.target = self.codex / PROMPT_NAME
        self.state = self.codex / STATE_NAME
        self.backups = self.codex / BACKUPS_NAME

    def run_cli(self, command: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(self.script),
                command,
                "--codex-dir",
                str(self.codex),
                "--json",
                *arguments,
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def assert_success(self, result: subprocess.CompletedProcess[str]) -> dict:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertIsInstance(data, dict)
        return data

    def write_config(self, text: str) -> None:
        self.codex.mkdir(parents=True, exist_ok=True)
        self.config.write_text(text, encoding="utf-8")

    def install(self) -> None:
        self.assert_success(self.run_cli("install"))

    def assert_active_target(self) -> None:
        text = self.config.read_text(encoding="utf-8")
        value = root_instruction(text)
        self.assertIsInstance(value, str)
        resolved = Path(value)
        if not resolved.is_absolute():
            resolved = self.codex / resolved
        self.assertEqual(resolved.resolve(), self.target.resolve())
        if tomllib is not None:
            self.assertEqual(tomllib.loads(text)["model_instructions_file"], value)

    def assert_mutations_refuse_without_writes(self) -> None:
        before = snapshot(self.root)
        for command in ("install", "uninstall"):
            with self.subTest(command=command):
                result = self.run_cli(command)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(snapshot(self.root), before)

    def symlink(self, link: Path, target: Path, *, directory: bool = False) -> None:
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"Symlinks are unavailable: {error}")

    def test_fresh_install_creates_valid_config_and_exact_utf8_prompt(self) -> None:
        self.install()
        self.assertEqual(self.target.read_text(encoding="utf-8"), FIXTURE_PROMPT)
        self.assertTrue(self.state.is_file())
        self.assert_active_target()

    def test_install_preserves_provider_comments_and_nested_instruction(self) -> None:
        self.write_config(PROVIDER_CONFIG)
        self.install()
        text = self.config.read_text(encoding="utf-8")
        self.assert_active_target()
        for line in PROVIDER_CONFIG.splitlines():
            if line:
                self.assertIn(line, text)
        if tomllib is not None:
            parsed = tomllib.loads(text)
            self.assertEqual(parsed["model_provider"], "fixture-provider")
            self.assertEqual(parsed["profiles"]["review"]["model_instructions_file"], "profile-owned.md")
            self.assertEqual(parsed["model_providers"]["fixture-provider"]["base_url"], "https://example.invalid/v1")

    def test_uninstall_restores_original_instruction_line_and_comment_exactly(self) -> None:
        original = "model_instructions_file = 'previous instructions.md' # original comment\n" + PROVIDER_CONFIG
        self.write_config(original)
        self.install()
        self.assert_success(self.run_cli("uninstall"))
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)
        self.assertFalse(self.target.exists())

    def test_uninstall_preserves_a_commented_out_original_key(self) -> None:
        original = '# model_instructions_file = "disabled.md" # keep disabled\n' + PROVIDER_CONFIG
        self.write_config(original)
        self.install()
        self.assert_success(self.run_cli("uninstall"))
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)
        self.assertIsNone(root_instruction(original))

    def test_nested_key_is_not_replaced_when_root_key_is_missing(self) -> None:
        original = '[profiles.review]\nmodel_instructions_file = "leave-this.md"\n'
        self.write_config(original)
        self.install()
        self.assert_active_target()
        text = self.config.read_text(encoding="utf-8")
        self.assertIn(original, text)
        self.assert_success(self.run_cli("uninstall"))
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)

    def test_repeated_install_is_idempotent(self) -> None:
        self.write_config(PROVIDER_CONFIG)
        self.install()
        before = snapshot(self.codex)
        self.assert_success(self.run_cli("install"))
        self.assertEqual(snapshot(self.codex), before)

    def test_source_update_replaces_prompt_and_retains_old_prompt_in_backups(self) -> None:
        self.install()
        updated = FIXTURE_PROMPT + "A new version of this harmless fixture.\n"
        self.source.write_text(updated, encoding="utf-8")
        self.assert_success(self.run_cli("install"))
        self.assertEqual(self.target.read_text(encoding="utf-8"), updated)
        self.assert_active_target()
        backup_contents = [path.read_bytes() for path in self.backups.rglob("*") if path.is_file()]
        self.assertIn(FIXTURE_PROMPT.encode("utf-8"), backup_contents)

    def test_later_provider_and_profile_changes_survive_uninstall(self) -> None:
        self.write_config(PROVIDER_CONFIG)
        self.install()
        changed = self.config.read_text(encoding="utf-8").replace(
            'base_url = "https://example.invalid/v1"', 'base_url = "https://changed.invalid/v2"'
        ).replace('model = "review-model"', 'model = "changed-review-model"')
        self.config.write_text(changed, encoding="utf-8")
        self.assert_success(self.run_cli("uninstall"))
        expected = PROVIDER_CONFIG.replace("https://example.invalid/v1", "https://changed.invalid/v2").replace(
            'model = "review-model"', 'model = "changed-review-model"'
        )
        self.assertEqual(self.config.read_text(encoding="utf-8"), expected)

    def test_manually_edited_prompt_blocks_update_and_uninstall(self) -> None:
        self.install()
        self.target.write_text("My local instruction edits.\n", encoding="utf-8")
        self.assert_mutations_refuse_without_writes()

    def test_externally_changed_root_instruction_blocks_update_and_uninstall(self) -> None:
        self.install()
        changed = re.sub(
            r"(?m)^\s*model_instructions_file\s*=.*$",
            'model_instructions_file = "external-owner.md" # changed later',
            self.config.read_text(encoding="utf-8"),
            count=1,
        )
        self.config.write_text(changed, encoding="utf-8")
        self.assert_mutations_refuse_without_writes()

    def test_corrupt_state_blocks_update_and_uninstall(self) -> None:
        self.install()
        self.state.write_text("{invalid json", encoding="utf-8")
        self.assert_mutations_refuse_without_writes()

    def test_wrong_state_shape_blocks_update_and_uninstall(self) -> None:
        self.install()
        self.state.write_text("[]\n", encoding="utf-8")
        self.assert_mutations_refuse_without_writes()

    def test_unmanaged_same_named_prompt_is_not_overwritten(self) -> None:
        self.write_config(PROVIDER_CONFIG)
        self.target.write_text("Not installed by this project.\n", encoding="utf-8")
        self.assert_mutations_refuse_without_writes()

    def test_install_dry_run_creates_no_directories(self) -> None:
        before = snapshot(self.root)
        self.assert_success(self.run_cli("install", "--dry-run"))
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(self.codex.exists())

    def test_update_and_uninstall_dry_runs_do_not_modify_any_files(self) -> None:
        self.install()
        self.source.write_text(FIXTURE_PROMPT + "Updated fixture.\n", encoding="utf-8")
        before = snapshot(self.root)
        self.assert_success(self.run_cli("install", "--dry-run"))
        self.assertEqual(snapshot(self.root), before)
        self.assert_success(self.run_cli("uninstall", "--dry-run"))
        self.assertEqual(snapshot(self.root), before)

    def test_fresh_install_uninstall_removes_only_managed_prompt(self) -> None:
        self.install()
        auth = self.codex / "auth.json"
        auth.write_text('{"fixture": "unchanged"}\n', encoding="utf-8")
        self.assert_success(self.run_cli("uninstall"))
        self.assertFalse(self.target.exists())
        self.assertEqual(auth.read_text(encoding="utf-8"), '{"fixture": "unchanged"}\n')
        if self.config.exists():
            self.assertIsNone(root_instruction(self.config.read_text(encoding="utf-8")))

    def test_source_prompt_symlink_is_not_followed(self) -> None:
        external = self.root / "external-prompt.md"
        external.write_text(FIXTURE_PROMPT, encoding="utf-8")
        self.source.unlink()
        self.symlink(self.source, external)
        before = snapshot(self.root)
        result = self.run_cli("install")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(snapshot(self.root), before)

    def test_target_prompt_symlink_is_not_followed(self) -> None:
        self.write_config(PROVIDER_CONFIG)
        external = self.root / "external-target.md"
        external.write_text("Unrelated content.\n", encoding="utf-8")
        self.symlink(self.target, external)
        self.assert_mutations_refuse_without_writes()

    def test_config_symlink_is_not_followed(self) -> None:
        self.codex.mkdir()
        external = self.root / "external-config.toml"
        external.write_text(PROVIDER_CONFIG, encoding="utf-8")
        self.symlink(self.config, external)
        self.assert_mutations_refuse_without_writes()

    def test_state_symlink_is_not_followed(self) -> None:
        self.install()
        external = self.root / "external-state.json"
        external.write_bytes(self.state.read_bytes())
        self.state.unlink()
        self.symlink(self.state, external)
        self.assert_mutations_refuse_without_writes()

    def test_codex_directory_symlink_is_not_followed(self) -> None:
        external = self.root / "external-codex"
        external.mkdir()
        self.symlink(self.codex, external, directory=True)
        self.assert_mutations_refuse_without_writes()

    def test_doctor_is_read_only_before_and_after_install(self) -> None:
        before = snapshot(self.root)
        self.assert_success(self.run_cli("doctor"))
        self.assertEqual(snapshot(self.root), before)
        self.install()
        before = snapshot(self.root)
        self.assert_success(self.run_cli("doctor"))
        self.assertEqual(snapshot(self.root), before)

    def test_doctor_detects_an_edited_prompt_without_writing(self) -> None:
        self.install()
        self.target.write_text("Locally modified.\n", encoding="utf-8")
        before = snapshot(self.root)
        result = self.run_cli("doctor")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(snapshot(self.root), before)


if __name__ == "__main__":
    unittest.main()
