from __future__ import annotations

import json
import queue
import sys
import threading
from collections import Counter
from dataclasses import dataclass
from functools import partial
from importlib import resources
from pathlib import Path
from tkinter import (
    BooleanVar,
    Canvas,
    Listbox,
    PhotoImage,
    StringVar,
    Tk,
    filedialog,
    messagebox,
    scrolledtext,
    ttk,
)
from typing import Any, cast

from guildbridge.gui_commands import (
    CommandResult,
    apply_confirmation_error,
    build_content_export_args,
    build_content_import_args,
    build_content_migrate_args,
    build_export_args,
    build_import_args,
    build_migrate_args,
    build_redact_args,
    build_validate_args,
    command_preview,
    run_cli_args,
)
from guildbridge.platforms import SUPPORTED_PLATFORMS, runtime_check
from guildbridge.providers import provider_names
from guildbridge.safety import APPLY_CONFIRMATION


@dataclass(frozen=True)
class Field:
    label: str
    variable: StringVar
    browse: str | None = None


@dataclass(frozen=True)
class ApplyPrompt:
    operation: str
    source_provider: str | None
    target_providers: tuple[str, ...]
    target_id: str
    target_name: str


GUI_THEMES: dict[str, dict[str, str]] = {
    "Light": {
        "bg": "#f4f6f8",
        "surface": "#ffffff",
        "surface_soft": "#eef2f6",
        "text": "#17202a",
        "muted": "#586577",
        "border": "#c7d0dd",
        "field": "#ffffff",
        "field_focus": "#dce9fb",
        "select_bg": "#1f5fbf",
        "select_fg": "#ffffff",
        "button": "#1f5fbf",
        "button_active": "#174a96",
        "output_bg": "#ffffff",
        "output_fg": "#17202a",
    },
    "Dark": {
        "bg": "#11161d",
        "surface": "#171d25",
        "surface_soft": "#202833",
        "text": "#e8eef5",
        "muted": "#aab5c3",
        "border": "#394454",
        "field": "#0f141b",
        "field_focus": "#1e334f",
        "select_bg": "#78a8ff",
        "select_fg": "#08111e",
        "button": "#2f6fc6",
        "button_active": "#3f82dd",
        "output_bg": "#0b1016",
        "output_fg": "#e8eef5",
    },
}


