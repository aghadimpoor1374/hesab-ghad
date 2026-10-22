"""Signed offline licenses. The signing private key must never ship with the app."""
import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def decode(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def verify(code, public_key):
    try:
        prefix, payload, signature = code.strip().split('.')
        if prefix != 'HG1':
            raise ValueError()
        Ed25519PublicKey.from_public_bytes(decode(public_key.strip())).verify(
            decode(signature), payload.encode('ascii'))
        data = json.loads(decode(payload))
        if data['days'] not in (20, 365) or not isinstance(data['id'], str):
            raise ValueError()
        return data
    except Exception as error:
        raise ValueError('کد لایسنس معتبر نیست.') from error


def activate(code, public_key, state=None, timestamp=None):
    data = verify(code, public_key)
    timestamp = timestamp if timestamp is not None else int(datetime.now(timezone.utc).timestamp())
    state = dict(state or {})
    code = code.strip()
    used = dict(state.get('used_codes', {}))
    if state and timestamp < state['last_seen'] - 300:
        raise ValueError('تاریخ دستگاه عقب رفته است؛ تاریخ را اصلاح کنید.')
    if state and state.get('code') != code:
        previous = verify(state['code'], public_key)
        used[previous['id']] = state['expires']
        if data['id'] in used:
            raise ValueError('این کد قبلاً استفاده شده است.')
        # Renewals extend remaining time; switching codes cannot discard paid days.
        started = max(timestamp, state['expires'])
        state = dict(code=code, started=started,
                     expires=started + data['days'] * 86400,
                     last_seen=timestamp, used_codes=used)
    if not state:
        state = dict(code=code, started=timestamp,
                     expires=timestamp + data['days'] * 86400, last_seen=timestamp,
                     used_codes={})
    if timestamp < state['last_seen'] - 300:
        raise ValueError('تاریخ دستگاه عقب رفته است؛ تاریخ را اصلاح کنید.')
    if timestamp >= state['expires']:
        raise ValueError('اعتبار لایسنس پایان یافته است؛ برای تمدید تماس بگیرید.')
    state['last_seen'] = max(timestamp, state['last_seen'])
    return state


def check_license(folder, parent=None, renew=False):
    import tkinter as tk
    from tkinter import messagebox, simpledialog
    root = parent or tk.Tk()
    if parent is None:
        root.withdraw()
    try:
        public = Path(__file__).with_name('license-public.key').read_text().strip()
        path = Path(folder) / 'offline-license.json'
        state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        code = state['code'] if state else None
        if state and not renew:
            try:
                activate(code, public, state)
            except ValueError as error:
                messagebox.showwarning('اعتبار لایسنس', str(error), parent=root)
                renew = True
        if not state or renew:
            code = simpledialog.askstring(
                'فعال‌سازی / تمدید آفلاین',
                'کد جدید را از اکسل کپی کنید.\nلغو: خروج از برنامه؛ اطلاعات ذخیره‌شده محفوظ می‌ماند.', parent=root)
        if not code:
            return False
        state = activate(code, public, state)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state), encoding='utf-8')
        temporary.replace(path)
        return True
    except Exception as error:
        messagebox.showerror('لایسنس', str(error) + '\nاطلاعات حسابداری حذف نشده است.', parent=root)
        return False
    finally:
        if parent is None:
            root.destroy()


def install_monitor(root, folder, on_expired=None):
    """Recheck using Tk's event loop, not an unsafe background GUI thread."""
    def tick():
        if not check_license(folder, parent=root):
            (on_expired or root.destroy)()
            return
        root.after(60000, tick)
    root.after(60000, tick)

    def renew():
        check_license(folder, parent=root, renew=True)

    import tkinter as tk
    tk.Button(root, text='تمدید لایسنس آفلاین', command=renew).pack(side='bottom')
    return renew
