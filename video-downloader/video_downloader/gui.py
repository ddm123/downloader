import queue
import sys
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText

from .downloader import download_video


class DownloaderApp:
    WINDOW_WIDTH = 760
    WINDOW_HEIGHT = 560

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("视频下载器")
        asset_root = Path(
            getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)
        ) / "video_downloader" / "assets"
        self.window_icon = tk.PhotoImage(file=str(asset_root / "video_downloader.png"))
        self.root.iconphoto(True, self.window_icon)
        self.root.geometry(f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}")
        self.root.minsize(580, 420)

        self.events: queue.Queue[tuple] = queue.Queue()
        self.output_dir = tk.StringVar(value=str(Path("videos").resolve()))
        self.status = tk.StringVar(value="就绪")

        self._build_ui()
        self._center_window()
        self.root.after(100, self._process_events)

    def _center_window(self) -> None:
        x = max(0, (self.root.winfo_screenwidth() - self.WINDOW_WIDTH) // 2)
        y = max(0, (self.root.winfo_screenheight() - self.WINDOW_HEIGHT) // 2)
        self.root.geometry(f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}+{x}+{y}")

    def _build_ui(self) -> None:
        content = ttk.Frame(self.root, padding=12)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(3, weight=1)

        ttk.Label(content, text="视频网址：").grid(row=0, column=0, sticky=tk.W, pady=(0, 8))
        self.url_entry = ttk.Entry(content)
        self.url_entry.grid(row=0, column=1, columnspan=2, sticky=tk.EW, pady=(0, 8))

        ttk.Label(content, text="保存目录：").grid(row=1, column=0, sticky=tk.W, pady=(0, 8))
        self.output_entry = ttk.Entry(content, textvariable=self.output_dir)
        self.output_entry.grid(row=1, column=1, sticky=tk.EW, pady=(0, 8))
        self.browse_button = ttk.Button(content, text="选择文件夹…", command=self._choose_directory)
        self.browse_button.grid(row=1, column=2, padx=(8, 0), pady=(0, 8))

        self.start_button = ttk.Button(content, text="开始下载", command=self._start_download)
        self.start_button.grid(row=2, column=0, columnspan=3, sticky=tk.EW, pady=(2, 10))

        log_frame = ttk.LabelFrame(content, text="运行日志", padding=6)
        log_frame.grid(row=3, column=0, columnspan=3, sticky=tk.NSEW)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log_view = ScrolledText(log_frame, wrap=tk.WORD, state=tk.DISABLED, height=16)
        self.log_view.grid(row=0, column=0, sticky=tk.NSEW)

        self.progress = ttk.Progressbar(content, mode="determinate", maximum=1)
        self.progress.grid(row=4, column=0, columnspan=3, sticky=tk.EW, pady=(10, 4))
        ttk.Label(content, textvariable=self.status).grid(row=5, column=0, columnspan=3, sticky=tk.W)

    def _choose_directory(self) -> None:
        initialdir = self.output_dir.get()
        if not Path(initialdir).is_dir():
            initialdir = str(Path.home())
        selected = filedialog.askdirectory(
            title="选择视频保存目录",
            initialdir=initialdir,
            mustexist=True,
        )
        if selected:
            self.output_dir.set(selected)

    def _start_download(self) -> None:
        url = self.url_entry.get().strip()
        output_dir = self.output_dir.get().strip()
        if not url:
            self.status.set("请填写视频网址")
            self.url_entry.focus_set()
            return
        if not output_dir:
            self.status.set("请选择保存目录")
            return

        self.start_button.configure(state=tk.DISABLED)
        self.browse_button.configure(state=tk.DISABLED)
        self.status.set("正在准备下载…")
        self.progress.configure(value=0, maximum=1)
        self._append_log(f"开始任务：{url}\n保存目录：{output_dir}")

        threading.Thread(
            target=self._download_worker,
            args=(url, output_dir),
            daemon=True,
        ).start()

    def _download_worker(self, url: str, output_dir: str) -> None:
        try:
            download_video(
                url,
                output_dir,
                log_callback=lambda message: self.events.put(("log", message)),
                progress_callback=lambda stage, current, total: self.events.put(
                    ("progress", stage, current, total)
                ),
            )
            self.events.put(("done",))
        except Exception:
            self.events.put(("error", traceback.format_exc()))

    def _process_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "log":
                    self._append_log(event[1])
                elif event[0] == "progress":
                    _, stage, current, total = event
                    self.progress.configure(maximum=max(total, 1), value=current)
                    self.status.set(f"{stage}：{current}/{total}")
                elif event[0] == "done":
                    self.status.set("任务完成")
                    self.start_button.configure(state=tk.NORMAL)
                    self.browse_button.configure(state=tk.NORMAL)
                elif event[0] == "error":
                    self._append_log("下载过程中发生错误：\n" + event[1])
                    self.status.set("下载失败，请查看日志")
                    self.start_button.configure(state=tk.NORMAL)
                    self.browse_button.configure(state=tk.NORMAL)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._process_events)

    def _append_log(self, message: str) -> None:
        self.log_view.configure(state=tk.NORMAL)
        self.log_view.insert(tk.END, message.rstrip() + "\n")
        self.log_view.see(tk.END)
        self.log_view.configure(state=tk.DISABLED)


def run() -> None:
    root = tk.Tk()
    DownloaderApp(root)
    root.mainloop()
