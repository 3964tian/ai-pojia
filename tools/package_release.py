#!/usr/bin/env python3
"""Build a reproducible source ZIP using an explicit, public-file allowlist."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "plugin.json", ".gitignore", "install.py",
    "tools/manage_skill.py", "tools/manage_prompt.py", "tools/package_release.py",
    "tests/test_manage_skill.py", "tests/test_manage_prompt.py", "tests/test_install.py",
    "docs/validation.md", "demos/README.md", "prompts/ai-pojia.md", "prompts/README.md", "prompts/source.json",
    "third_party/gpt-instruct/LICENSE", "third_party/gpt-instruct/source.json",
    "skills/ai-pojia/SKILL.md", "skills/ai-pojia/agents/openai.yaml",
    "skills/ai-pojia/references/demo-contract.md",
)


def release_files(root: Path) -> list[Path]:
    paths = [root / name for name in FILES]
    for path in paths:
        relative = path.relative_to(root)
        components = [root.joinpath(*relative.parts[:index]) for index in range(1, len(relative.parts) + 1)]
        if not path.is_file() or any(p.is_symlink() for p in components):
            raise ValueError(f"missing or symlinked release file: {relative}")
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def build(output_dir: Path) -> dict[str, object]:
    files = release_files(ROOT)
    metadata = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    name, version = metadata["name"], metadata["version"]
    if name != "ai-pojia" or not isinstance(version, str) or not version or any(c not in "0123456789.-abcdefghijklmnopqrstuvwxyz" for c in version):
        raise ValueError("invalid release identity")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{name}-v{version}.zip"
    descriptor, temp_name = tempfile.mkstemp(prefix=".ai-pojia-", suffix=".zip", dir=output_dir)
    os.close(descriptor)
    temporary = Path(temp_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in files:
                item = zipfile.ZipInfo(f"{name}/{path.relative_to(ROOT).as_posix()}", date_time=(1980, 1, 1, 0, 0, 0))
                item.create_system = 3
                item.external_attr = 0o100644 << 16
                item.compress_type = zipfile.ZIP_DEFLATED
                bundle.writestr(item, path.read_bytes())
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = archive.with_suffix(archive.suffix + ".sha256")
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return {"archive": str(archive.resolve()), "sha256": digest, "files": len(files)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.output_dir), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        parser.exit(1, f"Packaging failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
