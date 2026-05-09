from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from tkinter import (
    BooleanVar,
    Listbox,
    StringVar,
    Tk,
    filedialog,
    messagebox,
    scrolledtext,
    simpledialog,
    ttk,
)

from guildbridge.gui_commands import (
    CommandResult,
    apply_confirmation_error,
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


@dataclass(frozen=True)
class Field:
    label: str
    variable: StringVar
    browse: str | None = None


class GuildBridgeGUI(ttk.Frame):
    def __init__(self, master: Tk) -> None:
        super().__init__(master, padding=12)
        self.master = master
        self.master.title("GuildBridge")
        self.master.minsize(980, 720)
        self.grid(row=0, column=0, sticky="nsew")
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)

        self.providers = tuple(sorted(provider_names()))
        self.result_queue: queue.Queue[CommandResult] = queue.Queue()
        self.output = scrolledtext.ScrolledText(self, height=14, wrap="word")

        self._build()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)

        notebook = ttk.Notebook(self)
        notebook.grid(row=0, column=0, sticky="nsew")
        notebook.add(self._export_tab(notebook), text="Export")
        notebook.add(self._import_tab(notebook), text="Import")
        notebook.add(self._migrate_tab(notebook), text="Migrate")
        notebook.add(self._tools_tab(notebook), text="Validate / Redact")
        notebook.add(self._platforms_tab(notebook), text="Platforms")

        output_frame = ttk.LabelFrame(self, text="Output")
        output_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        output_frame.columnconfigure(0, weight=1)
        self.output.grid(in_=output_frame, row=0, column=0, sticky="ew", padx=8, pady=8)
        ttk.Button(output_frame, text="Clear", command=lambda: self.output.delete("1.0", "end")).grid(
            row=0, column=1, sticky="ns", padx=(0, 8), pady=8
        )

    def _new_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=12)
        frame.columnconfigure(1, weight=1)
        return frame

    def _provider_combo(self, frame: ttk.Frame, label: str, row: int, variable: StringVar) -> None:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        combo = ttk.Combobox(frame, textvariable=variable, values=self.providers)
        combo.grid(row=row, column=1, sticky="ew", pady=4)
        if self.providers and not variable.get():
            variable.set(self.providers[0])

    def _provider_listbox(self, frame: ttk.Frame, label: str, row: int, defaults: tuple[str, ...]) -> Listbox:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=4)
        listbox = Listbox(frame, selectmode="extended", exportselection=False, height=min(max(len(self.providers), 3), 8))
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
        return listbox

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
        else:
            selected = filedialog.askopenfilename()
        if selected:
            field.variable.set(selected)

    def _export_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        frame = self._new_tab(parent)
        provider = StringVar(value="discord")
        source_id = StringVar()
        template = StringVar()
        out = StringVar(value="community.template.json")
        include_overwrites = BooleanVar(value=False)

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
                )
            ),
        ).grid(row=row + 1, column=1, sticky="e", pady=(12, 0))
        return frame

    def _import_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        frame = self._new_tab(parent)
        file = StringVar()
        target_id = StringVar()
        target_name = StringVar()
        plan_out = StringVar(value="-")
        plan_in = StringVar()
        journal_out = StringVar()
        resume_journal = StringVar()
        audit = StringVar()
        redact = BooleanVar(value=False)
        apply = BooleanVar(value=False)
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
        ttk.Checkbutton(frame, text="Force invalid template after review", variable=force_invalid_template).grid(
            row=row + 1, column=1, sticky="w"
        )
        ttk.Checkbutton(frame, text="Apply writes", variable=apply).grid(row=row + 2, column=1, sticky="w")
        ttk.Button(
            frame,
            text="Run Import",
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
                    apply=apply.get(),
                    force_invalid_template=force_invalid_template.get(),
                ),
                apply_requested=apply.get(),
                reviewed_plan=plan_in.get(),
            ),
        ).grid(row=row + 3, column=1, sticky="e", pady=(12, 0))
        return frame

    def _migrate_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        frame = self._new_tab(parent)
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
        redact = BooleanVar(value=True)
        apply = BooleanVar(value=False)
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
        ttk.Checkbutton(frame, text="Redact before import", variable=redact).grid(row=row + 1, column=1, sticky="w")
        ttk.Checkbutton(frame, text="Force invalid template after review", variable=force_invalid_template).grid(
            row=row + 2, column=1, sticky="w"
        )
        ttk.Checkbutton(frame, text="Apply writes", variable=apply).grid(row=row + 3, column=1, sticky="w")
        ttk.Button(
            frame,
            text="Run Migrate",
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
                    redact=redact.get(),
                    apply=apply.get(),
                    force_invalid_template=force_invalid_template.get(),
                ),
                apply_requested=apply.get(),
                reviewed_plan=plan_in.get(),
            ),
        ).grid(row=row + 4, column=1, sticky="e", pady=(12, 0))
        return frame

    def _tools_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        frame = self._new_tab(parent)
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
        return frame

    def _platforms_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        frame = self._new_tab(parent)
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
        frame.rowconfigure(1, weight=1)
        return frame

    def _run(self, args: list[str], *, apply_requested: bool = False, reviewed_plan: str = "") -> None:
        if apply_requested and not self._confirm_apply(reviewed_plan):
            return
        self._append_output(f"$ {command_preview(args)}\n")
        worker = threading.Thread(target=self._worker, args=(args,), daemon=True)
        worker.start()
        self.after(100, self._poll)

    def _confirm_apply(self, reviewed_plan: str) -> bool:
        plan_error = apply_confirmation_error(
            apply=True,
            plan_in=reviewed_plan,
            confirmation="APPLY",
        )
        if plan_error:
            messagebox.showerror("Apply writes", plan_error, parent=self.master)
            return False
        typed = simpledialog.askstring(
            "Confirm apply writes",
            "Type APPLY to run provider writes using the reviewed plan.",
            parent=self.master,
        )
        error = apply_confirmation_error(apply=True, plan_in=reviewed_plan, confirmation=typed)
        if error:
            messagebox.showerror("Apply writes", error, parent=self.master)
            return False
        return True

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
        if result.timed_out:
            self._append_output("Status: timed out\n")
        if result.stdout:
            self._append_output(result.stdout)
        if result.stderr:
            self._append_output(result.stderr)
        self._append_output(f"Exit code: {result.returncode}\nDuration: {result.duration_seconds:.2f}s\n\n")

    def _append_output(self, text: str) -> None:
        self.output.insert("end", text)
        self.output.see("end")


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
