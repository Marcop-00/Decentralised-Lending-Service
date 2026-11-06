"""Safety checks for source packaging; standard library only, no real secrets."""

import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile


spec = importlib.util.spec_from_file_location(
    "prepare_submission", Path(__file__).resolve().parents[1] / "prepare_submission.py")
packaging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packaging)


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "project"
        for relative in packaging.ROOT_FILES:
            self.put(relative)
        self.put(packaging.LAB_KEYSTORE, json.dumps({"address": packaging.LAB_ADDRESS}))
        for stem in ("report", "report-it"):
            self.put(f"docs/{stem}.pdf", f"{stem} PDF fixture\n")
            self.put(f"docs/{stem}.tex")
        for relative in ("contracts/Pool.sol", "contracts/test/Attacker.sol",
                         "test/helpers/deploy.ts", "python/oracle/service.py",
                         "scripts/prepare_submission.py"):
            self.put(relative)

    def put(self, relative, text="test fixture\n"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def build(self, language="it", output="output"):
        return packaging.build_submission(self.root, self.base / output, language)

    def test_only_selected_report_and_all_source_trees(self):
        for language, selected, omitted in (("it", "report-it", "report"),
                                            ("en", "report", "report-it")):
            with self.subTest(language=language):
                files = packaging.collect_files(self.root, language)
                self.assertIn(f"docs/{selected}.pdf", files)
                self.assertNotIn(f"docs/{omitted}.pdf", files)
                for source in ("contracts/test/Attacker.sol", "test/helpers/deploy.ts",
                               "python/oracle/service.py"):
                    self.assertIn(source, files)
                folder, _ = self.build(language=language, output=language)
                self.assertEqual(list((folder / "docs").iterdir()), [folder / "docs/report.pdf"])
                self.assertEqual((folder / "docs/report.pdf").read_bytes(),
                                 (self.root / f"docs/{selected}.pdf").read_bytes())

    def test_command_defaults_to_english(self):
        output = self.base / "default-output"
        with patch.object(packaging, "PROJECT_ROOT", self.root), \
                patch("sys.argv", ["prepare_submission.py", "--output-dir", str(output)]), \
                patch("builtins.print"):
            packaging.main()
        folder = output / "Decentralised-Lending-Service-683674-en"
        self.assertEqual((folder / "docs/report.pdf").read_bytes(),
                         (self.root / "docs/report.pdf").read_bytes())

    def test_local_files_and_extra_keystores_are_excluded(self):
        excluded = ("python/.env", "python/oracle/.env", "python/.env-backup",
                    "python/voter/events-local.sqlite3", "python/__pycache__/x.pyc",
                    "python/__pycache__/cached.py", "python/.env-backup.py",
                    "python/.venv/site-packages/library.py", "scripts/venv/library.py",
                    "private-chain/data/secret", "private-chain/keystore/UTC--personal",
                    "bitcoin/blk00000.dat", "node_modules/module.js", "artifacts/x.json",
                    "docs/guida-orale.pdf", "docs/report.log", ".git/config",
                    "docs/render_gas_table.py", "docs/gas-measurements.json",
                    "docs/gas-table.tex", "docs/pisa_logo.png", "README.md",
                    "SUBMISSION.md", "MANIFEST.json", ".gitignore", ".gitattributes",
                    "scripts/prepare_submission.py", "scripts/tests/test_packaging.py")
        for path in excluded:
            self.put(path, "DO NOT PACKAGE")
        folder, archive = self.build()
        for path in excluded:
            self.assertFalse((folder / path).exists(), path)
        with ZipFile(archive) as zipped:
            self.assertNotIn(b"DO NOT PACKAGE", b"".join(zipped.read(n) for n in zipped.namelist()))

    def test_archive_contents_and_executable_setup(self):
        folder, archive = self.build()
        for omitted in ("MANIFEST.json", "SUBMISSION.md", "README.md", "scripts"):
            self.assertFalse((folder / omitted).exists(), omitted)
        with ZipFile(archive) as zipped:
            self.assertIsNone(zipped.testzip())
            self.assertEqual(set(zipped.namelist()), {
                folder.name + "/" + path.relative_to(folder).as_posix()
                for path in folder.rglob("*") if path.is_file()})
            self.assertEqual(stat.S_IMODE(zipped.getinfo(folder.name + "/setup.sh").external_attr >> 16), 0o755)
            for entry in zipped.infolist():
                self.assertEqual(zipped.read(entry.filename), (folder.parent / entry.filename).read_bytes())

    def test_build_is_repeatable_and_sources_do_not_change(self):
        original = (self.root / "setup.sh").read_bytes()
        _, first = self.build(output="first")
        _, second = self.build(output="second")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual((self.root / "setup.sh").read_bytes(), original)

    def test_existing_output_is_not_overwritten(self):
        _, archive = self.build()
        before = archive.read_bytes()
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.build()
        self.assertEqual(archive.read_bytes(), before)

    def test_missing_required_file_stops_before_writing(self):
        (self.root / "package-lock.json").unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            self.build()
        self.assertFalse((self.base / "output").exists())

    def test_symbolic_source_and_ancestor_are_rejected(self):
        source = self.root / "contracts/Pool.sol"
        source.unlink()
        source.symlink_to(self.root / "README.md")
        with self.assertRaisesRegex(ValueError, "Symbolic links"):
            self.build()
        source.unlink()
        directory = self.root / "test/helpers"
        directory.rename(self.root / "external-helpers")
        directory.symlink_to(self.root / "external-helpers", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Symbolic links"):
            packaging.checked_source(self.root, "test/helpers/deploy.ts")
        with self.assertRaisesRegex(ValueError, "Symbolic links"):
            self.build()

    def test_unexpected_lab_account_is_rejected(self):
        self.put(packaging.LAB_KEYSTORE, json.dumps({"address": "different-account"}))
        with self.assertRaisesRegex(ValueError, "unexpected address"):
            self.build()

    def test_invalid_language_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "language"):
            self.build(language="other")


if __name__ == "__main__":
    unittest.main()
