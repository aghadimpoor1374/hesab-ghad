"""نمایش فارسی در Tk بدون تغییر رشته‌های منطقی فرم‌ها یا پایگاه داده."""
import os
import re
import sys
import tkinter as tk
from tkinter import messagebox as native_messagebox, simpledialog as native_simpledialog
from tkinter import ttk as native

import arabic_reshaper
from bidi.algorithm import get_display


# Tk backends differ in their shaping support. Prefer the platform renderer
# on Windows/macOS; allow an explicit override for other Tk/font builds.
TEXT_MODES = ('auto', 'native', 'manual')
_LTR_TOKEN = re.compile(
    r'\d{4}/\d{1,2}/\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?'
    r'|[A-Za-z][A-Za-z0-9_.:/+@%\-]*'
    r'|[+\-]?\d+(?:[.,/:]\d+)*(?:%)?'
)


def text_mode():
    mode = os.environ.get('HESAB_GHADIM_TEXT_MODE', 'auto').strip().lower()
    if mode not in TEXT_MODES:
        mode = 'auto'
    if mode == 'auto':
        return 'native' if sys.platform in ('win32', 'darwin') else 'manual'
    return mode


def visual(value):
    """Format only widget text; never use the result for storage or arithmetic."""
    text = str(value)
    if not any('\u0600' <= char <= '\u06ff' for char in text):
        return text
    lines = []
    for line in text.split('\n'):
        # Some Tk APIs pass display text through _options again. Handle each
        # line independently so an already-shaped line cannot hide a raw one.
        if any('\ufb50' <= char <= '\ufdff' or '\ufe70' <= char <= '\ufefc' for char in line):
            lines.append(line)
        elif not any('\u0600' <= char <= '\u06ff' for char in line):
            lines.append(line)
        elif text_mode() == 'native':
            # RLM selects a Persian paragraph even when it begins with PDF or
            # a number. Leave letters logical so the OS can shape them once.
            lines.append(line if line.startswith('\u200f') else '\u200f' + line)
        else:
            # Keep a timestamp (date + time) and tokens such as UTC+03:30 in
            # one LTR run, within the explicitly RTL Persian paragraph.
            protected = _LTR_TOKEN.sub(lambda m: '\u202a' + m.group() + '\u202c', line)
            lines.append(get_display(arabic_reshaper.reshape(protected), base_dir='R'))
    return '\n'.join(lines)


def _display_options(options):
    """ttk's tab/item methods bypass Widget._options; shape those explicitly."""
    options = dict(options)
    if options.get('text') is not None:
        options['text'] = visual(options['text'])
    if isinstance(options.get('values'), (tuple, list)):
        options['values'] = tuple(visual(value) for value in options['values'])
    return options


class _Messagebox:
    def __getattr__(self, name):
        def show(title=None, message=None, **options):
            # Windows/macOS message boxes render Unicode natively. Linux uses Tk.
            if sys.platform not in ('win32', 'darwin'):
                if message is not None:
                    message = visual(message)
                if 'detail' in options:
                    options['detail'] = visual(options['detail'])
            return getattr(native_messagebox, name)(title, message, **options)
        return show


class _Simpledialog:
    @staticmethod
    def askstring(title, prompt, **options):
        # The prompt is a Tk Label, even on Windows; the title belongs to the OS.
        return native_simpledialog.askstring(title, visual(prompt), **options)


messagebox = _Messagebox()
simpledialog = _Simpledialog()


class _Persian:
    def __init__(self, *args, **kwargs):
        self._links = {}
        self._choices = {}
        super().__init__(*args, **kwargs)
        self.bind('<Destroy>', self._cleanup, add='+')

    def _cleanup(self, event):
        if event.widget is self:
            for source, proxy, source_trace, proxy_trace in self._links.values():
                source.trace_remove('write', source_trace)
                if proxy_trace:
                    proxy.trace_remove('write', proxy_trace)
            self._links.clear()

    def _display_variable(self, source):
        if not isinstance(source, tk.Variable):
            return source
        name = str(source)
        if name not in self._links:
            proxy = tk.StringVar(master=self.master, value=visual(source.get()))
            busy = [False]

            def from_source(*_):
                if not busy[0]:
                    busy[0] = True
                    try:
                        proxy.set(visual(source.get()))
                    finally:
                        busy[0] = False

            def from_display(*_):
                if not busy[0] and proxy.get() in self._choices:
                    busy[0] = True
                    try:
                        source.set(self._choices[proxy.get()])
                    finally:
                        busy[0] = False

            source_trace = source.trace_add('write', from_source)
            proxy_trace = proxy.trace_add('write', from_display) if isinstance(self, native.Combobox) else None
            self._links[name] = (source, proxy, source_trace, proxy_trace)
        return self._links[name][1]

    def _options(self, cnf, kw=None):
        options = dict(tk._cnfmerge((cnf, kw)) if kw else tk._cnfmerge(cnf))
        if 'text' in options:
            options['text'] = visual(options['text'])
        if 'values' in options:
            values = options['values']
            if isinstance(values, (tuple, list)):
                if isinstance(self, native.Combobox):
                    self._choices = {visual(value): value for value in values}
                options['values'] = tuple(visual(value) for value in values)
        if 'textvariable' in options:
            options['textvariable'] = self._display_variable(options['textvariable'])
        return super()._options(options)


class Label(_Persian, native.Label):
    pass


class TkLabel(_Persian, tk.Label):
    pass


class Button(_Persian, native.Button):
    pass


class Checkbutton(_Persian, native.Checkbutton):
    pass


class LabelFrame(_Persian, native.LabelFrame):
    pass


class Combobox(_Persian, native.Combobox):
    def set(self, value):
        super().set(visual(value))


class Treeview(_Persian, native.Treeview):
    def heading(self, column, option=None, **kw):
        return super().heading(column, option, **_display_options(kw))

    def insert(self, parent, index, iid=None, **kw):
        return super().insert(parent, index, iid=iid, **_display_options(kw))

    def item(self, item, option=None, **kw):
        return super().item(item, option, **_display_options(kw))

    def set(self, item, column=None, value=None):
        return super().set(item, column, visual(value) if value is not None else None)


class Notebook(_Persian, native.Notebook):
    def add(self, child, **kw):
        return super().add(child, **_display_options(kw))

    def insert(self, pos, child, **kw):
        return super().insert(pos, child, **_display_options(kw))

    def tab(self, tab_id, option=None, **kw):
        return super().tab(tab_id, option, **_display_options(kw))


Frame = native.Frame
Panedwindow = native.Panedwindow
Entry = native.Entry
Scrollbar = native.Scrollbar
Style = native.Style
