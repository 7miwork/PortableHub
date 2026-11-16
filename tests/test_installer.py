"""Tests fuer installer.py und catalog.py (stdlib unittest, keine Extras)."""

import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portablehub import installer, catalog, settings as cfg


def make_zip_bytes(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def file_url(path: Path) -> str:
    return path.as_uri()


class InstallerTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ph-test-"))
        self._patches = [
            mock.patch.object(cfg, "app_root", return_value=self.tmp),
            mock.patch.object(cfg, "data_dir", return_value=self.tmp / "PortableHub"),
            mock.patch.object(cfg, "apps_dir", return_value=self.tmp / "Apps"),
            mock.patch.object(cfg, "tmp_dir", return_value=self.tmp / "PortableHub" / "tmp"),
        ]
        for p in self._patches:
            p.start()
        (self.tmp / "PortableHub").mkdir(parents=True, exist_ok=True)
        (self.tmp / "Apps").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestInstall(InstallerTestBase):
    def _make_app(self, version="1.0.0", files=None, sha=None, url=None):
        if files is None:
            files = {"app.exe": "MZ", "readme.txt": "hi"}
        zpath = self.tmp / f"app-{version}.zip"
        zpath.write_bytes(make_zip_bytes(files))
        import hashlib
        digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
        return {
            "id": "testapp",
            "name": "TestApp",
            "version": version,
            "exe": "app.exe",
            "url": url or file_url(zpath),
            "sha256": sha if sha is not None else digest,
            "size": zpath.stat().st_size,
            "category": "Test",
            "platform": "windows",
        }

    def test_install_fresh(self):
        app = self._make_app()
        entry = installer.install_app(app)
        self.assertEqual(entry["version"], "1.0.0")
        self.assertTrue((self.tmp / "Apps" / "testapp" / "app.exe").exists())
        installed = cfg.load_installed()
        self.assertIn("testapp", installed)

    def test_hash_mismatch_rejected(self):
        app = self._make_app(sha="0" * 64)
        with self.assertRaises(installer.InstallError):
            installer.install_app(app)
        self.assertFalse((self.tmp / "Apps" / "testapp").exists())

    def test_update_preserves_data_dir(self):
        # v1 installieren
        app1 = self._make_app(version="1.0.0", files={"app.exe": "v1", "data/user.txt": "save"})
        installer.install_app(app1)
        # user.txt modifizieren
        (self.tmp / "Apps" / "testapp" / "data" / "user.txt").write_text("modified")
        # v2 aktualisieren
        app2 = self._make_app(version="2.0.0", files={"app.exe": "v2", "data/other.txt": "new"})
        installer.install_app(app2)
        ud = self.tmp / "Apps" / "testapp" / "data"
        self.assertEqual((ud / "user.txt").read_text(), "modified")
        self.assertEqual((ud / "other.txt").read_text(), "new")
        self.assertEqual((self.tmp / "Apps" / "testapp" / "app.exe").read_text(), "v2")
        self.assertEqual(cfg.load_installed()["testapp"]["version"], "2.0.0")

    def test_uninstall(self):
        app = self._make_app()
        installer.install_app(app)
        self.assertTrue(installer.uninstall_app("testapp"))
        self.assertFalse((self.tmp / "Apps" / "testapp").exists())
        self.assertNotIn("testapp", cfg.load_installed())
        self.assertFalse(installer.uninstall_app("testapp"))

    def test_path_traversal_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../evil.txt", "x")
        zpath = self.tmp / "evil.zip"
        zpath.write_bytes(buf.getvalue())
        app = self._make_app(url=file_url(zpath), sha=None)
        app["sha256"] = __import__("hashlib").sha256(zpath.read_bytes()).hexdigest()
        with self.assertRaises(installer.InstallError):
            installer.install_app(app)

    def test_cancel_aborts(self):
        import threading
        app = self._make_app()
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(installer.InstallError):
            installer.install_app(app, cancel=cancel)


class TestCatalog(unittest.TestCase):
    def test_version_compare(self):
        self.assertTrue(catalog.version_newer("2.0.0", "1.9.9"))
        self.assertFalse(catalog.version_newer("1.0.0", "1.0.0"))
        self.assertTrue(catalog.version_newer("1.0.1", "1.0.0"))

    def test_validate_app(self):
        good = {"id": "x", "name": "X", "version": "1", "exe": "a.exe",
                "url": "https://x", "sha256": "ab"}
        self.assertTrue(catalog.validate_app(good))
        bad = dict(good, id="../evil")
        self.assertFalse(catalog.validate_app(bad))
        bad2 = dict(good, platform="amiga")
        self.assertFalse(catalog.validate_app(bad2))

    def test_app_status(self):
        app = {"id": "a", "version": "2.0"}
        self.assertEqual(catalog.app_status(app, {}), "nicht installiert")
        self.assertEqual(catalog.app_status(app, {"a": {"version": "1.0"}}), "update")
        self.assertEqual(catalog.app_status(app, {"a": {"version": "2.0"}}), "installiert")


if __name__ == "__main__":
    unittest.main(verbosity=2)
