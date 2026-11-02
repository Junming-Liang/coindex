"""Release archives must be repeatable, complete, and version-consistent."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import struct
import tarfile
import tempfile
import unittest
import zipfile

SPEC = importlib.util.spec_from_file_location("coindex_release_tools", Path(__file__).resolve().parents[1] / "scripts/release.py")
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleasePackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "VERSION").write_text("1.10.0\n")

    def tearDown(self):
        self.temp.cleanup()

    def test_single_version_and_monotonic_macos_build_number(self):
        self.assertEqual(release.version(self.root), "1.10.0")
        self.assertGreater(int(release.build_number("1.10.0")), int(release.build_number("1.9.99")))
        for invalid in ("1.10", "v1.10.0", "1.10.0\nprivate", "01.10.0"):
            (self.root / "VERSION").write_text(invalid)
            with self.assertRaises(ValueError):
                release.version(self.root)

    def test_zip_reproducible_despite_mtime_and_preserves_launcher_mode(self):
        source = self.root / "source"
        source.mkdir()
        launcher = source / "coindex"
        launcher.write_text("#!/bin/sh\nexit 0\n")
        launcher.chmod(0o755)
        first, second = self.root / "a.zip", self.root / "b.zip"
        release.write_zip(first, [launcher], source, "coindex")
        os.utime(launcher, (1000000000, 1000000000))
        release.write_zip(second, [launcher], source, "coindex")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with zipfile.ZipFile(first) as archive:
            entry = archive.getinfo("coindex/coindex")
            self.assertEqual((entry.external_attr >> 16) & 0o777, 0o755)

    def test_linux_archive_reproducible_without_host_owner_or_timestamp(self):
        app = self.root / "coindex-linux"
        app.mkdir()
        (app / "coindex").write_text("#!/bin/sh\n")
        (app / "coindex").chmod(0o755)
        first, second = self.root / "a.tar.gz", self.root / "b.tar.gz"
        release.write_tar(first, app)
        os.utime(app / "coindex", (1000000000, 1000000000))
        release.write_tar(second, app)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with tarfile.open(first) as archive:
            entry = archive.getmember("coindex-linux/coindex")
            self.assertEqual((entry.mode, entry.uid, entry.gid, entry.mtime, entry.uname), (0o755, 0, 0, 0, ""))

    def test_symlinks_are_not_followed_into_release_packages(self):
        app = self.root / "app"
        app.mkdir()
        (app / "private-link").symlink_to(self.root / "VERSION")
        with self.assertRaises(ValueError):
            release.archive_files(app)
        with self.assertRaises(ValueError):
            release.write_zip(self.root / "bad.zip", [app / "private-link"], app, "app")

    def test_checksums_require_both_platforms_and_source_and_detect_changes(self):
        names = release.artifact_names("1.10.0")
        (self.root / names[0]).write_bytes(b"macOS")
        with self.assertRaises(ValueError):
            release.checksum_lines(self.root, "1.10.0")
        for name in names[1:]:
            (self.root / name).write_bytes(name.encode())
        before = release.checksum_lines(self.root, "1.10.0")
        self.assertIn(hashlib.sha256(b"macOS").hexdigest() + "  " + names[0], before)
        (self.root / names[0]).write_bytes(b"changed")
        self.assertNotEqual(before, release.checksum_lines(self.root, "1.10.0"))

    def make_release(self):
        names = release.artifact_names("1.10.0")
        self.write_dmg_fixture(self.root / names[3])
        mac = self.root / "coindex.app"
        (mac / "Contents/Resources/backend").mkdir(parents=True)
        (mac / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": "1.10.0"}))
        (mac / "Contents/Resources/release.json").write_text(json.dumps({"version": "1.10.0", "platform": "macos"}))
        (mac / "Contents/Resources/backend/summaries.py").write_text("")
        (mac / "Contents/Resources/backend/taskmap.py").write_text("")
        (mac / "Contents/Resources/backend/updates.py").write_text("")
        release.write_zip(self.root / names[0], release.archive_files(mac), mac, mac.name)
        linux = self.root / "coindex-linux"
        (linux / "backend").mkdir(parents=True)
        (linux / "scripts").mkdir()
        (linux / "linux").mkdir()
        (linux / "release.json").write_text(json.dumps({"version": "1.10.0", "platform": "linux"}))
        (linux / "backend/summaries.py").write_text("")
        (linux / "backend/taskmap.py").write_text("")
        (linux / "linux/mindmap.py").write_text("")
        (linux / "backend/updates.py").write_text("")
        (linux / "linux/summaries.py").write_text("")
        (linux / "scripts/install-linux.sh").write_text("")
        release.write_tar(self.root / names[1], linux)
        source = self.root / "source"
        for name in ("Sources/SummaryViews.swift", "Sources/TaskMapViews.swift", "Sources/UpdateViews.swift", "backend/summaries.py", "backend/taskmap.py", "backend/updates.py", "linux/app.py", "linux/summaries.py", "linux/mindmap.py", "scripts/build.sh", "VERSION"):
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("1.10.0\n" if name == "VERSION" else "")
        release.write_zip(self.root / names[2], release.archive_files(source), source, "coindex")
        return linux

    def write_dmg_fixture(self, target):
        metadata = plistlib.dumps({"resource-fork": {"blkx": []}})
        footer = bytearray(512)
        struct.pack_into(">4sII", footer, 0, b"koly", 4, 512)
        struct.pack_into(">QQ", footer, 216, 0, len(metadata))
        target.write_bytes(metadata + footer)

    def test_dmg_is_required_and_truncated_or_invalid_containers_are_rejected(self):
        self.make_release()
        image = self.root / "coindex-1.10.0-macos-universal.dmg"
        release.validate_dmg_container(image)
        for data in (b"", b"koly", image.read_bytes()[:-20], b"x" * 1024):
            image.write_bytes(data)
            with self.assertRaises(ValueError):
                release.validate_archives(self.root, "1.10.0")
        image.unlink()
        with self.assertRaises(FileNotFoundError):
            release.validate_archives(self.root, "1.10.0")

    def test_dmg_metadata_must_fit_inside_image(self):
        image = self.root / "invalid.dmg"
        self.write_dmg_fixture(image)
        data = bytearray(image.read_bytes())
        struct.pack_into(">QQ", data, len(data) - 512 + 216, len(data), 4096)
        image.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "metadata bounds"):
            release.validate_dmg_container(image)

    def test_validation_rejects_stale_linux_bundle_among_current_artifacts(self):
        linux = self.make_release()
        release.validate_archives(self.root, "1.10.0")
        (linux / "release.json").write_text(json.dumps({"version": "1.9.0", "platform": "linux"}))
        release.write_tar(self.root / release.artifact_names("1.10.0")[1], linux)
        with self.assertRaisesRegex(ValueError, "Linux archive version"):
            release.validate_archives(self.root, "1.10.0")

    def test_build_replacement_removes_stale_modules_and_preserves_unknown_path(self):
        destination = self.root / "dist/coindex-linux"
        destination.mkdir(parents=True)
        (destination / "coindex").write_text("# Managed by coindex build-linux.sh\n")
        (destination / "obsolete.py").write_text("old")
        stage = self.root / "build/stage/coindex-linux"
        stage.mkdir(parents=True)
        (stage / "coindex").write_text("# Managed by coindex build-linux.sh\n")
        (stage / "new.py").write_text("new")
        release.install_build("linux", stage, destination)
        self.assertFalse((destination / "obsolete.py").exists())
        self.assertTrue((destination / "new.py").exists())
        (destination / "coindex").write_text("unrelated")
        stage.mkdir()
        with self.assertRaises(ValueError):
            release.install_build("linux", stage, destination)
        self.assertEqual((destination / "coindex").read_text(), "unrelated")

    def test_release_notes_require_current_version_section(self):
        (self.root / "CHANGELOG.md").write_text("# Changelog\n\n## 1.10.0 — Unreleased\n\nNew summaries.\n\n## 1.9.0\nOld.\n")
        notes = release.release_notes(self.root)
        self.assertIn("New summaries.", notes)
        self.assertNotIn("Old.", notes)
        self.assertLess(notes.index("macos-universal.dmg"), notes.index("New summaries."))
        self.assertIn("coindex-1.10.0-linux.tar.gz", notes)
        self.assertIn("Source code", notes)
        (self.root / "VERSION").write_text("1.11.0\n")
        with self.assertRaises(ValueError):
            release.release_notes(self.root)


if __name__ == "__main__":
    unittest.main()
