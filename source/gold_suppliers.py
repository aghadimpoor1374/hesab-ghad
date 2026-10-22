"""Supplier selection and purchase profile, desktop UI."""
def choose_supplier(parent, ledger):
    import tkinter as tk
    from tkinter import simpledialog
    import gold_widgets as ttk
    from gold_widgets import messagebox
    from gold_accounting import display

    window = tk.Toplevel(parent)
    window.title('بنکداران — انتخاب و پرونده خرید طلای نو')
    window.geometry('960x600')
    window.transient(parent)
    result = [None]
    mapping = {}
    choice = tk.StringVar()
    combo = ttk.Combobox(window, textvariable=choice, state='readonly', width=55)
    combo.pack(fill='x', padx=10, pady=8)
    summary = tk.StringVar()
    ttk.Label(window, textvariable=summary, anchor='e', justify='right').pack(fill='x', padx=10)
    columns = ('fee', 'weight', 'product', 'date', 'document')
    tree = ttk.Treeview(window, columns=columns, show='headings', height=14)
    for key, label in zip(columns, ('اجرت (گرم)', 'وزن (گرم)', 'کالا', 'تاریخ', 'سند')):
        tree.heading(key, text=label)
        tree.column(key, width=160, anchor='e')
    tree.pack(fill='both', expand=True, padx=10, pady=10)

    def show(*_):
        if choice.get() not in mapping:
            return
        data = ledger.supplier_summary(mapping[choice.get()])
        summary.set('خرید: {} گرم | اجرت خرید: {} گرم\nمانده فیزیکی: {} گرم | اجرت تخصیص‌یافته به مانده: {} گرم\nمانده بر اساس FIFO است؛ این اعداد به معنی بدهی تسویه‌نشده نیستند.'.format(*(display(data[k]) for k in ('purchased', 'fees', 'remaining', 'remaining_fee'))))
        for item in tree.get_children():
            tree.delete(item)
        from decimal import Decimal
        for row in data['records']:
            tree.insert('', 'end', values=(display(Decimal(row['weight']) * Decimal(row['gold_fee_rate']) / 100), row['stock_weight'], row['product_title'] or '—', row['created_at_jalali'], row['document_no']))

    def reload(selected=None):
        mapping.clear()
        mapping['تعیین‌نشده — سوابق قدیمی'] = None
        for row in ledger.suppliers():
            mapping[f"{row['name']} — {row['phone']} (#{row['id']})"] = row['id']
        combo.configure(values=list(mapping))
        choice.set(next((key for key, value in mapping.items() if value == selected), next(iter(mapping))))
        show()

    def create():
        name = simpledialog.askstring('بنکدار جدید', 'نام بنکدار:', parent=window)
        if not name:
            return
        phone = simpledialog.askstring('بنکدار جدید', 'تلفن (اختیاری):', parent=window)
        try:
            reload(ledger.create_supplier(name, phone or ''))
        except ValueError as error:
            messagebox.showerror('ثبت نشد', str(error), parent=window)

    def accept():
        supplier = mapping.get(choice.get())
        if supplier is None:
            messagebox.showerror('انتخاب بنکدار', 'برای خرید جدید یک بنکدار مشخص انتخاب کنید.', parent=window)
            return
        result[0] = supplier
        window.destroy()

    combo.bind('<<ComboboxSelected>>', show)
    ttk.Button(window, text='افزودن بنکدار', command=create).pack(side='right', padx=10, pady=10)
    ttk.Button(window, text='ورود جنس در پرونده این بنکدار', command=accept).pack(side='right', padx=10, pady=10)
    reload()
    window.grab_set()
    parent.wait_window(window)
    return result[0]