class GuildBridgeGUI(ttk.Frame):
    def __init__(self, master: Tk) -> None:
        super().__init__(master, padding=12)
        self.root = master
        self.master = master
        self.master.title("GuildBridge")
        self.master.minsize(980, 720)
        self.grid(row=0, column=0, sticky="nsew")
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)

        self.providers = tuple(sorted(provider_names()))
        self.result_queue: queue.Queue[CommandResult] = queue.Queue()
        self.style = ttk.Style(master)
        self.theme = StringVar(value="Light")
        self.output = scrolledtext.ScrolledText(self, height=10, wrap="word")
        self.icon_image: PhotoImage | None = None
        self.themed_canvases: list[Canvas] = []
        self.themed_listboxes: list[Listbox] = []
        self.themed_trees: list[ttk.Treeview] = []

        self._set_window_icon()
        self._build()
        self._apply_theme()
        self.root.after(100, self._refresh_windows_titlebar)
        self.root.after(500, self._refresh_windows_titlebar)
        self.master.bind_all("<MouseWheel>", self._on_tab_mousewheel, add="+")
        self.master.bind_all("<Button-4>", self._on_tab_mousewheel, add="+")
        self.master.bind_all("<Button-5>", self._on_tab_mousewheel, add="+")

    def _set_window_icon(self) -> None:
        try:
            png_resource = resources.files("guildbridge").joinpath("assets/guildbridge-icon.png")
            with resources.as_file(png_resource) as png_path:
                self.icon_image = PhotoImage(file=str(png_path))
            self.root.iconphoto(True, self.icon_image)
        except Exception:
            self.icon_image = None
        if sys.platform == "win32":
            try:
                ico_resource = resources.files("guildbridge").joinpath("assets/guildbridge-icon.ico")
                with resources.as_file(ico_resource) as ico_path:
                    self.root.iconbitmap(str(ico_path))
                    self.root.iconbitmap(default=str(ico_path))
            except Exception:
                pass

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=0)
        self.rowconfigure(1, weight=3)
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Theme").grid(row=0, column=1, sticky="e", padx=(0, 8))
        theme_combo = ttk.Combobox(header, textvariable=self.theme, values=tuple(GUI_THEMES), state="readonly", width=10)
        theme_combo.grid(row=0, column=2, sticky="e")
        theme_combo.bind("<<ComboboxSelected>>", lambda _event: self._apply_theme())

        notebook = ttk.Notebook(self)
        notebook.grid(row=1, column=0, sticky="nsew")
        notebook.add(self._export_tab(notebook), text="Export")
        notebook.add(self._import_tab(notebook), text="Import")
        notebook.add(self._migrate_tab(notebook), text="Migrate")
        notebook.add(self._content_tab(notebook), text="Content")
        notebook.add(self._tools_tab(notebook), text="Validate / Redact")
        notebook.add(self._platforms_tab(notebook), text="Platforms")

        output_frame = ttk.LabelFrame(self, text="Output")
        output_frame.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)
        self.output.grid(in_=output_frame, row=0, column=0, sticky="nsew", padx=8, pady=8)
        ttk.Button(output_frame, text="Clear", command=lambda: self.output.delete("1.0", "end")).grid(
            row=0, column=1, sticky="ne", padx=(0, 8), pady=8
        )

    def _apply_theme(self) -> None:
        palette = GUI_THEMES.get(self.theme.get(), GUI_THEMES["Light"])
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        self.master["background"] = palette["bg"]
        self._apply_windows_titlebar(palette)
        self.configure(style="TFrame")
        self.style.configure(".", background=palette["bg"], foreground=palette["text"])
        self.style.configure("TFrame", background=palette["bg"])
        self.style.configure("TLabelframe", background=palette["bg"], bordercolor=palette["border"])
        self.style.configure("TLabelframe.Label", background=palette["bg"], foreground=palette["text"])
        self.style.configure("TLabel", background=palette["bg"], foreground=palette["text"])
        self.style.configure("TCheckbutton", background=palette["bg"], foreground=palette["text"])
        self.style.map(
            "TCheckbutton",
            background=[("active", palette["surface_soft"])],
            foreground=[("disabled", palette["muted"])],
        )
        self.style.configure(
            "TButton",
            background=palette["button"],
            foreground="#ffffff",
            bordercolor=palette["button"],
            focusthickness=1,
            focuscolor=palette["field_focus"],
            padding=(8, 4),
        )
        self.style.map(
            "TButton",
            background=[("active", palette["button_active"]), ("disabled", palette["surface_soft"])],
            foreground=[("disabled", palette["muted"])],
        )
        self.style.configure(
            "TEntry",
            fieldbackground=palette["field"],
            foreground=palette["text"],
            bordercolor=palette["border"],
            insertcolor=palette["text"],
        )
        self.style.configure(
            "TCombobox",
            fieldbackground=palette["field"],
            background=palette["field"],
            foreground=palette["text"],
            bordercolor=palette["border"],
            arrowcolor=palette["text"],
            selectbackground=palette["select_bg"],
            selectforeground=palette["select_fg"],
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[("readonly", palette["field"])],
            foreground=[("readonly", palette["text"])],
            selectbackground=[("readonly", palette["select_bg"])],
            selectforeground=[("readonly", palette["select_fg"])],
        )
        self.style.configure("TNotebook", background=palette["bg"], bordercolor=palette["border"])
        self.style.configure(
            "TNotebook.Tab",
            background=palette["surface_soft"],
            foreground=palette["text"],
            padding=(8, 4),
        )
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", palette["surface"]), ("active", palette["field_focus"])],
            foreground=[("selected", palette["text"])],
        )
        self.style.configure(
            "Treeview",
            background=palette["field"],
            fieldbackground=palette["field"],
            foreground=palette["text"],
            bordercolor=palette["border"],
            rowheight=24,
        )
        self.style.configure(
            "Treeview.Heading",
            background=palette["surface_soft"],
            foreground=palette["text"],
            bordercolor=palette["border"],
        )
        self.style.map(
            "Treeview",
            background=[("selected", palette["select_bg"])],
            foreground=[("selected", palette["select_fg"])],
        )

        self.output.configure(
            background=palette["output_bg"],
            foreground=palette["output_fg"],
            insertbackground=palette["output_fg"],
            selectbackground=palette["select_bg"],
            selectforeground=palette["select_fg"],
            highlightbackground=palette["border"],
            highlightcolor=palette["select_bg"],
        )
        for canvas in self.themed_canvases:
            canvas.configure(background=palette["bg"], highlightbackground=palette["border"])
        for listbox in self.themed_listboxes:
            listbox.configure(
                background=palette["field"],
                foreground=palette["text"],
                selectbackground=palette["select_bg"],
                selectforeground=palette["select_fg"],
                highlightbackground=palette["border"],
                highlightcolor=palette["select_bg"],
                relief="solid",
                borderwidth=1,
            )
        for tree in self.themed_trees:
            for row_index, item in enumerate(tree.get_children("")):
                tree.item(item, tags=("odd" if row_index % 2 else "even",))
            tree.tag_configure("even", background=palette["field"], foreground=palette["text"])
            tree.tag_configure("odd", background=palette["surface"], foreground=palette["text"])
        if sys.platform == "win32":
            self.root.after(100, self._refresh_windows_titlebar)

    def _apply_windows_titlebar(self, palette: dict[str, str]) -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes

            self.root.update_idletasks()
            dwmapi = ctypes.windll.dwmapi
            dark = ctypes.c_int(1 if self.theme.get() == "Dark" else 0)
            hwnds = self._windows_titlebar_hwnds(ctypes, wintypes)

            for hwnd in hwnds:
                for attribute in (20, 19):
                    dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(dark), ctypes.sizeof(dark))
                for attribute, color in (
                    (34, palette["border"]),
                    (35, palette["bg"]),
                    (36, palette["text"]),
                ):
                    colorref = ctypes.c_int(self._windows_colorref(color))
                    dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(colorref), ctypes.sizeof(colorref))
            ctypes.windll.user32.RedrawWindow(hwnds[-1], None, None, 0x0400 | 0x0100 | 0x0001)
        except Exception:
            pass

    def _refresh_windows_titlebar(self) -> None:
        self._apply_windows_titlebar(GUI_THEMES.get(self.theme.get(), GUI_THEMES["Light"]))

    def _windows_titlebar_hwnds(self, ctypes: Any, wintypes: Any) -> list[Any]:
        ctypes.windll.user32.GetParent.argtypes = (wintypes.HWND,)
        ctypes.windll.user32.GetParent.restype = wintypes.HWND
        ctypes.windll.user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        ctypes.windll.user32.GetAncestor.restype = wintypes.HWND
        hwnd = wintypes.HWND(self.root.winfo_id())
        hwnds = [hwnd]
        for handle in (
            ctypes.windll.user32.GetParent(hwnd),
            ctypes.windll.user32.GetAncestor(hwnd, 2),
        ):
            if handle and all(int(existing.value or 0) != int(handle) for existing in hwnds):
                hwnds.append(wintypes.HWND(handle))
        return hwnds

    @staticmethod
    def _windows_colorref(hex_color: str) -> int:
        value = hex_color.lstrip("#")
        red = int(value[0:2], 16)
        green = int(value[2:4], 16)
        blue = int(value[4:6], 16)
        return red | (green << 8) | (blue << 16)

    def _new_tab(self, parent: ttk.Notebook) -> tuple[ttk.Frame, ttk.Frame]:
        container = ttk.Frame(parent)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        canvas = Canvas(container, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        frame = ttk.Frame(canvas, padding=12)
        frame.columnconfigure(1, weight=1)

        canvas_window = canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        frame.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(canvas_window, width=event.width))
        self.themed_canvases.append(canvas)
        return container, frame

    def _provider_combo(self, frame: ttk.Frame, label: str, row: int, variable: StringVar) -> None:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        combo = ttk.Combobox(frame, textvariable=variable, values=self.providers, state="readonly")
        combo.grid(row=row, column=1, sticky="ew", pady=4)
        if self.providers and not variable.get():
            variable.set(self.providers[0])

    @staticmethod
    def _option_combo(frame: ttk.Frame, label: str, row: int, variable: StringVar, values: tuple[str, ...]) -> None:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        combo = ttk.Combobox(frame, textvariable=variable, values=values, state="readonly")
        combo.grid(row=row, column=1, sticky="ew", pady=4)
        if values and variable.get() not in values:
            variable.set(values[0])

    def _provider_listbox(self, frame: ttk.Frame, label: str, row: int, defaults: tuple[str, ...]) -> Listbox:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=4)
        listbox = Listbox(frame, selectmode="multiple", exportselection=False, height=min(max(len(self.providers), 3), 8))
        for provider in self.providers:
            listbox.insert("end", provider)
        selected = False
        for index, provider in enumerate(self.providers):
            if provider in defaults:
                listbox.selection_set(index)
                selected = True
        if self.providers and not selected:
            listbox.selection_set(0)
        listbox.grid(row=row, column=1, sticky="ew", pady=4)
        self.themed_listboxes.append(listbox)
        return listbox

    def _tab_canvas_for_event(self, event: Any) -> Canvas | None:
        widget = self.master.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget in self.themed_canvases:
                return widget
            widget = getattr(widget, "master", None)
        return None

    def _on_tab_mousewheel(self, event: Any) -> str | None:
        canvas = self._tab_canvas_for_event(event)
        if canvas is None:
            return None
        units = 3 if getattr(event, "num", None) == 5 or getattr(event, "delta", 0) < 0 else -3
        canvas.yview_scroll(units, "units")
        return "break"

    @staticmethod
    def _selected_providers(listbox: Listbox) -> list[str]:
        selected = [str(listbox.get(index)) for index in listbox.curselection()]
        if selected or listbox.size() == 0:
            return selected
        return [str(listbox.get(0))]

    def _fields(self, frame: ttk.Frame, start_row: int, fields: tuple[Field, ...]) -> int:
        row = start_row
        for field in fields:
            ttk.Label(frame, text=field.label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
            ttk.Entry(frame, textvariable=field.variable).grid(row=row, column=1, sticky="ew", pady=4)
            if field.browse:
                ttk.Button(frame, text="Browse", command=partial(self._browse, field)).grid(
                    row=row, column=2, sticky="ew", padx=(8, 0), pady=4
                )
            row += 1
        return row

    def _browse(self, field: Field) -> None:
        if field.browse == "save":
            selected = filedialog.asksaveasfilename(initialfile=Path(field.variable.get()).name)
        elif field.browse == "folder":
            selected = filedialog.askdirectory()
        else:
            selected = filedialog.askopenfilename()
        if selected:
            field.variable.set(selected)

    def _export_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        tab, frame = self._new_tab(parent)
        provider = StringVar(value="discord")
        source_id = StringVar()
        template = StringVar()
        out = StringVar(value="community.template.json")
        include_overwrites = BooleanVar(value=False)
        include_content = BooleanVar(value=False)

        self._provider_combo(frame, "From", 0, provider)
        row = self._fields(
            frame,
            1,
            (
                Field("Source ID", source_id),
                Field("Template URL/code", template),
                Field("Output JSON", out, "save"),
            ),
        )
        ttk.Checkbutton(frame, text="Include user overwrites", variable=include_overwrites).grid(
            row=row, column=1, sticky="w", pady=4
        )
        ttk.Checkbutton(frame, text="Include content migration (experimental)", variable=include_content).grid(
            row=row + 1, column=1, sticky="w"
        )
        ttk.Button(
            frame,
            text="Run Export",
            command=lambda: self._run(
                build_export_args(
                    provider.get(),
                    source_id=source_id.get(),
                    template=template.get(),
                    out=out.get(),
                    include_user_overwrites=include_overwrites.get(),
                    include_content=include_content.get(),
                )
            ),
        ).grid(row=row + 2, column=1, sticky="e", pady=(12, 0))
        return tab

    def _import_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        tab, frame = self._new_tab(parent)
        file = StringVar()
        target_id = StringVar()
        target_name = StringVar()
        plan_out = StringVar(value="-")
        plan_in = StringVar()
        journal_out = StringVar()
        resume_journal = StringVar()
        audit = StringVar()
        redact = BooleanVar(value=False)
        include_content = BooleanVar(value=False)
        force_invalid_template = BooleanVar(value=False)

        provider_to = self._provider_listbox(frame, "To", 0, ("discord",))
        row = self._fields(
            frame,
            1,
            (
                Field("Template JSON", file, "open"),
                Field("Target ID", target_id),
                Field("Target name", target_name),
                Field("Plan/result JSON", plan_out, "save"),
                Field("Reviewed plan JSON", plan_in, "open"),
                Field("Journal output JSON", journal_out, "save"),
                Field("Resume journal JSON", resume_journal, "open"),
                Field("Audit reason", audit),
            ),
        )
        ttk.Checkbutton(frame, text="Redact before import", variable=redact).grid(row=row, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Include content migration (experimental)", variable=include_content).grid(
            row=row + 1, column=1, sticky="w"
        )
        ttk.Checkbutton(frame, text="Force invalid template after review", variable=force_invalid_template).grid(
            row=row + 2, column=1, sticky="w"
        )
        actions = ttk.Frame(frame)
        actions.grid(row=row + 3, column=1, sticky="e", pady=(12, 0))
        ttk.Button(
            actions,
            text="Dry-run Check",
            command=lambda: self._run_dry_run(
                build_import_args(
                    self._selected_providers(provider_to),
                    file=file.get(),
                    target_id=target_id.get(),
                    target_name=target_name.get(),
                    plan_out=plan_out.get(),
                    plan_in="",
                    journal_out=journal_out.get(),
                    resume_journal=resume_journal.get(),
                    audit_log_reason=audit.get(),
                    redact=redact.get(),
                    include_content=include_content.get(),
                    apply=False,
                    force_invalid_template=force_invalid_template.get(),
                ),
                plan_out=plan_out.get(),
            ),
        ).grid(row=0, column=0, sticky="e", padx=(0, 8))
        ttk.Button(
            actions,
            text="Actual Run",
            command=lambda: self._run(
                build_import_args(
                    self._selected_providers(provider_to),
                    file=file.get(),
                    target_id=target_id.get(),
                    target_name=target_name.get(),
                    plan_out=plan_out.get(),
                    plan_in=plan_in.get(),
                    journal_out=journal_out.get(),
                    resume_journal=resume_journal.get(),
                    audit_log_reason=audit.get(),
                    redact=redact.get(),
                    include_content=include_content.get(),
                    apply=True,
                    force_invalid_template=force_invalid_template.get(),
                ),
                apply_requested=True,
                reviewed_plan=plan_in.get(),
                plan_out=plan_out.get(),
                apply_prompt=ApplyPrompt(
                    operation="Import",
                    source_provider=None,
                    target_providers=tuple(self._selected_providers(provider_to)),
                    target_id=target_id.get(),
                    target_name=target_name.get(),
                ),
            ),
        ).grid(row=0, column=1, sticky="e")
        return tab

    def _migrate_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        tab, frame = self._new_tab(parent)
        provider_from = StringVar(value="discord")
        source_id = StringVar()
        template = StringVar()
        target_id = StringVar()
        target_name = StringVar()
        template_out = StringVar()
        plan_out = StringVar(value="-")
        plan_in = StringVar()
        journal_out = StringVar()
        resume_journal = StringVar()
        audit = StringVar()
        include_overwrites = BooleanVar(value=False)
        include_content = BooleanVar(value=False)
        redact = BooleanVar(value=True)
        force_invalid_template = BooleanVar(value=False)

        self._provider_combo(frame, "From", 0, provider_from)
        provider_to = self._provider_listbox(frame, "To", 1, ("fluxer",))
        row = self._fields(
            frame,
            2,
            (
                Field("Source ID", source_id),
                Field("Template URL/code", template),
                Field("Target ID", target_id),
                Field("Target name", target_name),
                Field("Template output JSON", template_out, "save"),
                Field("Plan/result JSON", plan_out, "save"),
                Field("Reviewed plan JSON", plan_in, "open"),
                Field("Journal output JSON", journal_out, "save"),
                Field("Resume journal JSON", resume_journal, "open"),
                Field("Audit reason", audit),
            ),
        )
        ttk.Checkbutton(frame, text="Include user overwrites", variable=include_overwrites).grid(row=row, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Include content migration (experimental)", variable=include_content).grid(
            row=row + 1, column=1, sticky="w"
        )
        ttk.Checkbutton(frame, text="Redact before import", variable=redact).grid(row=row + 2, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Force invalid template after review", variable=force_invalid_template).grid(
            row=row + 3, column=1, sticky="w"
        )
        actions = ttk.Frame(frame)
        actions.grid(row=row + 4, column=1, sticky="e", pady=(12, 0))
        ttk.Button(
            actions,
            text="Dry-run Check",
            command=lambda: self._run_dry_run(
                build_migrate_args(
                    provider_from.get(),
                    self._selected_providers(provider_to),
                    source_id=source_id.get(),
                    template=template.get(),
                    target_id=target_id.get(),
                    target_name=target_name.get(),
                    template_out=template_out.get(),
                    plan_out=plan_out.get(),
                    plan_in="",
                    journal_out=journal_out.get(),
                    resume_journal=resume_journal.get(),
                    audit_log_reason=audit.get(),
                    include_user_overwrites=include_overwrites.get(),
                    include_content=include_content.get(),
                    redact=redact.get(),
                    apply=False,
                    force_invalid_template=force_invalid_template.get(),
                ),
                plan_out=plan_out.get(),
            ),
        ).grid(row=0, column=0, sticky="e", padx=(0, 8))
        ttk.Button(
            actions,
            text="Actual Run",
            command=lambda: self._run(
                build_migrate_args(
                    provider_from.get(),
                    self._selected_providers(provider_to),
                    source_id=source_id.get(),
                    template=template.get(),
                    target_id=target_id.get(),
                    target_name=target_name.get(),
                    template_out=template_out.get(),
                    plan_out=plan_out.get(),
                    plan_in=plan_in.get(),
                    journal_out=journal_out.get(),
                    resume_journal=resume_journal.get(),
                    audit_log_reason=audit.get(),
                    include_user_overwrites=include_overwrites.get(),
                    include_content=include_content.get(),
                    redact=redact.get(),
                    apply=True,
                    force_invalid_template=force_invalid_template.get(),
                ),
                apply_requested=True,
                reviewed_plan=plan_in.get(),
                plan_out=plan_out.get(),
                apply_prompt=ApplyPrompt(
                    operation="Migrate",
                    source_provider=provider_from.get(),
                    target_providers=tuple(self._selected_providers(provider_to)),
                    target_id=target_id.get(),
                    target_name=target_name.get(),
                ),
            ),
        ).grid(row=0, column=1, sticky="e")
        return tab

    def _content_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        tab, frame = self._new_tab(parent)
        discord_export = StringVar()
        discord_source_id = StringVar()
        discord_exporter_bin = StringVar()
        discord_exporter_version = StringVar(value="latest")
        discord_exporter_install_dir = StringVar()
        discord_token_env = StringVar(value="DISCORD_TOKEN")
        discord_export_out = StringVar()
        archive_file = StringVar()
        archive_out = StringVar(value="community.content.json")
        target_id = StringVar()
        target_name = StringVar()
        channel_map = StringVar()
        plan_out = StringVar(value="-")
        plan_in = StringVar()
        content_journal_out = StringVar()
        resume_content_journal = StringVar()
        content_dead_letter_out = StringVar()
        content_report_out = StringVar()
        content_lock_file = StringVar()
        content_incremental_state = StringVar()
        message_limit = StringVar()
        content_max_failures = StringVar(value="1")
        content_parallel_sends = StringVar(value="1")
        content_thread_mode = StringVar(value="reference")
        content_thread_archive_dir = StringVar()
        no_authors = BooleanVar(value=False)
        no_attachments = BooleanVar(value=False)
        no_reactions = BooleanVar(value=False)
        no_embeds = BooleanVar(value=False)
        no_stickers = BooleanVar(value=False)
        no_polls = BooleanVar(value=False)
        no_threads = BooleanVar(value=False)
        no_custom_emoji = BooleanVar(value=False)
        native_content = BooleanVar(value=False)
        ferry_parity = BooleanVar(value=False)
        download_remote_assets = BooleanVar(value=False)
        download_discord_chat_exporter = BooleanVar(value=False)
        force_invalid_archive = BooleanVar(value=False)
        content_incremental = BooleanVar(value=False)
        content_continue_on_error = BooleanVar(value=False)

        provider_to = self._provider_listbox(frame, "To", 0, ("stoat",))
        row = self._fields(
            frame,
            1,
            (
                Field("DiscordChatExporter file/folder", discord_export, "folder"),
                Field("Discord guild/server ID", discord_source_id),
                Field("DiscordChatExporter app", discord_exporter_bin, "open"),
                Field("Managed DCE version", discord_exporter_version),
                Field("Managed DCE install folder", discord_exporter_install_dir, "folder"),
                Field("Discord token env var", discord_token_env),
                Field("Discord export output", discord_export_out, "folder"),
                Field("Content archive JSON", archive_file, "open"),
                Field("Archive output JSON", archive_out, "save"),
                Field("Target ID", target_id),
                Field("Target name", target_name),
                Field("Channel map JSON", channel_map, "open"),
                Field("Plan/result JSON", plan_out, "save"),
                Field("Reviewed plan JSON", plan_in, "open"),
                Field("Content journal JSON", content_journal_out, "save"),
                Field("Resume content journal", resume_content_journal, "open"),
                Field("Dead-letter JSON", content_dead_letter_out, "save"),
                Field("Report JSON", content_report_out, "save"),
                Field("Content lock file", content_lock_file, "save"),
                Field("Incremental state JSON", content_incremental_state, "save"),
                Field("Message limit", message_limit),
                Field("Max failures", content_max_failures),
                Field("Parallel sends", content_parallel_sends),
                Field("Thread archive folder", content_thread_archive_dir, "folder"),
            ),
        )
        self._option_combo(frame, "Thread mode", row, content_thread_mode, ("reference", "merge", "channel", "markdown"))
        row += 1
        ttk.Checkbutton(frame, text="Omit author names", variable=no_authors).grid(row=row, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Omit attachment references", variable=no_attachments).grid(row=row + 1, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Omit reactions", variable=no_reactions).grid(row=row + 2, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Omit embeds", variable=no_embeds).grid(row=row + 3, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Omit stickers", variable=no_stickers).grid(row=row + 4, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Omit polls", variable=no_polls).grid(row=row + 5, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Omit thread/forum references", variable=no_threads).grid(row=row + 6, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Omit custom emoji summary", variable=no_custom_emoji).grid(row=row + 7, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Use provider-native content features", variable=native_content).grid(row=row + 8, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Discord -> Stoat full-fidelity preset", variable=ferry_parity).grid(row=row + 9, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Download remote media/assets", variable=download_remote_assets).grid(row=row + 10, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Download DiscordChatExporter if needed", variable=download_discord_chat_exporter).grid(row=row + 11, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Incremental resume state", variable=content_incremental).grid(row=row + 12, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Continue after failed messages", variable=content_continue_on_error).grid(row=row + 13, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Force invalid archive after review", variable=force_invalid_archive).grid(
            row=row + 14, column=1, sticky="w"
        )

        actions = ttk.Frame(frame)
        actions.grid(row=row + 15, column=1, sticky="e", pady=(12, 0))

        def content_options(*, apply: bool, reviewed: bool) -> dict[str, Any]:
            return {
                "target_id": target_id.get(),
                "target_name": target_name.get(),
                "channel_map": channel_map.get(),
                "plan_out": plan_out.get(),
                "plan_in": plan_in.get() if reviewed else "",
                "apply": apply,
                "force_invalid_archive": force_invalid_archive.get(),
                "message_limit": message_limit.get(),
                "no_authors": no_authors.get(),
                "no_attachments": no_attachments.get(),
                "no_reactions": no_reactions.get(),
                "no_embeds": no_embeds.get(),
                "no_stickers": no_stickers.get(),
                "no_polls": no_polls.get(),
                "no_threads": no_threads.get(),
                "no_custom_emoji": no_custom_emoji.get(),
                "native_content": native_content.get(),
                "ferry_parity": ferry_parity.get(),
                "download_remote_assets": download_remote_assets.get(),
                "content_journal_out": content_journal_out.get(),
                "resume_content_journal": resume_content_journal.get(),
                "content_dead_letter_out": content_dead_letter_out.get(),
                "content_report_out": content_report_out.get(),
                "content_lock_file": content_lock_file.get(),
                "content_incremental_state": content_incremental_state.get(),
                "content_incremental": content_incremental.get(),
                "content_continue_on_error": content_continue_on_error.get(),
                "content_max_failures": content_max_failures.get(),
                "content_parallel_sends": content_parallel_sends.get(),
                "content_thread_mode": content_thread_mode.get(),
                "content_thread_archive_dir": content_thread_archive_dir.get(),
            }

        ttk.Button(
            actions,
            text="Export Archive",
            command=lambda: self._run(
                build_content_export_args(
                    discord_chat_export=discord_export.get(),
                    source_id=discord_source_id.get(),
                    discord_chat_exporter_bin=discord_exporter_bin.get(),
                    download_discord_chat_exporter=download_discord_chat_exporter.get(),
                    discord_chat_exporter_version=discord_exporter_version.get(),
                    discord_chat_exporter_install_dir=discord_exporter_install_dir.get(),
                    discord_token_env=discord_token_env.get(),
                    discord_export_out=discord_export_out.get(),
                    out=archive_out.get(),
                )
            ),
        ).grid(row=0, column=0, sticky="e", padx=(0, 8), pady=(0, 8))
        ttk.Button(
            actions,
            text="Dry-run Import",
            command=lambda: self._run_dry_run(
                build_content_import_args(
                    self._selected_providers(provider_to),
                    file=archive_file.get(),
                    **content_options(apply=False, reviewed=False),
                ),
                plan_out=plan_out.get(),
            ),
        ).grid(row=0, column=1, sticky="e", padx=(0, 8), pady=(0, 8))
        ttk.Button(
            actions,
            text="Dry-run Migrate",
            command=lambda: self._run_dry_run(
                build_content_migrate_args(
                    self._selected_providers(provider_to),
                    discord_chat_export=discord_export.get(),
                    source_id=discord_source_id.get(),
                    discord_chat_exporter_bin=discord_exporter_bin.get(),
                    download_discord_chat_exporter=download_discord_chat_exporter.get(),
                    discord_chat_exporter_version=discord_exporter_version.get(),
                    discord_chat_exporter_install_dir=discord_exporter_install_dir.get(),
                    discord_token_env=discord_token_env.get(),
                    discord_export_out=discord_export_out.get(),
                    **content_options(apply=False, reviewed=False),
                ),
                plan_out=plan_out.get(),
            ),
        ).grid(row=0, column=2, sticky="e", pady=(0, 8))
        ttk.Button(
            actions,
            text="Actual Import",
            command=lambda: self._run(
                build_content_import_args(
                    self._selected_providers(provider_to),
                    file=archive_file.get(),
                    **content_options(apply=True, reviewed=True),
                ),
                apply_requested=True,
                reviewed_plan=plan_in.get(),
                plan_out=plan_out.get(),
                apply_prompt=ApplyPrompt(
                    operation="Content import",
                    source_provider=None,
                    target_providers=tuple(self._selected_providers(provider_to)),
                    target_id=target_id.get(),
                    target_name=target_name.get(),
                ),
            ),
        ).grid(row=1, column=1, sticky="e", padx=(0, 8))
        ttk.Button(
            actions,
            text="Actual Migrate",
            command=lambda: self._run(
                build_content_migrate_args(
                    self._selected_providers(provider_to),
                    discord_chat_export=discord_export.get(),
                    source_id=discord_source_id.get(),
                    discord_chat_exporter_bin=discord_exporter_bin.get(),
                    download_discord_chat_exporter=download_discord_chat_exporter.get(),
                    discord_chat_exporter_version=discord_exporter_version.get(),
                    discord_chat_exporter_install_dir=discord_exporter_install_dir.get(),
                    discord_token_env=discord_token_env.get(),
                    discord_export_out=discord_export_out.get(),
                    **content_options(apply=True, reviewed=True),
                ),
                apply_requested=True,
                reviewed_plan=plan_in.get(),
                plan_out=plan_out.get(),
                apply_prompt=ApplyPrompt(
                    operation="Content migrate",
                    source_provider="discord",
                    target_providers=tuple(self._selected_providers(provider_to)),
                    target_id=target_id.get(),
                    target_name=target_name.get(),
                ),
            ),
        ).grid(row=1, column=2, sticky="e")
        return tab

    def _tools_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        tab, frame = self._new_tab(parent)
        validate_file = StringVar()
        redact_file = StringVar()
        redact_out = StringVar(value="redacted.template.json")

        row = self._fields(frame, 0, (Field("Validate JSON", validate_file, "open"),))
        ttk.Button(frame, text="Validate", command=lambda: self._run(build_validate_args(validate_file.get()))).grid(
            row=row, column=1, sticky="e", pady=(8, 16)
        )
        row += 1
        row = self._fields(
            frame,
            row,
            (
                Field("Redact JSON", redact_file, "open"),
                Field("Redacted output", redact_out, "save"),
            ),
        )
        ttk.Button(
            frame,
            text="Redact",
            command=lambda: self._run(build_redact_args(redact_file.get(), out=redact_out.get())),
        ).grid(row=row, column=1, sticky="e", pady=(8, 0))
        return tab

    def _platforms_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        tab, frame = self._new_tab(parent)
        frame.columnconfigure(0, weight=1)
        checks = runtime_check()
        check_text = "\n".join(f"{key}: {value}" for key, value in checks.items())
        ttk.Label(frame, text=check_text, justify="left").grid(row=0, column=0, sticky="w", pady=(0, 12))

        columns = ("name", "family", "cli", "desktop", "web", "ci")
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=12)
        for column, label in (
            ("name", "Platform"),
            ("family", "Family"),
            ("cli", "CLI"),
            ("desktop", "Desktop GUI"),
            ("web", "Web GUI"),
            ("ci", "CI"),
        ):
            tree.heading(column, text=label)
            tree.column(column, width=170 if column not in {"name", "family"} else 130)
        for supported in SUPPORTED_PLATFORMS:
            tree.insert(
                "",
                "end",
                values=(
                    supported.name,
                    supported.family,
                    supported.cli_support,
                    supported.desktop_gui_support,
                    supported.web_gui_support,
                    supported.ci_coverage,
                ),
            )
        tree.grid(row=1, column=0, sticky="nsew")
        self.themed_trees.append(tree)
        frame.rowconfigure(1, weight=1)
        return tab

    def _run(
        self,
        args: list[str],
        *,
        apply_requested: bool = False,
        reviewed_plan: str = "",
        plan_out: str = "",
        apply_prompt: ApplyPrompt | None = None,
    ) -> None:
        if apply_requested and not self._confirm_apply(reviewed_plan, plan_out, apply_prompt):
            return
        self._append_output(f"$ {command_preview(args)}\nStatus: running...\n")
        worker = threading.Thread(target=self._worker, args=(args,), daemon=True)
        worker.start()
        self.after(100, self._poll)

    def _run_dry_run(self, args: list[str], *, plan_out: str) -> None:
        if not plan_out.strip() or plan_out.strip() == "-":
            messagebox.showerror(
                "Dry-run Check",
                "Dry-run Check requires a Plan/result JSON file path. This keeps generated plans out of the output panel.",
                parent=self.master,
            )
            return
        self._run(args)

    def _confirm_apply(self, reviewed_plan: str, plan_out: str, prompt: ApplyPrompt | None) -> bool:
        reviewed_plan = reviewed_plan.strip()
        plan_out = plan_out.strip()
        plan_error = apply_confirmation_error(
            apply=True,
            plan_in=reviewed_plan,
            confirmation=APPLY_CONFIRMATION,
            plan_out=plan_out,
        )
        if plan_error:
            messagebox.showerror("Actual run", plan_error, parent=self.master)
            return False
        try:
            preview = self._reviewed_plan_preview(reviewed_plan)
        except ValueError as exc:
            messagebox.showerror("Actual run", str(exc), parent=self.master)
            return False
        return bool(
            messagebox.askyesno(
                "Confirm actual run",
                self._apply_confirmation_message(prompt, reviewed_plan, plan_out, preview),
                icon="warning",
                parent=self.master,
            )
        )

    @staticmethod
    def _reviewed_plan_preview(reviewed_plan: str) -> list[str]:
        path = Path(reviewed_plan.strip()).expanduser()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ValueError(f"Could not read reviewed plan JSON:\n{path}\n\n{exc}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"Reviewed plan JSON is not valid JSON:\n{path}\n\n{exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Reviewed plan JSON must contain an object.")
        plan = data.get("plan")
        actions = data.get("actions")
        if not isinstance(plan, dict) or not isinstance(actions, list):
            raise ValueError("Reviewed plan JSON must be a dry-run result with plan metadata and actions.")
        context_raw = plan.get("context")
        context = cast(dict[str, Any], context_raw) if isinstance(context_raw, dict) else {}
        action_count = int(plan.get("action_count") or len(actions))
        providers = Counter(str(action.get("provider") or "unknown") for action in actions if isinstance(action, dict))
        methods = Counter(str(action.get("method") or "UNKNOWN") for action in actions if isinstance(action, dict))
        paths = Counter(
            f"{action.get('provider') or 'unknown'} {action.get('method') or 'UNKNOWN'} {action.get('path') or ''}".strip()
            for action in actions
            if isinstance(action, dict)
        )

        lines = [
            f"Reviewed plan file: {path}",
            f"Source provider: {context.get('source_provider') or 'n/a'}",
            f"Target provider: {context.get('provider') or 'n/a'}",
            f"Target ID: {context.get('target_id') or 'new target if supported'}",
            f"Target name: {context.get('target_name') or 'not set'}",
            f"Planned write actions: {action_count}",
        ]
        if providers:
            lines.append("Action providers: " + ", ".join(f"{name} ({count})" for name, count in providers.most_common()))
        if methods:
            lines.append("Action types: " + ", ".join(f"{name} {count}" for name, count in methods.most_common()))
        if paths:
            lines.append("Most common incoming changes:")
            lines.extend(f"  - {name} x{count}" for name, count in paths.most_common(8))
        return lines

    @staticmethod
    def _apply_confirmation_message(
        prompt: ApplyPrompt | None,
        reviewed_plan: str,
        plan_out: str,
        preview: list[str],
    ) -> str:
        lines = [
            "This actual run will write changes to the selected platform/server.",
            "",
        ]
        if prompt is not None:
            lines.append(f"Operation: {prompt.operation}")
            if prompt.source_provider:
                lines.append(f"From: {prompt.source_provider}")
            lines.append(f"To: {', '.join(prompt.target_providers) or 'n/a'}")
            lines.append(f"Selected target ID: {prompt.target_id or 'new target if supported'}")
            lines.append(f"Selected target name: {prompt.target_name or 'not set'}")
            lines.append("")
        lines.extend(preview)
        lines.extend(
            [
                "",
                f"Apply result output: {plan_out.strip() or 'output panel only'}",
                "",
                "Continue with the actual run?",
            ]
        )
        return "\n".join(lines)

    def _worker(self, args: list[str]) -> None:
        self.result_queue.put(run_cli_args(args))

    def _poll(self) -> None:
        try:
            result = self.result_queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll)
            return
        self._show_result(result)

    def _show_result(self, result: CommandResult) -> None:
        status = "completed successfully" if result.returncode == 0 and not result.timed_out else "failed"
        if result.timed_out:
            status = "timed out"
        if result.stdout:
            self._append_output(result.stdout)
        if result.stderr:
            self._append_output(result.stderr)
        self._append_output(f"Status: {status}\nExit code: {result.returncode}\nDuration: {result.duration_seconds:.2f}s\n\n")
        if result.returncode == 0 and not result.timed_out:
            messagebox.showinfo(
                "GuildBridge",
                self._result_dialog_message(result, "Command completed successfully"),
                parent=self.master,
            )
        else:
            messagebox.showerror("GuildBridge", self._result_dialog_message(result, f"Command {status}"), parent=self.master)

    @staticmethod
    def _result_dialog_message(result: CommandResult, heading: str) -> str:
        details = (result.stderr or result.stdout).strip()
        message = f"{heading}. Exit code: {result.returncode}. Duration: {result.duration_seconds:.2f}s."
        if details:
            max_length = 1800
            if len(details) > max_length:
                details = details[:max_length].rstrip() + "\n..."
            message += f"\n\n{details}"
        return message

    def _append_output(self, text: str) -> None:
        self.output.insert("end", text)
        self.output.see("end")
        self.output.update_idletasks()


def main() -> int:
    try:
        root = Tk()
    except Exception as exc:
        print(f"guildbridge-gui: unable to start Tkinter GUI: {exc}")
        return 1
    GuildBridgeGUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
