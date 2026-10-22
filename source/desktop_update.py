"""Offline, signed full-installer updates. Never load Python/plugins from packages."""
from contextlib import closing
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from zipfile import ZipFile, ZIP_DEFLATED
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

CURRENT_VERSION = '1.0.0'
MAX_INSTALLER = 1024 * 1024 * 1024


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,6}\.\d{1,6}\.\d{1,6}', value):
        raise ValueError('شماره نسخه نامعتبر است.')
    return tuple(map(int, value.split('.')))


def verify_package(package, public_key, current=CURRENT_VERSION):
    with ZipFile(package) as archive:
        names = archive.namelist()
        if sorted(names) != ['installer.exe', 'manifest.json', 'signature.txt']:
            raise ValueError('ساختار بسته معتبر نیست.')
        if archive.getinfo('manifest.json').file_size > 8192 or archive.getinfo('signature.txt').file_size > 256:
            raise ValueError('بسته بیش از اندازه مجاز است.')
        payload = archive.read('manifest.json')
        signature = base64.b64decode(archive.read('signature.txt'), validate=True)
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key)).verify(signature, payload)
        manifest = json.loads(payload)
        if manifest.get('kind') != 'hesab-ghadim-windows-update-v1':
            raise ValueError('این بسته مخصوص حساب قدیم نیست.')
        target_platform = 'windows-x64' if sys.maxsize > 2**32 else 'windows-x86'
        if manifest.get('platform') != target_platform:
            raise ValueError('بسته برای این سیستم مناسب نیست.')
        if version(manifest['version']) <= version(current):
            raise ValueError('نسخه بسته باید جدیدتر از نسخه فعلی باشد.')
        if version(current) < version(manifest['minimum_version']):
            raise ValueError('ابتدا نسخه واسط موردنیاز را نصب کنید.')
        size = archive.getinfo('installer.exe').file_size
        if not 0 < size <= MAX_INSTALLER or size != manifest.get('size'):
            raise ValueError('حجم نصب‌کننده معتبر نیست.')
        digest = hashlib.sha256()
        with archive.open('installer.exe') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        if digest.hexdigest() != manifest.get('sha256'):
            raise ValueError('فایل نصب خراب یا دست‌کاری شده است.')
        return manifest


def stage_package(package, public_key, updates, current=CURRENT_VERSION):
    # Hold an immutable local copy so a selected source cannot change after verification.
    updates = Path(updates)
    updates.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='update-', dir=updates))
    try:
        local = stage / 'package.hgu'
        if Path(package).stat().st_size > MAX_INSTALLER + 1024 * 1024:
            raise ValueError('بسته بیش از اندازه مجاز است.')
        shutil.copyfile(package, local)
        manifest = verify_package(local, public_key, current)
        installer = stage / 'installer.exe'
        with ZipFile(local) as archive, archive.open('installer.exe') as source, installer.open('xb') as target:
            shutil.copyfileobj(source, target)
        return installer, manifest
    except Exception:
        shutil.rmtree(stage)
        raise


