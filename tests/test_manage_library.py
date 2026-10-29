"""Verify the prompt library installer only against temporary fixture roots."""

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
INSTALLER = ROOT / "tools" / "manage_library.py"
STATE = ".ai-pojia-library-state.json"
BACKUPS = ".ai-pojia-library-backups"

FIXTURE_LINES = [
    {
        "id": "line-a", "profile": "prof-a", "family": "fixture", "stage": "stable",
        "label": "Fixture A", "prompt_file": "prompts/library/a.md", "bytes": 0,
        "sha256": "", "archive": "a.zip", "archive_member": "a.md",
        "archive_sha256": "0" * 64, "archive_path": "a.zip",
    },
    {
        "id": "line-b", "profile": "prof-b", "family": "fixture", "stage": "rc",
        "label": "Fixture B", "prompt_file": "prompts/library/b.md", "bytes": 0,
        "sha256": "", "archive": "b.zip", "archive_member": "b.md",
        "archive_sha256": "0" * 64, "archive_path": "b.zip",
    },
]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot(root: Path) -> dict:
    if not root.exists():
        return {}
    output = {}
    for path in [root, *root.rglob("*")]:
        name = "." if path == root else path.relative_to(root).as_posix()
        if path.is_symlink():
            output[name] = ("link", os.readlink(path))
        elif path.is_dir():
            output[name] = ("dir", "")
        else:
            output[name] = ("file", path.read_bytes())
    return output


