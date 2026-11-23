import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bootstrap


class BootstrapTests(unittest.TestCase):
    def test_existing_install_is_not_overwritten(self):
        with patch.object(bootstrap, 'pygame_ready', return_value=True), patch.object(bootstrap, 'install_bundle') as install:
            bootstrap.ensure_dependencies(Path('.'))
            install.assert_not_called()

    def test_missing_or_corrupt_bundle_fails_without_writing_vendor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(RuntimeError):
                bootstrap.install_bundle(root)
            folder = root / 'dependencies'
            folder.mkdir()
            (folder / bootstrap.BUNDLE).write_bytes(b'incomplete')
            with self.assertRaises(RuntimeError):
                bootstrap.install_bundle(root)
            self.assertFalse((root / '.vendor').exists())

    def test_bundle_cannot_extract_outside_vendor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'dependencies').mkdir()
            bundle = root / 'dependencies' / bootstrap.BUNDLE
            with zipfile.ZipFile(bundle, 'w') as archive:
                archive.writestr('pygame/../../outside.txt', 'invalid')
            digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
            with patch.object(bootstrap, 'BUNDLE_SHA256', digest), self.assertRaises(RuntimeError):
                bootstrap.install_bundle(root)
            self.assertFalse((root / 'outside.txt').exists())
            self.assertFalse((root / '.vendor').exists())

    def test_failed_import_after_setup_reports_failure(self):
        with patch.object(bootstrap, 'pygame_ready', return_value=False), patch.object(bootstrap, 'install_bundle') as install:
            with self.assertRaises(RuntimeError):
                bootstrap.ensure_dependencies(Path('.'))
            install.assert_called_once()
