"""Build a minimal source submission folder and ZIP using an explicit allowlist.

Uses only Python's standard library. Never installs dependencies, deploys,
reads generated service environments or copies local chain/Bitcoin databases.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import stat
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAB_ADDRESS = "d278d247a52c550508ea2b2c9321d816238fb523"
LAB_KEYSTORE = (
    "private-chain/keystore/"
    "UTC--2026-05-05T14-09-10.723312492Z--" + LAB_ADDRESS
)
ROOT_FILES = (
    "package.json",
    "package-lock.json", "hardhat.config.ts", "tsconfig.json", "setup.sh",
    "python/requirements.txt", "private-chain/project2526genesis.json",
    "private-chain/password.txt", LAB_KEYSTORE,
)
SOURCE_TREES = {"contracts": {".sol"}, "test": {".ts"},
                "python": {".py"}}
IGNORED_SOURCE_DIRS = {"__pycache__", "node_modules", "venv", "artifacts", "cache", "coverage"}


def checked_source(root, relative):
    """Reject symlinks, including symlinked ancestors, rather than dereference."""
    path = root / relative
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ValueError(f"Symbolic links cannot be packaged: {relative}")
    if not path.is_file():
        raise ValueError(f"Required source file is missing: {relative}")
    return path


def collect_files(root, language):
    if language not in ("en", "it"):
        raise ValueError("Report language must be en or it")
    report = "report-it" if language == "it" else "report"
    files = set(ROOT_FILES) | {f"docs/{report}.pdf"}
    for directory, suffixes in SOURCE_TREES.items():
        source = root / directory
        if source.is_symlink() or not source.is_dir():
            raise ValueError(f"Missing source directory or symbolic link: {directory}")
        for path in source.rglob("*"):
            relative_parts = path.relative_to(source).parts
            if any(part.startswith(".") or part in IGNORED_SOURCE_DIRS for part in relative_parts):
                continue
            if path.is_symlink():
                raise ValueError(f"Symbolic links cannot be packaged: {path.relative_to(root)}")
            if path.suffix in suffixes:
                files.add(path.relative_to(root).as_posix())
    for relative in files:
        checked_source(root, relative)
    key = json.loads(checked_source(root, LAB_KEYSTORE).read_text())
    if key.get("address", "").lower().removeprefix("0x") != LAB_ADDRESS:
        raise ValueError("The supplied laboratory keystore has an unexpected address")
    return sorted(files)


def build_submission(root, output, language):
    root, output = Path(root).resolve(), Path(output).resolve()
    files = collect_files(root, language)
    name = f"Decentralised-Lending-Service-683674-{language}"
    folder, archive = output / name, output / f"{name}.zip"
    if folder.exists() or archive.exists() or folder.is_symlink() or archive.is_symlink():
        raise ValueError("Submission output already exists; choose another --output-dir")
    output.mkdir(parents=True, exist_ok=True)
    folder.mkdir()
    report_source = "docs/report-it.pdf" if language == "it" else "docs/report.pdf"
    for relative in files:
        source = checked_source(root, relative)
        # Keep a single, predictable report filename in either language.
        target = folder / ("docs/report.pdf" if relative == report_source else relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o755 if relative == "setup.sh" else 0o644)
    # Stable entry ordering, permissions and timestamps make repeated builds of
    # the same inputs byte-identical. The ZIP has exactly one top-level folder.
    with ZipFile(archive, "x", compression=ZIP_DEFLATED) as zip_file:
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            info = ZipInfo(path.relative_to(output).as_posix(), (2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | stat.S_IMODE(path.stat().st_mode)) << 16
            zip_file.writestr(info, path.read_bytes())
    return folder, archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-language", choices=("en", "it"), default="en")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "submission")
    args = parser.parse_args()
    try:
        folder, archive = build_submission(PROJECT_ROOT, args.output_dir, args.report_language)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Submission not created: {exc}\n")
    print(f"Folder: {folder}")
    print(f"ZIP: {archive}")
    print(f"SHA-256: {hashlib.sha256(archive.read_bytes()).hexdigest()}")
    print("WARNING: check the five-page report limit before uploading; packaging is not approval.")


if __name__ == "__main__":
    main()
