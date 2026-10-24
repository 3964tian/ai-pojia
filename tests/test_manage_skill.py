"""Exercise the public installer CLI using disposable clients and skill payloads.

These checks never install into the current user's skill or configuration paths.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = PROJECT_ROOT / "tools" / "manage_skill.py"
MARKER = ".ai-pojia-install.json"


def snapshot(root: Path) -> dict[str, tuple[str, bytes | str]]:
    """Include empty directories and links, so failed operations cannot hide writes."""
    if not root.exists() and not root.is_symlink():
        return {}
    result: dict[str, tuple[str, bytes | str]] = {}
    for entry in [root, *root.rglob("*")]:
        relative = "." if entry == root else entry.relative_to(root).as_posix()
        if entry.is_symlink():
            result[relative] = ("link", os.readlink(entry))
        elif entry.is_dir():
            result[relative] = ("directory", "")
        else:
            result[relative] = ("file", entry.read_bytes())
    return result


class ManageSkillCLITest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ai-pojia-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repository"
        self.script = self.repo / "tools" / "manage_skill.py"
        self.script.parent.mkdir(parents=True)
        shutil.copy2(INSTALLER, self.script)
        self.source = self.repo / "skills" / "ai-pojia"
        self.payload = {
            "SKILL.md": (
                "---\nname: ai-pojia\n"
                "description: Analyze and verify user-owned demo projects.\n"
                "---\n\n# AI破甲\n\nInspect the supplied demo and report evidence.\n"
            ).encode("utf-8"),
            "references/workflow.md": b"Inspect, copy, change, and verify the demo.\n",
            "assets/示例.txt": "本地演示输入。\n".encode("utf-8"),
        }
        for name, content in self.payload.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        (self.repo / "plugin.json").write_text(
            json.dumps({"name": "ai-pojia", "version": "0.1.0"}), encoding="utf-8"
        )
        self.skills_dir = self.root / "client" / "skills"
        self.target = self.skills_dir / "ai-pojia"

    def run_cli(self, command: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(self.script),
                command,
                "--skills-dir",
                str(self.skills_dir),
                "--json",
                *arguments,
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def assert_success(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIsInstance(json.loads(result.stdout), dict)

    def install(self) -> None:
        self.assert_success(self.run_cli("install"))

    def archives(self) -> list[Path]:
        directory = self.skills_dir / ".ai-pojia-backups"
        return sorted(directory.iterdir()) if directory.exists() else []

    def assert_payload(self, directory: Path, expected: dict[str, bytes]) -> None:
        for name, content in expected.items():
            self.assertEqual((directory / name).read_bytes(), content, name)

    def assert_modification_is_preserved(self) -> None:
        before = snapshot(self.root)
        for command in ("install", "uninstall"):
            with self.subTest(command=command):
                result = self.run_cli(command)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(snapshot(self.root), before)

    def make_symlink(self, link: Path, target: Path, *, directory: bool = False) -> None:
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"Symlinks are unavailable: {error}")

    def test_install_dry_run_does_not_create_destination_or_state(self) -> None:
        before = snapshot(self.root)
        self.assert_success(self.run_cli("install", "--dry-run"))
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(self.skills_dir.exists())

    def test_first_install_copies_the_complete_payload(self) -> None:
        self.install()
        self.assert_payload(self.target, self.payload)
        self.assertTrue((self.target / MARKER).is_file())
        installed = {
            path.relative_to(self.target).as_posix()
            for path in self.target.rglob("*")
            if path.is_file()
        }
        self.assertEqual(installed, {*self.payload, MARKER})

    def test_repeated_install_is_idempotent(self) -> None:
        self.install()
        before = snapshot(self.skills_dir)
        self.assert_success(self.run_cli("install"))
        self.assertEqual(snapshot(self.skills_dir), before)
        self.assertEqual(self.archives(), [])

    def test_update_installs_new_files_and_archives_the_old_payload(self) -> None:
        self.install()
        updated = {**self.payload, "references/new-case.md": b"A newly added case.\n"}
        updated["references/workflow.md"] = b"Updated workflow.\n"
        for name, content in updated.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.assert_success(self.run_cli("install"))
        self.assert_payload(self.target, updated)
        archives = self.archives()
        self.assertEqual(len(archives), 1)
        self.assert_payload(archives[0], self.payload)
        self.assertFalse((archives[0] / "references/new-case.md").exists())

    def test_update_dry_run_preserves_installed_files_and_backups(self) -> None:
        self.install()
        (self.source / "references/workflow.md").write_text("New source.\n", encoding="utf-8")
        before = snapshot(self.root)
        self.assert_success(self.run_cli("install", "--dry-run"))
        self.assertEqual(snapshot(self.root), before)

    def test_edited_installed_file_blocks_update_and_uninstall(self) -> None:
        self.install()
        (self.target / "references/workflow.md").write_text("My local edits.\n", encoding="utf-8")
        self.assert_modification_is_preserved()

    def test_untracked_installed_file_blocks_update_and_uninstall(self) -> None:
        self.install()
        (self.target / "my-notes.txt").write_text("Keep my notes.\n", encoding="utf-8")
        self.assert_modification_is_preserved()

    def test_missing_installed_file_blocks_update_and_uninstall(self) -> None:
        self.install()
        (self.target / "references/workflow.md").unlink()
        self.assert_modification_is_preserved()

    def test_unmanaged_destination_is_not_overwritten_or_removed(self) -> None:
        self.target.mkdir(parents=True)
        (self.target / "SKILL.md").write_text("An unrelated existing skill.\n", encoding="utf-8")
        self.assert_modification_is_preserved()

    def test_invalid_json_marker_blocks_update_and_uninstall(self) -> None:
        self.install()
        (self.target / MARKER).write_text("{this is not valid json", encoding="utf-8")
        self.assert_modification_is_preserved()

    def test_wrong_marker_shape_blocks_update_and_uninstall(self) -> None:
        self.install()
        (self.target / MARKER).write_text("[]\n", encoding="utf-8")
        self.assert_modification_is_preserved()

    def test_source_file_symlink_is_rejected_without_following_it(self) -> None:
        external = self.root / "external-source.txt"
        external.write_text("Not a bundled asset.\n", encoding="utf-8")
        self.make_symlink(self.source / "references/external.txt", external)
        before = snapshot(self.root)
        result = self.run_cli("install")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(snapshot(self.root), before)

    def test_source_directory_symlink_is_rejected(self) -> None:
        original = self.source.with_name("real-payload")
        self.source.rename(original)
        self.make_symlink(self.source, original, directory=True)
        before = snapshot(self.root)
        result = self.run_cli("install")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(snapshot(self.root), before)

    def test_destination_symlink_is_not_followed(self) -> None:
        external = self.root / "unrelated-skill"
        external.mkdir()
        (external / "notes.txt").write_text("Keep this directory.\n", encoding="utf-8")
        self.skills_dir.mkdir(parents=True)
        self.make_symlink(self.target, external, directory=True)
        self.assert_modification_is_preserved()

    def test_marker_symlink_is_not_followed(self) -> None:
        self.install()
        marker = self.target / MARKER
        external = self.root / "external-marker.json"
        external.write_bytes(marker.read_bytes())
        marker.unlink()
        self.make_symlink(marker, external)
        self.assert_modification_is_preserved()

    def test_install_and_uninstall_preserve_client_configuration(self) -> None:
        client = self.skills_dir.parent
        client.mkdir(parents=True)
        expected = {
            "config.toml": b'model = "example-model"\nprovider = "user-choice"\n',
            "auth.json": b'{"example": "fixture-only"}\n',
        }
        for name, content in expected.items():
            (client / name).write_bytes(content)
        self.install()
        self.assert_success(self.run_cli("uninstall"))
        for name, content in expected.items():
            self.assertEqual((client / name).read_bytes(), content)

    def test_uninstall_archives_the_complete_install(self) -> None:
        self.install()
        self.assert_success(self.run_cli("uninstall"))
        self.assertFalse(self.target.exists())
        archives = self.archives()
        self.assertEqual(len(archives), 1)
        self.assert_payload(archives[0], self.payload)
        self.assertTrue((archives[0] / MARKER).is_file())

    def test_uninstall_dry_run_preserves_the_complete_install(self) -> None:
        self.install()
        before = snapshot(self.root)
        self.assert_success(self.run_cli("uninstall", "--dry-run"))
        self.assertEqual(snapshot(self.root), before)

    def test_doctor_is_read_only_when_missing_or_installed(self) -> None:
        before = snapshot(self.root)
        self.assert_success(self.run_cli("doctor"))
        self.assertEqual(snapshot(self.root), before)
        self.install()
        before = snapshot(self.root)
        self.assert_success(self.run_cli("doctor"))
        self.assertEqual(snapshot(self.root), before)


if __name__ == "__main__":
    unittest.main()