def backup_data(folder, destination):
    folder, destination = Path(folder).resolve(), Path(destination).resolve()
    if destination == folder or folder in destination.parents:
        raise ValueError('مسیر پشتیبان باید بیرون پوشه اطلاعات باشد.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    db = folder / 'gold_accounting.sqlite3'
    temporary = destination.with_suffix('.tmp')
    try:
        with tempfile.TemporaryDirectory() as temp:
            snapshot = Path(temp) / db.name
            if db.exists():
                # SQLite's context manager commits/rolls back, but does not close
                # connections. Close both handles before archiving/cleanup on Windows.
                with closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)) as source, closing(sqlite3.connect(snapshot)) as target:
                    source.backup(target)
                    if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('بررسی سلامت دیتابیس ناموفق بود؛ نصب متوقف شد.')
            with ZipFile(temporary, 'x', ZIP_DEFLATED) as archive:
                for path in folder.rglob('*'):
                    if path.is_symlink():
                        raise ValueError('پیوند نمادین در اطلاعات؛ پشتیبان‌گیری متوقف شد.')
                    if not path.is_file() or path.name in {db.name, db.name + '-wal', db.name + '-shm', db.name + '-journal'}:
                        continue
                    archive.write(path, path.relative_to(folder).as_posix())
                if snapshot.exists():
                    archive.write(snapshot, db.name)
        with ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError('آزمایش پشتیبان ناموفق بود.')
        if destination.exists():
            raise FileExistsError(destination)
        temporary.replace(destination)
        return destination
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def install_ui(root, folder, close):
    import tkinter as tk
    from tkinter import filedialog, messagebox

    def update():
        if os.name != 'nt' or not getattr(sys, 'frozen', False):
            messagebox.showinfo('به‌روزرسانی', 'نصب پکیج فقط در نسخه نصب‌شده ویندوز فعال است.', parent=root)
            return
        selected = filedialog.askopenfilename(parent=root, title='انتخاب بسته امضاشده', filetypes=[('Hesab Ghadim Update', '*.hgu')])
        if not selected:
            return
        try:
            home = Path(folder).parent
            public = Path(__file__).with_name('update-public.key').read_text().strip()
            installer, manifest = stage_package(selected, public, home / 'updates')
            if not messagebox.askyesno('نصب نسخه جدید',
                    f"نسخه فعلی: {CURRENT_VERSION}\nنسخه جدید: {manifest['version']}\n"
                    'فرم‌های ثبت‌نشده را ابتدا ذخیره کنید. برنامه بسته خواهد شد.\nادامه و پشتیبان‌گیری؟', parent=root):
                return
            stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
            backup = home / 'update-backups' / stamp
            backup.mkdir(parents=True)
            # Preserve the old executable tree for manual application rollback.
            app = Path(sys.executable).resolve().parent
            if app == home or app in home.parents or home in app.parents:
                raise ValueError('مسیر نصب و اطلاعات از هم جدا نیستند؛ نصب متوقف شد.')
            shutil.copytree(app, backup / 'previous-app')
            backup_data(folder, backup / 'accounting-and-license.zip')
            (backup / 'README.txt').write_text(
                'Before restoring, close the app and copy current data elsewhere.\n'
                'previous-app contains the prior application for manual rollback.\n'
                'Do not run it against a newer database schema. Restore the matching snapshot only after copying current data elsewhere.\n'
                'accounting-and-license.zip contains pre-update data, attachments and license.\n'
                'Do not overwrite current data without a separate copy: newer entries would be lost.\n', encoding='utf-8')
            if not messagebox.askyesno('پشتیبان آماده است',
                    f'پشتیبان:\n{backup}\nنصب‌کننده اجرا شود؟', parent=root):
                return
            if close() is not True:
                return
            try:
                subprocess.Popen([str(installer), '/LOG=' + str(backup / 'installer.log')], cwd=installer.parent)
            except OSError as error:
                # Tk root has closed; show a standalone error without changing data.
                messagebox.showerror('اجرای نصب ناموفق بود', f'{error}\nپشتیبان: {backup}')
        except Exception as error:
            messagebox.showerror('به‌روزرسانی متوقف شد', str(error), parent=root)

    def show_backups():
        directory = Path(folder).parent / 'update-backups'
        directory.mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            os.startfile(str(directory))
        else:
            messagebox.showinfo('پشتیبان‌های به‌روزرسانی', str(directory), parent=root)

    bar = tk.Frame(root)
    bar.pack(side='bottom', fill='x')
    tk.Button(bar, text='به‌روزرسانی / نصب پکیج جدید', command=update).pack(side='right')
    tk.Button(bar, text='پشتیبان‌های قبل از به‌روزرسانی', command=show_backups).pack(side='right')
