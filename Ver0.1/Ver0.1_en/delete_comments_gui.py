from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


class CommentRemoverApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("C/C Header Comment Remover")
        self.root.geometry("640x300")
        self.root.resizable(False, False)

        self.folder_path_var = tk.StringVar()
        self.status_var = tk.StringVar(value="请选择一个文件夹")
        self.progress_var = tk.DoubleVar(value=0.0)

        self.total_files = 0
        self.processed_files = 0
        self.update_queue: queue.Queue = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.errors: list[str] = []
        self.cancel_event = threading.Event()
        self.was_cancelled = False

        self._build_ui()

    def _build_ui(self) -> None:
        padding = {"padx": 12, "pady": 8}

        path_frame = ttk.LabelFrame(self.root, text="目标文件夹")
        path_frame.pack(fill="x", **padding)

        path_entry = ttk.Entry(path_frame, textvariable=self.folder_path_var, state="readonly")
        path_entry.pack(side="left", fill="x", expand=True, padx=(12, 6), pady=8)

        browse_btn = ttk.Button(path_frame, text="选择...", command=self.select_folder)
        browse_btn.pack(side="left", padx=(0, 12), pady=8)

        actions_frame = ttk.Frame(self.root)
        actions_frame.pack(fill="x", **padding)

        self.start_btn = ttk.Button(actions_frame, text="开始处理", command=self.start_processing)
        self.start_btn.pack(side="left", padx=(12, 6))

        self.cancel_btn = ttk.Button(actions_frame, text="取消", state="disabled", command=self.cancel_processing)
        self.cancel_btn.pack(side="left", padx=(6, 12))

        progress_frame = ttk.LabelFrame(self.root, text="处理进度")
        progress_frame.pack(fill="x", **padding)

        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill="x", padx=12, pady=(12, 6))

        self.progress_label = ttk.Label(progress_frame, textvariable=self.status_var, anchor="w")
        self.progress_label.pack(fill="x", padx=12, pady=(0, 12))

        self.current_file_var = tk.StringVar(value="当前文件：无")
        self.current_file_label = ttk.Label(self.root, textvariable=self.current_file_var, anchor="w")
        self.current_file_label.pack(fill="x", padx=24)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def select_folder(self) -> None:
        selected = filedialog.askdirectory()
        if selected:
            self.folder_path_var.set(selected)
            self.status_var.set("已选择文件夹，点击开始处理")
            self.progress_var.set(0.0)
            self.current_file_var.set("当前文件：无")

    def start_processing(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("操作进行中", "仍在处理中，请稍候或取消。")
            return

        folder_path = self.folder_path_var.get()
        if not folder_path:
            messagebox.showinfo("提示", "请先选择一个文件夹。")
            return

        target = Path(folder_path)
        if not target.exists() or not target.is_dir():
            messagebox.showerror("错误", "所选路径不可用，请重新选择。")
            return

        files = self.collect_target_files(target)
        if not files:
            messagebox.showinfo("提示", "选定文件夹内没有 .c 或 .h 文件。")
            return

        self.total_files = len(files)
        self.processed_files = 0
        self.errors = []
        self.was_cancelled = False
        self.progress_var.set(0.0)
        self.progress_bar.configure(maximum=self.total_files)
        self.status_var.set(f"准备处理 {self.total_files} 个文件...")
        self.current_file_var.set("当前文件：准备中")

        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")

        self.update_queue = queue.Queue()
        self.cancel_event.clear()

        self.worker_thread = threading.Thread(
            target=self._worker,
            args=(files,),
            daemon=True,
        )
        self.worker_thread.start()
        self.root.after(100, self._poll_queue)

    def collect_target_files(self, root_path: Path) -> list[Path]:
        files: list[Path] = []
        for suffix in (".c", ".h"):
            files.extend(root_path.rglob(f"*{suffix}"))
        files.sort()
        return files

    def _worker(self, files: list[Path]) -> None:
        for index, file_path in enumerate(files, start=1):
            if self.cancel_event.is_set():
                break
            try:
                self.remove_comments_from_file(file_path)
                self.update_queue.put(("progress", index, file_path))
            except Exception as exc:
                self.errors.append(f"{file_path}: {exc}")
                self.update_queue.put(("error", index, file_path, str(exc)))
        if self.cancel_event.is_set():
            self.update_queue.put(("cancelled", None))
        else:
            self.update_queue.put(("done", None))

    def _poll_queue(self) -> None:
        try:
            while True:
                event = self.update_queue.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass

        if self.worker_thread and self.worker_thread.is_alive():
            self.root.after(100, self._poll_queue)
        else:
            self.start_btn.configure(state="normal")
            self.cancel_btn.configure(state="disabled")
            if self.worker_thread is not None:
                if self.was_cancelled:
                    messagebox.showinfo(
                        "已取消",
                        f"处理已取消，已完成 {self.processed_files}/{self.total_files} 个文件。",
                    )
                elif self.errors:
                    messagebox.showwarning(
                        "处理完成（有警告）",
                        "处理完成，但部分文件出现错误，请查看日志。\n"
                        + "\n".join(self.errors[:5])
                        + ("\n..." if len(self.errors) > 5 else ""),
                    )
                else:
                    messagebox.showinfo("处理完成", "所有文件处理完成。")
                self.worker_thread = None

    def _handle_event(self, event: tuple) -> None:
        event_type = event[0]
        if event_type == "progress":
            _, index, file_path = event
            self.processed_files = index
            self.progress_var.set(index)
            self.status_var.set(f"已处理 {index}/{self.total_files} 个文件")
            self.current_file_var.set(f"当前文件：{file_path}")
        elif event_type == "error":
            _, index, file_path, message = event
            self.processed_files = index
            self.progress_var.set(index)
            self.status_var.set(f"处理 {index}/{self.total_files} 个文件时出错")
            self.current_file_var.set(f"错误文件：{file_path} - {message}")
        elif event_type == "cancelled":
            self.was_cancelled = True
            self.status_var.set(f"处理已取消，已完成 {self.processed_files}/{self.total_files} 个文件")
            self.current_file_var.set("当前文件：无")
        elif event_type == "done":
            self.processed_files = self.total_files
            self.progress_var.set(self.total_files)
            self.status_var.set("处理完成，所有文件已更新")
            self.current_file_var.set("当前文件：无")

    def cancel_processing(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            self.cancel_event.set()
            self.cancel_btn.configure(state="disabled")

    def on_close(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            if not messagebox.askyesno("退出", "任务仍在进行，确定要退出吗？"):
                return
            self.cancel_event.set()
        self.root.destroy()

    def remove_comments_from_file(self, file_path: Path) -> None:
        original_text = file_path.read_text(encoding="utf-8", errors="ignore")
        cleaned_text = self.remove_c_comments(original_text)
        if cleaned_text != original_text:
            file_path.write_text(cleaned_text, encoding="utf-8")

    def remove_c_comments(self, source: str) -> str:
        # Stateful parser to strip C-style comments without touching string or char literals.
        result: list[str] = []
        i = 0
        length = len(source)
        state = "default"

        while i < length:
            ch = source[i]

            if state == "default":
                if ch == '"':
                    result.append(ch)
                    state = "string"
                elif ch == "'":
                    result.append(ch)
                    state = "char"
                elif ch == "/" and i + 1 < length:
                    next_ch = source[i + 1]
                    if next_ch == "/":
                        state = "single_comment"
                        i += 1
                    elif next_ch == "*":
                        state = "multi_comment"
                        i += 1
                    else:
                        result.append(ch)
                else:
                    result.append(ch)
            elif state == "string":
                result.append(ch)
                if ch == "\\" and i + 1 < length:
                    result.append(source[i + 1])
                    i += 1
                elif ch == '"':
                    state = "default"
            elif state == "char":
                result.append(ch)
                if ch == "\\" and i + 1 < length:
                    result.append(source[i + 1])
                    i += 1
                elif ch == "'":
                    state = "default"
            elif state == "single_comment":
                if ch == "\n":
                    result.append(ch)
                    state = "default"
            elif state == "multi_comment":
                if ch == "*" and i + 1 < length and source[i + 1] == "/":
                    state = "default"
                    i += 1
                elif ch in "\r\n":
                    result.append(ch)
            i += 1

        return "".join(result)


def main() -> None:
    root = tk.Tk()
    CommentRemoverApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
