"""Exercise the combined entry point only against temporary fixture repositories."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROFILE = "ai-pojia-instructions.md"
PROMPT_STATE = ".ai-pojia-prompt-state.json"
FIXTURE = "# Safe fixture\n\nInspect the user's own demo and report evidence.\n"
CONFIG = (
    '# Preserve all user settings and comments.\n'
    'model = "fixture-model"\n'
    'model_provider = "fixture-provider"\n'
    'model_instructions_file = "previous.md" # user field\n'
    '\n[model_providers.fixture-provider]\n'
    'name = "Fixture provider"\n'
    'base_url = "https://example.invalid/v1"\n'
)


def snapshot(root: Path) -> dict:
    if not root.exists():
        return {}
    output = {}
    for path in [root, *root.rglob("*")]:
        name = "." if path == root else path.relative_to(root).as_posix()
        output[name] = ("link", os.readlink(path)) if path.is_symlink() else ("dir", "") if path.is_dir() else ("file", path.read_bytes())
    return output


class CombinedInstallerTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="ai-pojia-combined-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repository"
        self.repo.mkdir()
        self.script = self.repo / "install.py"
        shutil.copy2(ROOT / "install.py", self.script)
        (self.repo / "tools").mkdir()
        for name in ("manage_prompt.py", "manage_skill.py"):
            shutil.copy2(ROOT / "tools" / name, self.repo / "tools" / name)
        self.source = self.repo / "prompts" / "ai-pojia.md"
        self.source.parent.mkdir()
        self.source.write_text(FIXTURE, encoding="utf-8")
        self.skill_source = self.repo / "skills" / "ai-pojia"
        self.skill_source.mkdir(parents=True)
        (self.skill_source / "SKILL.md").write_text(
            "---\nname: ai-pojia\ndescription: Inspect user-owned demo projects.\n---\n\n# Fixture\n", encoding="utf-8"
        )
        self.codex = self.root / "fixture-client"
        self.config = self.codex / "config.toml"
        self.profile = self.codex / PROFILE
        self.skill = self.codex / "skills" / "ai-pojia"

    def run_cli(self, *arguments: str, explicit_dir: bool = True) -> tuple[subprocess.CompletedProcess[str], dict]:
        command = [sys.executable, str(self.script), *arguments, "--json"]
        if explicit_dir:
            command.extend(["--codex-dir", str(self.codex)])
        env = dict(os.environ, CODEX_HOME=str(self.codex))
        result = subprocess.run(command, cwd=self.repo, env=env, capture_output=True, text=True, timeout=30, check=False)
        return result, json.loads(result.stdout)

    def install(self) -> dict:
        result, output = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return output

    def write_config(self) -> None:
        self.codex.mkdir()
        self.config.write_text(CONFIG, encoding="utf-8")

    def test_default_installs_both_and_respects_codex_home(self) -> None:
        result, output = self.run_cli(explicit_dir=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output["completed_components"], ["prompt", "skill"])
        self.assertEqual(self.profile.read_text(encoding="utf-8"), FIXTURE)
        self.assertEqual((self.skill / "SKILL.md").read_bytes(), (self.skill_source / "SKILL.md").read_bytes())
        self.assertIn(str(self.profile), self.config.read_text(encoding="utf-8"))
        self.assertFalse(output["model_tested"])

    def test_install_dry_run_is_zero_write_including_directories(self) -> None:
        before = snapshot(self.root)
        result, output = self.run_cli("--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output["status"], "dry_run")
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(self.codex.exists())

    def test_prompt_conflict_preflight_does_not_install_skill(self) -> None:
        self.write_config()
        self.profile.write_text("Existing user text.\n", encoding="utf-8")
        before = snapshot(self.root)
        result, output = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output["completed_components"], [])
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(self.skill.exists())

    def test_skill_conflict_preflight_does_not_load_prompt(self) -> None:
        self.write_config()
        self.skill.mkdir(parents=True)
        (self.skill / "SKILL.md").write_text("User-owned content.\n", encoding="utf-8")
        before = snapshot(self.root)
        result, output = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output["completed_components"], [])
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(self.profile.exists())

    def test_uninstall_restores_original_field_and_preserves_later_provider_edits(self) -> None:
        self.write_config()
        self.install()
        changed = self.config.read_text(encoding="utf-8").replace("https://example.invalid/v1", "https://changed.invalid/v2")
        self.config.write_text(changed, encoding="utf-8")
        auth = self.codex / "auth.json"
        auth.write_text('{"fixture":"do-not-read-or-alter"}\n', encoding="utf-8")
        result, output = self.run_cli("--uninstall")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output["completed_components"], ["prompt", "skill"])
        self.assertEqual(self.config.read_text(encoding="utf-8"), CONFIG.replace("https://example.invalid/v1", "https://changed.invalid/v2"))
        self.assertEqual(auth.read_text(encoding="utf-8"), '{"fixture":"do-not-read-or-alter"}\n')
        self.assertFalse(self.profile.exists())
        self.assertFalse(self.skill.exists())

    def test_modified_skill_is_kept_but_prompt_is_closed(self) -> None:
        self.write_config()
        self.install()
        local_edit = "Locally edited Skill.\n"
        (self.skill / "SKILL.md").write_text(local_edit, encoding="utf-8")
        result, output = self.run_cli("--uninstall")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output["status"], "partial")
        self.assertEqual(output["completed_components"], ["prompt"])
        self.assertEqual(output["failed_component"], "skill")
        self.assertEqual(self.config.read_text(encoding="utf-8"), CONFIG)
        self.assertFalse(self.profile.exists())
        self.assertFalse((self.codex / PROMPT_STATE).exists())
        self.assertEqual((self.skill / "SKILL.md").read_text(encoding="utf-8"), local_edit)

    def test_doctor_is_read_only_and_reports_source_hashes(self) -> None:
        for installed in (False, True):
            with self.subTest(installed=installed):
                if installed:
                    self.install()
                before = snapshot(self.root)
                result, output = self.run_cli("--doctor")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(snapshot(self.root), before)
                self.assertEqual(output["prompt_enabled"], installed)
                self.assertEqual(output["skill_installed"], installed)
                self.assertEqual(output["source_hashes"]["prompt_sha256"], hashlib.sha256(FIXTURE.encode("utf-8")).hexdigest())
                self.assertEqual(output["source_hashes"]["skill_files_sha256"]["SKILL.md"], hashlib.sha256((self.skill_source / "SKILL.md").read_bytes()).hexdigest())
                self.assertFalse(output["model_tested"])

    def test_uninstall_dry_run_preserves_both(self) -> None:
        self.install()
        before = snapshot(self.root)
        result, output = self.run_cli("--uninstall", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output["status"], "dry_run")
        self.assertEqual(snapshot(self.root), before)

    def test_actual_second_component_failure_reports_completed_prompt_and_recovery(self) -> None:
        fake = self.repo / "tools" / "manage_skill.py"
        fake.write_text(
            "import json, sys\n"
            "preview = '--dry-run' in sys.argv\n"
            "print(json.dumps({'status': 'dry_run' if preview else 'error', 'error': 'Fixture failure'}))\n"
            "raise SystemExit(0 if preview else 1)\n", encoding="utf-8"
        )
        result, output = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output["status"], "partial")
        self.assertEqual(output["completed_components"], ["prompt"])
        self.assertEqual(output["failed_component"], "skill")
        self.assertTrue(self.profile.exists())
        self.assertTrue((self.codex / PROMPT_STATE).exists())
        self.assertFalse(self.skill.exists())
        self.assertGreaterEqual(len(output["recovery_commands"]), 2)
        for recovery in output["recovery_commands"]:
            self.assertIn(str(self.codex), recovery["argv"])

    def test_invalid_child_output_is_not_echoed(self) -> None:
        (self.repo / "tools" / "manage_prompt.py").write_text(
            "import sys\nprint('fixture-sensitive-config')\nprint('fixture-sensitive-auth', file=sys.stderr)\nraise SystemExit(1)\n", encoding="utf-8"
        )
        before = snapshot(self.root)
        result, output = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("fixture-sensitive", result.stdout + result.stderr)
        self.assertEqual(output["completed_components"], [])
        self.assertEqual(snapshot(self.root), before)


if __name__ == "__main__":
    unittest.main()
