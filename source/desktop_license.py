"""Online-only desktop license gate. Accounting data is never transmitted."""
import json
import os
from pathlib import Path
import secrets
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlparse


def check_license(folder):
    import tkinter as tk
    from tkinter import messagebox, simpledialog
    root = tk.Tk()
    root.withdraw()
    try:
        config_path = Path(__file__).with_name('license-server.json')
        config = json.loads(config_path.read_text(encoding='utf-8'))
        url = config['url']
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('آدرس HTTPS سرور لایسنس تنظیم نشده است.')
        path = Path(folder) / 'license.json'
        if path.exists():
            state = json.loads(path.read_text(encoding='utf-8'))
        else:
            state = {'device': secrets.token_urlsafe(48)}
        code = state.get('license') or simpledialog.askstring('فعال‌سازی', 'کد لایسنس را وارد کنید:', parent=root)
        if not code:
            return False
        state['license'] = code.strip()
        # Save device identity before contacting server so a timeout cannot strand activation.
        temp = path.with_suffix('.tmp')
        with open(temp, 'w', encoding='utf-8') as output:
            json.dump(state, output)
        os.replace(temp, path)
        request = Request(url.rstrip('/') + '/api/desktop/license',
                          data=json.dumps(state).encode(),
                          headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urlopen(request, timeout=20) as response:
                if urlparse(response.url).scheme != 'https':
                    raise ValueError('پاسخ ناامن سرور.')
                result = json.loads(response.read(8192))
        except HTTPError as error:
            detail = json.loads(error.read(8192))
            raise ValueError(detail.get('error', 'فعال‌سازی ناموفق بود.')) from error
        if result['expires'] <= result['server_time']:
            raise ValueError('اعتبار لایسنس پایان یافته است.')
        temp = path.with_suffix('.tmp')
        with open(temp, 'w', encoding='utf-8') as output:
            json.dump(state, output)
        os.replace(temp, path)
        return True
    except Exception as error:
        messagebox.showerror('بررسی لایسنس',
                             'برنامه باز نشد؛ اطلاعات شما حذف نشده است.\n'
                             'اتصال اینترنت و تنظیم سرور را بررسی کنید.\n' + str(error), parent=root)
        return False
    finally:
        root.destroy()
