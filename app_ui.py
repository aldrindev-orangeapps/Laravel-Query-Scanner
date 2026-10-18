"""Tkinter desktop interface for Laravel Query Scanner."""

from __future__ import annotations

import json
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional

from analyzer import Finding, LaravelQueryScanner, ScanSummary, findings_to_json
from context_builder import build_context
from project_store import ProjectStore


COLORS = {
    "bg": "#F4F7FB",
    "surface": "#FFFFFF",
    "sidebar": "#101828",
    "sidebar_muted": "#98A2B3",
    "text": "#101828",
    "muted": "#667085",
    "primary": "#2563EB",
    "primary_dark": "#1D4ED8",
    "border": "#D0D5DD",
    "high": "#B42318",
    "medium": "#B54708",
    "low": "#175CD3",
}


class LaravelScannerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Laravel Query Scanner")
        self.root.geometry("1240x780")
        self.root.minsize(1000, 680)
        self.root.configure(bg=COLORS["bg"])

        self.store = ProjectStore()
        self.project_var = tk.StringVar()
        self.scope_var = tk.StringVar(value="full")
        self.file_var = tk.StringVar()
        self.method_var = tk.StringVar()
        self.severity_var = tk.StringVar(value="All severities")
        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Select a Laravel project to begin.")
        self.summary_var = tk.StringVar(value="No scan yet")
        self.cache_var = tk.BooleanVar(value=True)

        self.findings: List[Finding] = []
        self.visible_findings: Dict[str, Finding] = {}
        self.last_summary: Optional[ScanSummary] = None
        self.cancel_event = threading.Event()
        self.worker: Optional[threading.Thread] = None

        self._configure_styles()
        self._build_layout()
        self._load_recent_project()
        self.search_var.trace_add("write", lambda *_: self._refresh_findings())
        self.severity_var.trace_add("write", lambda *_: self._refresh_findings())

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background=COLORS["bg"])
        style.configure("Surface.TFrame", background=COLORS["surface"])
        style.configure("Sidebar.TFrame", background=COLORS["sidebar"])
        style.configure("Title.TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=("Segoe UI", 22, "bold"))
        style.configure("Subtitle.TLabel", background=COLORS["bg"], foreground=COLORS["muted"], font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background=COLORS["surface"], foreground=COLORS["text"], font=("Segoe UI", 11, "bold"))
        style.configure("CardText.TLabel", background=COLORS["surface"], foreground=COLORS["muted"], font=("Segoe UI", 9))
        style.configure("SidebarTitle.TLabel", background=COLORS["sidebar"], foreground="white", font=("Segoe UI", 16, "bold"))
        style.configure("SidebarText.TLabel", background=COLORS["sidebar"], foreground=COLORS["sidebar_muted"], font=("Segoe UI", 9))
        style.configure("Primary.TButton", background=COLORS["primary"], foreground="white", borderwidth=0, padding=(16, 9), font=("Segoe UI", 9, "bold"))
        style.map("Primary.TButton", background=[("active", COLORS["primary_dark"]), ("disabled", "#98A2B3")])
        style.configure("Secondary.TButton", padding=(12, 8), font=("Segoe UI", 9))
        style.configure("Treeview", rowheight=29, font=("Segoe UI", 9), background="white", fieldbackground="white", bordercolor=COLORS["border"])
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), padding=(8, 8))
        style.map("Treeview", background=[("selected", "#DCE9FF")], foreground=[("selected", COLORS["text"])])
        style.configure("TRadiobutton", background=COLORS["surface"], font=("Segoe UI", 9))
        style.configure("TCheckbutton", background=COLORS["surface"], font=("Segoe UI", 9))

    def _build_layout(self) -> None:
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(self.root, style="Sidebar.TFrame", width=230, padding=(22, 24))
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        ttk.Label(sidebar, text="Laravel Query\nScanner", style="SidebarTitle.TLabel").pack(anchor="w")
        ttk.Label(sidebar, text="Local-first query diagnostics", style="SidebarText.TLabel").pack(anchor="w", pady=(8, 30))

        self.scan_button = ttk.Button(sidebar, text="Start scan", style="Primary.TButton", command=self.start_scan)
        self.scan_button.pack(fill="x")
        self.cancel_button = ttk.Button(sidebar, text="Cancel", style="Secondary.TButton", command=self.cancel_scan, state="disabled")
        self.cancel_button.pack(fill="x", pady=(10, 0))
        ttk.Separator(sidebar).pack(fill="x", pady=24)
        ttk.Label(sidebar, text="ZERO AI DURING SCAN", style="SidebarText.TLabel").pack(anchor="w")
        ttk.Label(
            sidebar,
            text="Static checks run on your computer.\nAI context is created only when\nyou request it.",
            style="SidebarText.TLabel",
            justify="left",
        ).pack(anchor="w", pady=(8, 0))
        ttk.Label(sidebar, textvariable=self.summary_var, style="SidebarText.TLabel", wraplength=180, justify="left").pack(side="bottom", anchor="w")

        main = ttk.Frame(self.root, padding=(26, 22))
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)
        ttk.Label(main, text="Find expensive Laravel queries", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(main, text="Scan any Laravel project without running the app or connecting to its database.", style="Subtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 16))

        setup = ttk.Frame(main, style="Surface.TFrame", padding=16)
        setup.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        setup.columnconfigure(1, weight=1)
        ttk.Label(setup, text="Project", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.project_combo = ttk.Combobox(setup, textvariable=self.project_var, values=self.store.recent_projects())
        self.project_combo.grid(row=0, column=1, sticky="ew")
        ttk.Button(setup, text="Browse…", command=self.choose_project).grid(row=0, column=2, padx=(8, 0))

        options = ttk.Frame(setup, style="Surface.TFrame")
        options.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        ttk.Radiobutton(options, text="Full project", variable=self.scope_var, value="full", command=self._toggle_scope).pack(side="left")
        ttk.Radiobutton(options, text="Selected PHP file", variable=self.scope_var, value="file", command=self._toggle_scope).pack(side="left", padx=(18, 0))
        ttk.Checkbutton(options, text="Use unchanged-result cache", variable=self.cache_var).pack(side="right")

        file_row = ttk.Frame(setup, style="Surface.TFrame")
        file_row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        file_row.columnconfigure(0, weight=1)
        self.file_entry = ttk.Entry(file_row, textvariable=self.file_var, state="disabled")
        self.file_entry.grid(row=0, column=0, sticky="ew")
        self.file_button = ttk.Button(file_row, text="Choose file…", command=self.choose_file, state="disabled")
        self.file_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(file_row, text="Method (optional)", style="CardText.TLabel").grid(row=0, column=2, padx=(18, 6))
        self.method_entry = ttk.Entry(file_row, textvariable=self.method_var, width=22, state="disabled")
        self.method_entry.grid(row=0, column=3)

        content = ttk.Panedwindow(main, orient="vertical")
        content.grid(row=3, column=0, sticky="nsew")

        results = ttk.Frame(content, style="Surface.TFrame", padding=12)
        results.columnconfigure(0, weight=1)
        results.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(results, style="Surface.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        toolbar.columnconfigure(1, weight=1)
        ttk.Label(toolbar, text="Findings", style="CardTitle.TLabel").grid(row=0, column=0, padx=(0, 14))
        ttk.Entry(toolbar, textvariable=self.search_var).grid(row=0, column=1, sticky="ew")
        ttk.Combobox(toolbar, textvariable=self.severity_var, values=("All severities", "High", "Medium", "Low"), state="readonly", width=16).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(toolbar, text="Export JSON", command=self.export_json).grid(row=0, column=3, padx=(8, 0))

        columns = ("severity", "rule", "location", "method", "message")
        self.tree = ttk.Treeview(results, columns=columns, show="headings", selectmode="browse")
        headings = {"severity": "Severity", "rule": "Rule", "location": "Location", "method": "Method", "message": "Finding"}
        widths = {"severity": 80, "rule": 70, "location": 280, "method": 150, "message": 430}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], minwidth=60, stretch=column in ("location", "message"))
        self.tree.tag_configure("high", foreground=COLORS["high"])
        self.tree.tag_configure("medium", foreground=COLORS["medium"])
        self.tree.tag_configure("low", foreground=COLORS["low"])
        scrollbar = ttk.Scrollbar(results, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._show_selected)
        content.add(results, weight=3)

        detail = ttk.Frame(content, style="Surface.TFrame", padding=14)
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(1, weight=1)
        detail_header = ttk.Frame(detail, style="Surface.TFrame")
        detail_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(detail_header, text="Finding details", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(detail_header, text="Open in VS Code", command=self.open_in_vscode).pack(side="right")
        ttk.Button(detail_header, text="Copy AI context", command=self.copy_context).pack(side="right", padx=(0, 8))
        ttk.Button(detail_header, text="Save AI context…", command=self.save_context).pack(side="right", padx=(0, 8))
        self.detail_text = tk.Text(detail, wrap="word", height=10, relief="flat", bg="#F9FAFB", fg=COLORS["text"], font=("Consolas", 9), padx=10, pady=10)
        self.detail_text.grid(row=1, column=0, sticky="nsew")
        self.detail_text.configure(state="disabled")
        content.add(detail, weight=2)

        status = ttk.Frame(main)
        status.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_var, style="Subtitle.TLabel").grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(status, mode="determinate", length=220)
        self.progress.grid(row=0, column=1, sticky="e")

    def _load_recent_project(self) -> None:
        recent = self.store.recent_projects()
        if recent:
            self.project_var.set(recent[0])

    def _toggle_scope(self) -> None:
        enabled = self.scope_var.get() == "file"
        state = "normal" if enabled else "disabled"
        self.file_entry.configure(state=state)
        self.file_button.configure(state=state)
        self.method_entry.configure(state=state)

    def choose_project(self) -> None:
        selected = filedialog.askdirectory(title="Select Laravel project", initialdir=self.project_var.get() or None)
        if selected:
            self.project_var.set(selected)
            self.store.remember(Path(selected))
            self.project_combo.configure(values=self.store.recent_projects())

    def choose_file(self) -> None:
        project = Path(self.project_var.get()) if self.project_var.get() else Path.cwd()
        selected = filedialog.askopenfilename(title="Select PHP file", initialdir=str(project), filetypes=(("PHP files", "*.php"), ("All files", "*.*")))
        if selected:
            self.file_var.set(selected)

    def _validate_scan(self) -> Optional[tuple[Path, Optional[Path], Optional[str]]]:
        if not self.project_var.get().strip():
            messagebox.showwarning("Project required", "Select a Laravel project first.")
            return None
        project = Path(self.project_var.get()).resolve()
        if not LaravelQueryScanner.is_laravel_project(project):
            messagebox.showerror("Not a Laravel project", "The selected folder must contain artisan, composer.json, and app/.")
            return None
        selected_file: Optional[Path] = None
        selected_method: Optional[str] = None
        if self.scope_var.get() == "file":
            if not self.file_var.get().strip():
                messagebox.showwarning("File required", "Choose a PHP file for selected-file scan.")
                return None
            selected_file = Path(self.file_var.get()).resolve()
            try:
                selected_file.relative_to(project)
            except ValueError:
                messagebox.showerror("File outside project", "Choose a PHP file inside the selected Laravel project.")
                return None
            if not selected_file.is_file() or selected_file.suffix.lower() != ".php":
                messagebox.showerror("Invalid file", "The selected scan target must be an existing .php file.")
                return None
            selected_method = self.method_var.get().strip() or None
        return project, selected_file, selected_method

    def start_scan(self) -> None:
        validated = self._validate_scan()
        if not validated:
            return
        project, selected_file, selected_method = validated
        self.store.remember(project)
        self.cancel_event.clear()
        self.findings = []
        self.last_summary = None
        self._refresh_findings()
        self.scan_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress.configure(value=0, maximum=1)
        self.status_var.set("Preparing project analysis…")
        use_cache = self.cache_var.get()

        def run() -> None:
            try:
                scanner = LaravelQueryScanner(project, use_cache=use_cache)

                def progress(current: int, total: int, path: Path) -> None:
                    relative = path.relative_to(project)
                    self.root.after(0, self._update_progress, current, total, str(relative))

                summary = scanner.scan(
                    selected_file=selected_file,
                    selected_method=selected_method,
                    progress=progress,
                    cancelled=self.cancel_event.is_set,
                )
                self.root.after(0, self._scan_complete, summary)
            except Exception as exc:  # UI boundary: present unexpected scanner errors safely.
                self.root.after(0, self._scan_failed, str(exc))

        self.worker = threading.Thread(target=run, name="laravel-query-scan", daemon=True)
        self.worker.start()

    def _update_progress(self, current: int, total: int, relative: str) -> None:
        self.progress.configure(maximum=max(total, 1), value=current)
        self.status_var.set("Scanning %d/%d: %s" % (current, total, relative))

    def cancel_scan(self) -> None:
        self.cancel_event.set()
        self.cancel_button.configure(state="disabled")
        self.status_var.set("Cancelling after the current file…")

    def _scan_complete(self, summary: ScanSummary) -> None:
        self.last_summary = summary
        self.findings = summary.findings
        self._refresh_findings()
        self.scan_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        high = sum(item.severity == "high" for item in summary.findings)
        medium = sum(item.severity == "medium" for item in summary.findings)
        low = sum(item.severity == "low" for item in summary.findings)
        label = "%d files • %d findings\n%d high  %d medium  %d low\n%d files reused from cache" % (
            summary.files_scanned, len(summary.findings), high, medium, low, summary.files_cached
        )
        self.summary_var.set(label)
        prefix = "Scan cancelled." if summary.cancelled else "Scan complete."
        self.status_var.set("%s %d findings in %d files." % (prefix, len(summary.findings), summary.files_scanned))

    def _scan_failed(self, error: str) -> None:
        self.scan_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.status_var.set("Scan failed.")
        messagebox.showerror("Scan failed", error)

    def _refresh_findings(self) -> None:
        if not hasattr(self, "tree"):
            return
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.visible_findings.clear()
        severity = self.severity_var.get().lower().replace(" severities", "")
        search = self.search_var.get().strip().lower()
        for index, finding in enumerate(self.findings):
            haystack = " ".join((finding.rule_id, finding.file, finding.method, finding.title, finding.message)).lower()
            if severity != "all" and finding.severity != severity:
                continue
            if search and search not in haystack:
                continue
            item_id = "finding-%d" % index
            location = "%s:%d" % (finding.file, finding.line)
            self.tree.insert("", "end", iid=item_id, values=(finding.severity.upper(), finding.rule_id, location, finding.method, finding.title), tags=(finding.severity,))
            self.visible_findings[item_id] = finding

    def _selected_finding(self) -> Optional[Finding]:
        selection = self.tree.selection()
        return self.visible_findings.get(selection[0]) if selection else None

    def _show_selected(self, _event: object = None) -> None:
        finding = self._selected_finding()
        if not finding:
            return
        content = (
            "%s • %s confidence\n%s:%d • %s()\n\n%s\n\nSuggestion\n%s\n\nCode\n%s"
            % (
                finding.title,
                finding.confidence,
                finding.file,
                finding.line,
                finding.method,
                finding.message,
                finding.suggestion,
                finding.snippet,
            )
        )
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", content)
        self.detail_text.configure(state="disabled")

    def _context_for_selected(self) -> Optional[str]:
        finding = self._selected_finding()
        if not finding:
            messagebox.showinfo("Select a finding", "Select one finding first.")
            return None
        project = Path(self.project_var.get()).resolve()
        try:
            return build_context(project, finding.file, finding.method, self.findings)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Context generation failed", str(exc))
            return None

    def copy_context(self) -> None:
        context = self._context_for_selected()
        if context is None:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(context)
        self.status_var.set("AI context copied. No AI request was sent by this app.")

    def save_context(self) -> None:
        context = self._context_for_selected()
        finding = self._selected_finding()
        if context is None or finding is None:
            return
        destination = filedialog.asksaveasfilename(
            title="Save AI context",
            defaultextension=".md",
            initialfile="%s-%s-query-context.md" % (Path(finding.file).stem, finding.method),
            filetypes=(("Markdown", "*.md"), ("Text", "*.txt")),
        )
        if destination:
            Path(destination).write_text(context, encoding="utf-8")
            self.status_var.set("AI context saved to %s" % destination)

    def export_json(self) -> None:
        if self.last_summary is None:
            messagebox.showinfo("Nothing to export", "Run a scan first.")
            return
        destination = filedialog.asksaveasfilename(
            title="Export findings",
            defaultextension=".json",
            initialfile="laravel-query-findings.json",
            filetypes=(("JSON", "*.json"),),
        )
        if destination:
            Path(destination).write_text(findings_to_json(self.last_summary), encoding="utf-8")
            self.status_var.set("Findings exported to %s" % destination)

    def open_in_vscode(self) -> None:
        finding = self._selected_finding()
        if not finding:
            messagebox.showinfo("Select a finding", "Select one finding first.")
            return
        path = Path(self.project_var.get()).resolve() / finding.file
        try:
            subprocess.Popen(
                ["code", "--goto", "%s:%d" % (path, finding.line)],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            messagebox.showerror("VS Code unavailable", "Could not run the 'code' command. Enable it in your PATH or open the location manually.")


def run_app() -> None:
    root = tk.Tk()
    LaravelScannerApp(root)
    root.mainloop()

