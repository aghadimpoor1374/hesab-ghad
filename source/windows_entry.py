import os
from pathlib import Path
import tkinter.messagebox

folder = Path(os.environ['LOCALAPPDATA']) / 'HesabGhadim' / 'hesab_ghadim_files'
folder.mkdir(parents=True, exist_ok=True)
os.environ['HESAB_GHADIM_DATABASE'] = str(folder / 'gold_accounting.sqlite3')
os.chdir(folder)
try:
    from offline_license import check_license, install_monitor
    if not check_license(folder):
        raise SystemExit(1)
    import gold_accounting
    from desktop_update import install_ui

    def setup(root, close):
        install_monitor(root, folder, close)
        install_ui(root, folder, close)

    gold_accounting.main(license_setup=setup)
except Exception:
    import traceback
    error = traceback.format_exc()
    (folder / 'error.log').write_text(error, encoding='utf-8')
    tkinter.messagebox.showerror('Hesab Ghadim', error)
