from contextlib import closing
from unittest.mock import patch
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from zipfile import ZipFile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

base = Path(__file__).parent
source = base / 'windows-installer-kit/source/desktop_update.py'
if not source.exists():
    source = base / 'source/desktop_update.py'
spec = importlib.util.spec_from_file_location('desktop_update', source)
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = Ed25519PrivateKey.generate()
        self.public = base64.b64encode(self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()

    def package(self, *, body=b'MZ-test', signed_body=None, version='1.1.0', minimum='1.0.0', extra=None, key=None):
        signed_body = body if signed_body is None else signed_body
        manifest = json.dumps(dict(kind='hesab-ghadim-windows-update-v1', platform=('windows-x64' if update.sys.maxsize > 2**32 else 'windows-x86'), version=version,
                                   minimum_version=minimum, size=len(signed_body), sha256=hashlib.sha256(signed_body).hexdigest())).encode()
        path = self.root / 'test.hgu'
        with ZipFile(path, 'w') as archive:
            archive.writestr('manifest.json', manifest)
            archive.writestr('signature.txt', base64.b64encode((key or self.key).sign(manifest)))
            archive.writestr('installer.exe', body)
            if extra:
                archive.writestr(extra, b'bad')
        return path

    def test_valid_package_and_stage(self):
        path = self.package()
        installer, manifest = update.stage_package(path, self.public, self.root / 'updates')
        self.assertEqual(installer.read_bytes(), b'MZ-test')
        self.assertEqual(manifest['version'], '1.1.0')

    def test_unsigned_or_wrong_publisher_rejected(self):
        with self.assertRaises(Exception):
            update.verify_package(self.package(key=Ed25519PrivateKey.generate()), self.public)

    def test_tampered_installer_rejected(self):
        with self.assertRaises(ValueError):
            update.verify_package(self.package(body=b'MZ-evil', signed_body=b'MZ-test'), self.public)

    def test_old_and_equal_versions_rejected(self):
        for value in ['0.9.0', '1.0.0']:
            with self.assertRaises(ValueError):
                update.verify_package(self.package(version=value), self.public)

    def test_minimum_version(self):
        with self.assertRaises(ValueError):
            update.verify_package(self.package(minimum='1.0.1'), self.public)

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            update.verify_package(self.package(extra='../evil.exe'), self.public)
        self.assertFalse((self.root.parent / 'evil.exe').exists())

    def test_failed_stage_cleaned(self):
        dest = self.root / 'updates'
        with self.assertRaises(ValueError):
            update.stage_package(self.package(extra='evil'), self.public, dest)
        self.assertEqual(list(dest.iterdir()), [])

    def test_backup_includes_wal_records_attachments_license(self):
        folder = self.root / 'data'
        folder.mkdir()
        db = sqlite3.connect(folder / 'gold_accounting.sqlite3')
        self.addCleanup(db.close)
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE records (name TEXT)')
        db.execute("INSERT INTO records VALUES ('customer')")
        db.commit()
        (folder / 'attachments').mkdir()
        (folder / 'attachments/invoice.txt').write_text('invoice')
        (folder / 'offline-license.json').write_text('{"code":"keep"}')
        target = self.root / 'backups/test.zip'
        update.backup_data(folder, target)
        with ZipFile(target) as archive:
            self.assertEqual(archive.read('offline-license.json'), b'{"code":"keep"}')
            self.assertEqual(archive.read('attachments/invoice.txt'), b'invoice')
            restored = self.root / 'restored.sqlite3'
            restored.write_bytes(archive.read('gold_accounting.sqlite3'))
        with closing(sqlite3.connect(restored)) as conn:
            self.assertEqual(conn.execute('SELECT name FROM records').fetchone()[0], 'customer')
        self.assertEqual(db.execute('SELECT COUNT(*) FROM records').fetchone()[0], 1)

    def test_backup_closes_both_database_connections(self):
        folder = self.root / 'data'
        folder.mkdir()
        with closing(sqlite3.connect(folder / 'gold_accounting.sqlite3')) as conn:
            conn.execute('CREATE TABLE records (name TEXT)')
            conn.commit()
        connect = sqlite3.connect
        opened = []

        def tracked_connect(*args, **kwargs):
            connection = connect(*args, **kwargs)
            opened.append(connection)
            return connection

        with patch.object(update.sqlite3, 'connect', side_effect=tracked_connect):
            update.backup_data(folder, self.root / 'backup.zip')
        self.assertEqual(len(opened), 2)
        for connection in opened:
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute('SELECT 1')

    def test_backup_cannot_be_inside_data(self):
        folder = self.root / 'data'
        folder.mkdir()
        with self.assertRaises(ValueError):
            update.backup_data(folder, folder / 'backup.zip')

    def test_backup_preserves_existing_file(self):
        folder = self.root / 'data'
        folder.mkdir()
        destination = self.root / 'old.zip'
        destination.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):
            update.backup_data(folder, destination)
        self.assertEqual(destination.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
