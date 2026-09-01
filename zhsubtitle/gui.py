"""Interactive Tkinter GUI for subtitle search, quick keyword switching, and selection."""

import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import List, Optional, Tuple

from .config import Config, load_config
from .guess import parse_video
from .logger import logger
from .models import SubtitleItem, VideoMeta
from .service import SubtitleService


class SubtitlePickerGui:
    """Tkinter-based subtitle search and download GUI window with Douban ID and Quick Search Chips."""

    def __init__(
        self,
        video_path: Optional[str] = None,
        initial_query: Optional[str] = None,
        config: Optional[Config] = None
    ):
        self.config = config or load_config()
        self.service = SubtitleService(self.config)
        self.video_path = video_path
        self.meta: Optional[VideoMeta] = parse_video(video_path) if video_path else None

        self.initial_query = initial_query
        self.results: List[SubtitleItem] = []
        self.selected_path: Optional[str] = None

        logger.info(f"[GUI] Initialized with video='{video_path}', custom_query='{initial_query}'")

        self._init_window()
        self._init_styles()
        self._create_widgets()

        # Start initial resolution / search
        self.root.after(100, self.start_initial_load)

    def _init_window(self) -> None:
        """Initialize main window properties."""
        self.root = tk.Tk()
        self.root.title("MPV Chinese Subtitle Downloader (SubHD & Zimuku)")
        self.root.geometry("920x580")
        self.root.minsize(760, 460)

        # Make window stay on top of MPV
        try:
            self.root.attributes("-topmost", True)
            self.root.lift()
        except Exception:
            pass

        # Keyboard shortcuts
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.bind("<Return>", lambda e: self.start_search())

        # Center window on screen
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f"+{x}+{y}")

    def _init_styles(self) -> None:
        """Configure modern dark theme palette and TTK widget styles."""
        self.bg_color = "#1e1e2e"
        self.fg_color = "#cdd6f4"
        self.panel_bg = "#252538"
        self.accent_color = "#89b4fa"
        self.btn_primary_bg = "#a6e3a1"
        self.btn_primary_fg = "#11111b"
        self.subtext_color = "#a6adc8"
        self.select_bg = "#45475a"
        self.chip_bg = "#313244"
        self.chip_fg = "#89dceb"

        self.root.configure(bg=self.bg_color)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("TFrame", background=self.bg_color)
        style.configure("Panel.TFrame", background=self.panel_bg)

        style.configure("TLabel", background=self.bg_color, foreground=self.fg_color, font=("Segoe UI", 9))
        style.configure("Title.TLabel", font=("Segoe UI", 11, "bold"), foreground=self.accent_color)
        style.configure("Sub.TLabel", foreground=self.subtext_color, font=("Segoe UI", 8))
        style.configure("Status.TLabel", background=self.panel_bg, foreground=self.subtext_color, font=("Segoe UI", 9))
        style.configure("TCheckbutton", background=self.bg_color, foreground=self.fg_color, font=("Segoe UI", 9))

        style.configure(
            "Treeview",
            background="#181825",
            foreground=self.fg_color,
            fieldbackground="#181825",
            rowheight=26,
            font=("Segoe UI", 9)
        )
        style.configure(
            "Treeview.Heading",
            background=self.panel_bg,
            foreground=self.accent_color,
            font=("Segoe UI", 9, "bold")
        )
        style.map("Treeview", background=[("selected", self.select_bg)], foreground=[("selected", "#ffffff")])

    def _create_widgets(self) -> None:
        """Create header, search bar, quick keyword buttons, results treeview, and action buttons."""
        main_container = ttk.Frame(self.root, padding=12)
        main_container.pack(fill=tk.BOTH, expand=True)

        # 1. Search Header Frame
        search_frame = ttk.Frame(main_container)
        search_frame.pack(fill=tk.X, pady=(0, 8))

        header_text = "Subtitle Search"
        if self.meta and self.meta.raw_name:
            header_text += f" - {self.meta.raw_name}"
        ttk.Label(search_frame, text=header_text, style="Title.TLabel").pack(anchor=tk.W, pady=(0, 6))

        # Search input row
        input_row = ttk.Frame(search_frame)
        input_row.pack(fill=tk.X)

        default_text = self.initial_query or (self.meta.title if self.meta else "")
        self.query_var = tk.StringVar(value=default_text)
        self.query_entry = tk.Entry(
            input_row,
            textvariable=self.query_var,
            font=("Segoe UI", 10),
            bg="#313244",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief=tk.FLAT,
            bd=5
        )
        self.query_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        # Provider Checkboxes
        self.use_subhd_var = tk.BooleanVar(value=self.config.is_provider_enabled("subhd"))
        self.use_zimuku_var = tk.BooleanVar(value=self.config.is_provider_enabled("zimuku"))

        ttk.Checkbutton(input_row, text="SubHD", variable=self.use_subhd_var).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(input_row, text="Zimuku", variable=self.use_zimuku_var).pack(side=tk.LEFT, padx=4)

        # Search Button
        self.search_btn = tk.Button(
            input_row,
            text=" Search ",
            command=self.start_search,
            bg=self.accent_color,
            fg="#11111b",
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            padx=12,
            pady=4,
            cursor="hand2"
        )
        self.search_btn.pack(side=tk.LEFT, padx=(8, 0))

        # 2. Quick Keyword Chips Bar
        self.chips_frame = ttk.Frame(search_frame)
        self.chips_frame.pack(fill=tk.X, pady=(6, 0))
        self._render_chips()

        # 3. Results Table Area
        table_frame = ttk.Frame(main_container)
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("provider", "format", "source", "fansub", "title", "score")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")

        self.tree.heading("provider", text="Source")
        self.tree.heading("format", text="Format")
        self.tree.heading("source", text="Type")
        self.tree.heading("fansub", text="Fansub / Group")
        self.tree.heading("title", text="Subtitle Name / Release")
        self.tree.heading("score", text="Match")

        self.tree.column("provider", width=80, anchor=tk.CENTER, stretch=False)
        self.tree.column("format", width=70, anchor=tk.CENTER, stretch=False)
        self.tree.column("source", width=80, anchor=tk.CENTER, stretch=False)
        self.tree.column("fansub", width=120, anchor=tk.W, stretch=False)
        self.tree.column("title", width=460, anchor=tk.W, stretch=True)
        self.tree.column("score", width=60, anchor=tk.CENTER, stretch=False)

        # Scrollbars
        v_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=v_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", lambda e: self.on_download_selected())

        # 4. Bottom Status and Action Bar
        bottom_frame = ttk.Frame(main_container)
        bottom_frame.pack(fill=tk.X, pady=(10, 0))

        self.status_var = tk.StringVar(value="Initializing subtitle auto-resolution...")
        self.status_label = ttk.Label(bottom_frame, textvariable=self.status_var, style="Status.TLabel")
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.download_btn = tk.Button(
            bottom_frame,
            text=" Download & Load Subtitle ",
            command=self.on_download_selected,
            bg=self.btn_primary_bg,
            fg=self.btn_primary_fg,
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            padx=14,
            pady=5,
            cursor="hand2"
        )
        self.download_btn.pack(side=tk.RIGHT, padx=(8, 0))

        cancel_btn = tk.Button(
            bottom_frame,
            text=" Cancel ",
            command=self.root.destroy,
            bg="#313244",
            fg=self.fg_color,
            font=("Segoe UI", 9),
            relief=tk.FLAT,
            padx=10,
            pady=5,
            cursor="hand2"
        )
        cancel_btn.pack(side=tk.RIGHT)

    def _render_chips(self) -> None:
        """Render quick search keyword chip buttons."""
        for child in self.chips_frame.winfo_children():
            child.destroy()

        if not self.meta:
            return

        chips = self.meta.get_search_chips()
        if not chips:
            return

        lbl = ttk.Label(self.chips_frame, text="Quick Search: ", style="Sub.TLabel")
        lbl.pack(side=tk.LEFT, padx=(0, 4))

        for label, query_val in chips:
            btn = tk.Button(
                self.chips_frame,
                text=label,
                command=lambda q=query_val: self._on_chip_clicked(q),
                bg=self.chip_bg,
                fg=self.chip_fg,
                font=("Segoe UI", 8),
                relief=tk.FLAT,
                padx=6,
                pady=1,
                cursor="hand2",
                activebackground="#45475a",
                activeforeground="#ffffff"
            )
            btn.pack(side=tk.LEFT, padx=3)

    def _on_chip_clicked(self, query_val: str) -> None:
        """Handle click on a quick search option chip."""
        self.query_var.set(query_val)
        self.start_search()

    def start_initial_load(self) -> None:
        """Trigger full automatic resolution (Zimuku Work + SubHD Douban ID bridge) on launch."""
        if self.initial_query:
            self.start_search()
            return

        if not self.meta:
            return

        self.status_var.set("Auto-resolving work via Zimuku & SubHD Douban Bridge...")
        self.search_btn.config(state=tk.DISABLED)
        self.tree.delete(*self.tree.get_children())

        threading.Thread(
            target=self._async_auto_resolve,
            daemon=True
        ).start()

    def _async_auto_resolve(self) -> None:
        """Run two-stage resolution in background thread."""
        try:
            results, updated_meta = self.service.auto_resolve(self.meta)
            self.meta = updated_meta
            self.root.after(0, self._handle_auto_resolve_complete, results)
        except Exception as e:
            logger.error(f"[GUI] Auto-resolve error: {e}")
            self.root.after(0, self._handle_search_error, str(e))

    def _handle_auto_resolve_complete(self, results: List[SubtitleItem]) -> None:
        """Update GUI after auto-resolve finishes."""
        # Update search box to Douban ID (or Chinese title) if found
        if self.meta.douban_id:
            self.query_var.set(self.meta.douban_id)
        elif self.meta.cn_title:
            if self.meta.is_tv and self.meta.season:
                from .models import to_cn_season
                self.query_var.set(f"{self.meta.cn_title} {to_cn_season(self.meta.season)}")
            else:
                self.query_var.set(self.meta.cn_title)

        # Refresh the quick keyword chips with extracted IDs
        self._render_chips()

        # Populate the treeview with all results
        self._populate_results(results)

    def start_search(self) -> None:
        """Trigger search for the query currently in the entry box."""
        query = self.query_var.get().strip()
        if not query:
            return

        providers = []
        if self.use_subhd_var.get():
            providers.append("subhd")
        if self.use_zimuku_var.get():
            providers.append("zimuku")

        if not providers:
            messagebox.showwarning("Warning", "Please enable at least one provider (SubHD or Zimuku).")
            return

        self.status_var.set(f"Searching '{query}' on {', '.join(p.upper() for p in providers)}...")
        self.search_btn.config(state=tk.DISABLED)
        self.tree.delete(*self.tree.get_children())
        logger.info(f"[GUI] Searching for '{query}' on {providers}")

        threading.Thread(
            target=self._async_search,
            args=(query, providers),
            daemon=True
        ).start()

    def _async_search(self, query: str, providers: List[str]) -> None:
        """Background search runner."""
        try:
            results = self.service.search(query, meta=self.meta, provider_names=providers)
            self.root.after(0, self._populate_results, results)
        except Exception as e:
            logger.error(f"[GUI] Search error: {e}")
            self.root.after(0, self._handle_search_error, str(e))

    def _populate_results(self, results: List[SubtitleItem]) -> None:
        """Populate treeview with search results."""
        self.results = results
        self.search_btn.config(state=tk.NORMAL)

        if not results:
            self.status_var.set("No subtitles found. Try clicking one of the Quick Search options above.")
            logger.info("[GUI] Search returned 0 results.")
            return

        for idx, item in enumerate(results):
            tags = item.tags
            fmt_display = "/".join(f.upper() for f in tags.fmt) if tags.fmt else "-"
            src_display = "/".join(s.capitalize() for s in tags.source) if tags.source else "-"
            fansub_display = tags.fansub or "-"
            score_display = f"{int(item.score)}"

            self.tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    item.provider.upper(),
                    fmt_display,
                    src_display,
                    fansub_display,
                    item.title,
                    score_display
                )
            )

        first_item = self.tree.get_children()
        if first_item:
            self.tree.selection_set(first_item[0])
            self.tree.focus(first_item[0])

        self.status_var.set(f"Found {len(results)} subtitles. Select an item and click Download.")
        logger.info(f"[GUI] Populated {len(results)} items in table.")

    def _handle_search_error(self, err_msg: str) -> None:
        self.search_btn.config(state=tk.NORMAL)
        self.status_var.set(f"Search failed: {err_msg}")

    def on_download_selected(self) -> None:
        """Handle download button click or row double-click."""
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Hint", "Please select a subtitle from the list first.")
            return

        index = int(selected[0])
        if index < 0 or index >= len(self.results):
            return

        item = self.results[index]
        self.status_var.set(f"Downloading [{item.provider.upper()}] {item.title}...")
        self.download_btn.config(state=tk.DISABLED)
        logger.info(f"[GUI] User selected #{index}: [{item.provider.upper()}] {item.title}")

        threading.Thread(
            target=self._async_download,
            args=(item,),
            daemon=True
        ).start()

    def _async_download(self, item: SubtitleItem) -> None:
        """Background download runner."""
        try:
            res = self.service.download_and_extract(item, video_path=self.video_path, meta=self.meta)
            self.root.after(0, self._handle_download_complete, res)
        except Exception as e:
            logger.error(f"[GUI] Download error: {e}")
            self.root.after(0, self._handle_download_error, str(e))

    def _handle_download_complete(self, result) -> None:
        self.download_btn.config(state=tk.NORMAL)
        if result.success:
            self.selected_path = result.saved_path
            logger.info(f"[GUI] Download success, saved to: {result.saved_path}")
            print(f"[SUBTITLE_LOADED]{result.saved_path}")
            sys.stdout.flush()
            self.root.destroy()
        else:
            logger.warning(f"[GUI] Download failed: {result.error_msg}")
            messagebox.showerror("Download Error", result.error_msg or "Failed to download subtitle.")
            self.status_var.set(f"Error: {result.error_msg}")

    def _handle_download_error(self, err_msg: str) -> None:
        self.download_btn.config(state=tk.NORMAL)
        messagebox.showerror("Download Error", f"Unexpected error during download:\n{err_msg}")
        self.status_var.set(f"Download failed: {err_msg}")

    def run(self) -> Optional[str]:
        """Launch the GUI loop and return the downloaded subtitle file path."""
        self.root.mainloop()
        return self.selected_path


def launch_gui(video_path: Optional[str] = None, initial_query: Optional[str] = None) -> Optional[str]:
    """Helper function to run the GUI."""
    app = SubtitlePickerGui(video_path=video_path, initial_query=initial_query)
    return app.run()