class ManageLibraryCLITest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="ai-pojia-library-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repository"
        self.script = self.repo / "tools" / "manage_library.py"
        self.script.parent.mkdir(parents=True)
        shutil.copy2(INSTALLER, self.script)
        library = self.repo / "prompts" / "library"
        library.mkdir(parents=True)
        lines = []
        for line, text in zip(FIXTURE_LINES, ("# Fixture prompt A\n", "# Fixture prompt B\n")):
            payload = text.encode("utf-8")
            (self.repo / line["prompt_file"]).write_bytes(payload)
            lines.append(dict(line, bytes=len(payload), sha256=digest(payload)))
        (library / "source.json").write_text(
            json.dumps({"manifest_version": 1, "upstream": {"repository": "fixture"}, "lines": lines},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.codex = self.root / "Codex user data with spaces"
        self.state = self.codex / STATE
        self.backups = self.codex / BACKUPS

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.script), *arguments, "--codex-dir", str(self.codex), "--json"],
            cwd=self.repo, capture_output=True, text=True, timeout=30, check=False,
        )

    def data(self, result: subprocess.CompletedProcess[str]) -> dict:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_install_writes_prompts_profiles_and_state(self) -> None:
        output = self.data(self.run_cli("install"))
        self.assertEqual(output["status"], "installed")
        self.assertEqual(sorted(output["changed"]), ["line-a", "line-b"])
        prompt_a = self.codex / "ai-pojia-line-a.md"
        profile_a = self.codex / "prof-a.config.toml"
        self.assertEqual(prompt_a.read_bytes(), b"# Fixture prompt A\n")
        body = profile_a.read_text(encoding="utf-8")
        self.assertIn('model_instructions_file = "{}"'.format(prompt_a), body)
        self.assertIn("# line:     line-a", body)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(set(state["entries"]), {"line-a", "line-b"})
        self.assertFalse((self.codex / "config.toml").exists())

    def test_install_is_idempotent(self) -> None:
        self.data(self.run_cli("install"))
        before = snapshot(self.codex)
        second = self.data(self.run_cli("install"))
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual(snapshot(self.codex), before)

    def test_dry_run_writes_nothing(self) -> None:
        before = snapshot(self.codex)
        output = self.data(self.run_cli("install", "--dry-run"))
        self.assertEqual(output["status"], "dry_run")
        self.assertEqual(snapshot(self.codex), before)

    def test_doctor_reports_partial_after_tampering(self) -> None:
        self.data(self.run_cli("install"))
        (self.codex / "ai-pojia-line-a.md").write_text("tampered\n", encoding="utf-8")
        result = self.run_cli("doctor")
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "partial")
        statuses = {entry["id"]: entry["status"] for entry in report["entries"]}
        self.assertEqual(statuses["line-a"], "modified")
        self.assertEqual(statuses["line-b"], "installed")

    def test_install_refuses_unmanaged_collision(self) -> None:
        self.codex.mkdir(parents=True)
        (self.codex / "ai-pojia-line-a.md").write_text("# foreign\n", encoding="utf-8")
        before = snapshot(self.codex)
        result = self.run_cli("install")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "error")
        self.assertEqual(snapshot(self.codex), before)

    def test_reinstall_overwrites_own_modified_file(self) -> None:
        self.data(self.run_cli("install"))
        (self.codex / "ai-pojia-line-a.md").write_text("# drifted\n", encoding="utf-8")
        output = self.data(self.run_cli("install"))
        self.assertEqual(output["status"], "installed")
        self.assertEqual((self.codex / "ai-pojia-line-a.md").read_bytes(), b"# Fixture prompt A\n")
        self.assertTrue(self.backups.exists())

    def test_single_line_install(self) -> None:
        output = self.data(self.run_cli("install", "--line", "prof-b"))
        self.assertEqual(output["changed"], ["line-b"])
        self.assertTrue((self.codex / "prof-b.config.toml").exists())
        self.assertFalse((self.codex / "prof-a.config.toml").exists())

    def test_uninstall_removes_only_owned_files(self) -> None:
        self.data(self.run_cli("install"))
        keep = self.codex / "keep-me.txt"
        keep.write_text("user file\n", encoding="utf-8")
        output = self.data(self.run_cli("uninstall"))
        self.assertEqual(output["status"], "removed")
        self.assertFalse((self.codex / "ai-pojia-line-a.md").exists())
        self.assertFalse((self.codex / "prof-a.config.toml").exists())
        self.assertTrue(keep.exists())
        self.assertEqual(json.loads(self.state.read_text(encoding="utf-8"))["entries"], {})

    def test_uninstall_keeps_modified_file_and_reports(self) -> None:
        self.data(self.run_cli("install"))
        drifted = self.codex / "prof-a.config.toml"
        drifted.write_text("# hand edited\n", encoding="utf-8")
        output = self.data(self.run_cli("uninstall"))
        self.assertEqual(output["status"], "removed")
        self.assertTrue(drifted.exists())
        self.assertIn(str(drifted), output["kept"])

    def test_manifest_checksum_mismatch_is_rejected(self) -> None:
        manifest_path = self.repo / "prompts" / "library" / "source.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["lines"][0]["sha256"] = "f" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        before = snapshot(self.codex)
        result = self.run_cli("install")
        self.assertEqual(result.returncode, 1)
        self.assertIn("摘要", json.loads(result.stdout)["error"])
        self.assertEqual(snapshot(self.codex), before)

    def test_dotted_profile_is_rejected(self) -> None:
        manifest_path = self.repo / "prompts" / "library" / "source.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["lines"][0]["profile"] = "gpt-6.1-sol"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.run_cli("install")
        self.assertEqual(result.returncode, 1)
        self.assertIn("profile", json.loads(result.stdout)["error"])

    def test_symlinked_target_is_rejected(self) -> None:
        self.codex.mkdir(parents=True)
        outside = self.root / "outside.md"
        outside.write_text("# outside\n", encoding="utf-8")
        os.symlink(outside, self.codex / "ai-pojia-line-a.md")
        before = snapshot(self.codex)
        result = self.run_cli("install")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(snapshot(self.codex), before)

    def test_human_output_renders_every_command(self) -> None:
        """The non-JSON path must not depend on fields only doctor provides."""
        for arguments in (("install",), ("doctor",), ("list",), ("uninstall",)):
            with self.subTest(command=arguments[0]):
                result = subprocess.run(
                    [sys.executable, str(self.script), *arguments, "--codex-dir", str(self.codex)],
                    cwd=self.repo, capture_output=True, text=True, timeout=30, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_list_reads_manifest_without_writing(self) -> None:
        before = snapshot(self.codex)
        output = self.data(self.run_cli("list"))
        self.assertEqual([entry["id"] for entry in output["entries"]], ["line-a", "line-b"])
        self.assertEqual(snapshot(self.codex), before)


class RepositoryLibraryTest(unittest.TestCase):
    """The shipped library must stay byte-exact against its own manifest."""

    def test_repository_manifest_matches_files(self) -> None:
        manifest = json.loads((ROOT / "prompts" / "library" / "source.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], 1)
        self.assertGreaterEqual(len(manifest["lines"]), 3)
        for line in manifest["lines"]:
            with self.subTest(line=line["id"]):
                payload = (ROOT / line["prompt_file"]).read_bytes()
                self.assertEqual(len(payload), line["bytes"])
                self.assertEqual(digest(payload), line["sha256"])
                self.assertNotIn(".", line["profile"])

    def test_shipped_library_covers_both_rc_lines(self) -> None:
        manifest = json.loads((ROOT / "prompts" / "library" / "source.json").read_text(encoding="utf-8"))
        ids = {line["id"] for line in manifest["lines"]}
        self.assertIn("gpt-5.6-sol-v45", ids)
        self.assertIn("gpt-6-astra-v2-rc1", ids)
        self.assertIn("gpt-6.1-sol-v1-rc2", ids)

    def test_ai_pojia_prompt_is_not_the_raw_v45(self) -> None:
        raw = (ROOT / "prompts" / "library" / "gpt-5.6-sol-v45.md").read_bytes()
        adapted = (ROOT / "prompts" / "ai-pojia.md").read_bytes()
        self.assertNotEqual(digest(raw), digest(adapted))


if __name__ == "__main__":
    unittest.main()
