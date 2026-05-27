import queue
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from parser import DEFAULT_START_URL, KrishaScraper, save_to_csv


class KrishaDesktopApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Krisha Parser Desktop")
        self.root.geometry("860x700")
        self.root.minsize(760, 620)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.running = False
        self.entries: list[ttk.Entry] = []

        self.start_url_var = tk.StringVar(value=DEFAULT_START_URL)
        self.pages_var = tk.StringVar(value="5")
        self.limit_var = tk.StringVar(value="200")
        self.delay_min_var = tk.StringVar(value="1")
        self.delay_max_var = tk.StringVar(value="2.5")
        self.output_var = tk.StringVar(value=str(Path.cwd() / "krisha_export.csv"))
        self.processed_var = tk.StringVar(value="Обработано: 0")

        self._configure_styles()
        self._build_ui()
        self._bind_entry_shortcuts()
        self._poll_logs()

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")

        style.configure("Root.TFrame", background="#f4f7fb")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"), background="#ffffff", foreground="#0f172a")
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10), background="#ffffff", foreground="#475569")
        style.configure("Section.TLabel", font=("Segoe UI", 10, "bold"), background="#ffffff", foreground="#1e3a8a")
        style.configure("Hint.TLabel", font=("Segoe UI", 9), background="#ffffff", foreground="#64748b")
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"), background="#ffffff", foreground="#1e40af")
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("TEntry", padding=7)
        style.configure("TProgressbar", thickness=16)

    def _build_ui(self) -> None:
        root_frame = ttk.Frame(self.root, style="Root.TFrame", padding=20)
        root_frame.pack(fill="both", expand=True)

        card = ttk.Frame(root_frame, style="Card.TFrame", padding=18)
        card.pack(fill="both", expand=True)

        title = ttk.Label(card, text="Krisha Parser Desktop", style="Title.TLabel")
        title.grid(row=0, column=0, columnspan=3, sticky="w")

        subtitle = ttk.Label(
            card,
            text="Сохранены те же функции: квартиры/коммерция, очистка author_company, CSV с ';'.",
            style="Subtitle.TLabel",
        )
        subtitle.grid(row=1, column=0, columnspan=3, pady=(2, 16), sticky="w")

        params = ttk.LabelFrame(card, text="Параметры", padding=12)
        params.grid(row=2, column=0, columnspan=3, sticky="nsew")

        self._add_labeled_entry(params, 0, "Ссылка на поиск", self.start_url_var, width=100, col_span=3)
        self._add_labeled_entry(params, 2, "Страниц", self.pages_var, width=20)
        self._add_labeled_entry(
            params, 2, "Лимит объявлений (0 = без лимита)", self.limit_var, width=30, col=1
        )
        self._add_labeled_entry(params, 4, "Задержка мин (сек)", self.delay_min_var, width=20)
        self._add_labeled_entry(params, 4, "Задержка макс (сек)", self.delay_max_var, width=20, col=1)
        self._add_labeled_entry(params, 6, "CSV файл", self.output_var, width=72, col_span=2)

        browse_btn = ttk.Button(params, text="Выбрать...", command=self._choose_output)
        browse_btn.grid(row=7, column=2, padx=(8, 0), pady=(0, 6), sticky="w")

        params.columnconfigure(0, weight=1)
        params.columnconfigure(1, weight=1)
        params.columnconfigure(2, weight=1)

        actions = ttk.Frame(card, style="Card.TFrame")
        actions.grid(row=3, column=0, columnspan=3, sticky="we", pady=(12, 8))

        self.run_btn = ttk.Button(
            actions,
            text="Запустить парсинг",
            command=self._start_parsing,
            style="Primary.TButton",
        )
        self.run_btn.grid(row=0, column=0, sticky="w")

        clear_btn = ttk.Button(actions, text="Очистить лог", command=self._clear_log)
        clear_btn.grid(row=0, column=1, padx=(8, 0), sticky="w")

        self.status_var = tk.StringVar(value="Готово к запуску")
        status_label = ttk.Label(actions, textvariable=self.status_var, style="Status.TLabel")
        status_label.grid(row=0, column=2, sticky="e")

        actions.columnconfigure(2, weight=1)

        progress_block = ttk.Frame(card, style="Card.TFrame")
        progress_block.grid(row=4, column=0, columnspan=3, sticky="we", pady=(2, 8))

        self.progress = ttk.Progressbar(progress_block, orient="horizontal", mode="determinate", maximum=100, value=0)
        self.progress.grid(row=0, column=0, columnspan=3, sticky="we")

        processed_label = ttk.Label(progress_block, textvariable=self.processed_var, style="Section.TLabel")
        processed_label.grid(row=1, column=0, pady=(6, 0), sticky="w")

        hint_label = ttk.Label(progress_block, text="Прогресс обновляется после каждого объявления", style="Hint.TLabel")
        hint_label.grid(row=1, column=2, pady=(6, 0), sticky="e")

        progress_block.columnconfigure(0, weight=1)
        progress_block.columnconfigure(1, weight=1)
        progress_block.columnconfigure(2, weight=1)

        log_label = ttk.Label(card, text="Лог выполнения", style="Section.TLabel")
        log_label.grid(row=5, column=0, columnspan=3, sticky="w")

        self.log_box = tk.Text(
            card,
            height=18,
            wrap="word",
            bg="#f8fafc",
            fg="#0f172a",
            relief="solid",
            borderwidth=1,
            font=("Consolas", 10),
        )
        self.log_box.grid(row=6, column=0, columnspan=3, sticky="nsew", pady=(4, 0))
        self.log_box.tag_configure("info", foreground="#334155")
        self.log_box.tag_configure("ok", foreground="#15803d")
        self.log_box.tag_configure("warn", foreground="#c2410c")
        self.log_box.tag_configure("error", foreground="#b91c1c")
        self.log_box.tag_configure("done", foreground="#1d4ed8")

        scrollbar = ttk.Scrollbar(card, orient="vertical", command=self.log_box.yview)
        scrollbar.grid(row=6, column=3, sticky="ns")
        self.log_box.configure(yscrollcommand=scrollbar.set)

        card.columnconfigure(0, weight=1)
        card.columnconfigure(1, weight=1)
        card.columnconfigure(2, weight=1)
        card.rowconfigure(6, weight=1)

    def _add_labeled_entry(
        self,
        frame: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        width: int,
        col: int = 0,
        col_span: int = 1,
    ) -> None:
        ttk.Label(frame, text=label).grid(row=row, column=col, columnspan=col_span, sticky="w", pady=(0, 2))
        entry = ttk.Entry(frame, textvariable=variable, width=width)
        entry.grid(row=row + 1, column=col, columnspan=col_span, sticky="we", pady=(0, 10))
        self.entries.append(entry)

    def _bind_entry_shortcuts(self) -> None:
        for entry in self.entries:
            entry.bind("<Control-v>", self._paste_from_clipboard)
            entry.bind("<Control-V>", self._paste_from_clipboard)
            entry.bind("<Shift-Insert>", self._paste_from_clipboard)
            entry.bind("<Button-3>", self._show_context_menu)

    def _paste_from_clipboard(self, event: tk.Event) -> str:
        widget = event.widget
        if not isinstance(widget, ttk.Entry):
            return "break"
        try:
            clipboard_text = self.root.clipboard_get()
        except tk.TclError:
            return "break"
        widget.insert(tk.INSERT, clipboard_text)
        return "break"

    def _show_context_menu(self, event: tk.Event) -> str:
        widget = event.widget
        if not isinstance(widget, ttk.Entry):
            return "break"
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Вставить", command=lambda: self._paste_into(widget))
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _paste_into(self, entry: ttk.Entry) -> None:
        try:
            clipboard_text = self.root.clipboard_get()
        except tk.TclError:
            return
        entry.insert(tk.INSERT, clipboard_text)

    def _choose_output(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="Выберите путь для CSV",
            defaultextension=".csv",
            filetypes=[("CSV file", "*.csv"), ("All files", "*.*")],
            initialfile="krisha_export.csv",
        )
        if selected:
            self.output_var.set(selected)

    def _clear_log(self) -> None:
        self.log_box.delete("1.0", tk.END)

    def _validate(self) -> tuple[bool, str]:
        if not self.start_url_var.get().strip().startswith("http"):
            return False, "Поле 'Ссылка на поиск' должно начинаться с http/https."
        try:
            pages = int(self.pages_var.get().strip())
            if pages < 1:
                return False, "Количество страниц должно быть >= 1."
        except ValueError:
            return False, "Поле 'Страниц' должно быть целым числом."

        try:
            limit = int(self.limit_var.get().strip())
            if limit < 0:
                return False, "Поле 'Лимит объявлений' должно быть >= 0."
        except ValueError:
            return False, "Поле 'Лимит объявлений' должно быть целым числом."

        try:
            delay_min = float(self.delay_min_var.get().strip())
            delay_max = float(self.delay_max_var.get().strip())
            if delay_min < 0 or delay_max < 0:
                return False, "Задержки не могут быть отрицательными."
            if delay_max < delay_min:
                return False, "'Задержка макс' должна быть >= 'Задержка мин'."
        except ValueError:
            return False, "Поля задержек должны быть числами."

        if not self.output_var.get().strip():
            return False, "Укажите путь к CSV файлу."

        return True, ""

    def _start_parsing(self) -> None:
        if self.running:
            return

        valid, error = self._validate()
        if not valid:
            messagebox.showerror("Ошибка валидации", error)
            return

        self.running = True
        self.run_btn.configure(state="disabled")
        self.status_var.set("Идет парсинг...")
        self.processed_var.set("Обработано: 0")
        self._log("=== Старт ===")

        limit_raw = int(self.limit_var.get().strip())
        if limit_raw == 0:
            self.progress.configure(mode="indeterminate", value=0, maximum=100)
            self.progress.start(10)
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=limit_raw, value=0)

        self.worker = threading.Thread(target=self._run_worker, daemon=True)
        self.worker.start()

    def _run_worker(self) -> None:
        try:
            pages = int(self.pages_var.get().strip())
            limit_raw = int(self.limit_var.get().strip())
            listings_limit = None if limit_raw == 0 else limit_raw
            delay_min = float(self.delay_min_var.get().strip())
            delay_max = float(self.delay_max_var.get().strip())
            start_url = self.start_url_var.get().strip()
            output = self.output_var.get().strip()

            self._log(f"[INFO] URL: {start_url}")
            self._log(f"[INFO] pages={pages}, limit={'ALL' if listings_limit is None else listings_limit}")
            self._log(f"[INFO] delay=({delay_min}, {delay_max})")

            scraper = KrishaScraper(
                start_url=start_url,
                delay_min=delay_min,
                delay_max=delay_max,
            )
            rows = scraper.run(
                pages_limit=pages,
                listings_limit=listings_limit,
                progress_callback=self._on_progress,
                log_callback=self._log,
            )
            save_to_csv(output, rows)

            self._log(f"[DONE] Сохранено: {len(rows)} строк в {output}")
            self.root.after(
                0, lambda: messagebox.showinfo("Готово", f"CSV сохранен:\n{output}\n\nСтрок: {len(rows)}")
            )
        except Exception as error:  # noqa: BLE001
            self._log("[ERROR] " + str(error))
            self._log(traceback.format_exc())
            self.root.after(0, lambda: messagebox.showerror("Ошибка", f"{error}"))
        finally:
            self.root.after(0, self._finish_run)

    def _finish_run(self) -> None:
        self.running = False
        self.run_btn.configure(state="normal")
        self.progress.stop()
        self.status_var.set("Готово к запуску")

    def _on_progress(self, processed: int, total: int | None) -> None:
        self.root.after(0, lambda: self._update_progress_ui(processed, total))

    def _update_progress_ui(self, processed: int, total: int | None) -> None:
        self.processed_var.set(f"Обработано: {processed}")
        if total is not None and self.progress.cget("mode") == "determinate":
            self.progress.configure(value=min(processed, int(total)))

    def _log(self, message: str) -> None:
        self.log_queue.put(message)

    def _poll_logs(self) -> None:
        try:
            while True:
                item = self.log_queue.get_nowait()
                self.log_box.insert(tk.END, item + "\n", self._log_tag(item))
                self.log_box.see(tk.END)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_logs)

    @staticmethod
    def _log_tag(message: str) -> str:
        upper = message.upper()
        if "[ERROR]" in upper or "TRACEBACK" in upper:
            return "error"
        if "[WARN]" in upper:
            return "warn"
        if "[OK]" in upper:
            return "ok"
        if "[DONE]" in upper:
            return "done"
        return "info"


def main() -> None:
    root = tk.Tk()
    app = KrishaDesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
