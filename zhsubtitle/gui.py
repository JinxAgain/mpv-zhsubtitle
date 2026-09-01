"""Interactive Tkinter GUI for subtitle search, quick keyword switching, and selection."""

import os
import re
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict, List, Optional, Tuple
import urllib.parse
import webbrowser

from bs4 import BeautifulSoup
import requests

from .config import Config, load_config
from .guess import parse_video
from .logger import logger
from .models import SubtitleItem, VideoMeta
from .service import SubtitleService


class TreeviewTooltip:
    """Floating tooltip for Treeview rows displaying full subtitle release names and metadata."""

    def __init__(self, root: tk.Tk, tree: ttk.Treeview, get_item_fn):
        self.root = root
        self.tree = tree
        self.get_item_fn = get_item_fn
        self.tip_window: Optional[tk.Toplevel] = None
        self.current_iid: Optional[str] = None
        self.scheduled_id: Optional[str] = None

        self.tree.bind("<Motion>", self._on_motion)
        self.tree.bind("<Leave>", self._on_leave)
        self.tree.bind("<ButtonPress>", self._on_leave)

    def _on_motion(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid:
            self._hide()
            self.current_iid = None
            return

        if iid != self.current_iid:
            self.current_iid = iid
            self._hide()
            if self.scheduled_id:
                self.tree.after_cancel(self.scheduled_id)
            self.scheduled_id = self.tree.after(250, lambda: self._show(event.x_root, event.y_root, iid))

    def _show(self, x: int, y: int, iid: str) -> None:
        item: Optional[SubtitleItem] = self.get_item_fn(iid)
        if not item or self.tip_window:
            return

        self.tip_window = tk.Toplevel(self.root)
        self.tip_window.wm_overrideredirect(True)

        # Ensure tooltip stays on top of topmost main window
        try:
            self.tip_window.wm_attributes("-topmost", True)
            self.tip_window.attributes("-topmost", True)
            self.tip_window.lift()
        except Exception:
            pass

        frame = tk.Frame(self.tip_window, bg="#11111b", bd=1, relief=tk.SOLID)
        frame.pack(fill=tk.BOTH, expand=True)

        # Full Title / Release
        title_lbl = tk.Label(
            frame,
            text=item.title,
            bg="#11111b",
            fg="#89b4fa",
            font=("Segoe UI", 9, "bold"),
            wraplength=540,
            justify=tk.LEFT,
            padx=8,
            pady=4
        )
        title_lbl.pack(anchor=tk.W)

        # Metadata rows
        uploader_disp = item.tags.display_uploader_or_group()
        info_lines = [
            f"Source: {item.provider.upper()} (ID: {item.id})",
            f"Language: {item.tags.display_lang()}  |  Format: {'/'.join(f.upper() for f in item.tags.fmt) or '-'}",
            f"Type: {item.tags.display_type()}  |  Uploader / Group: {uploader_disp}"
        ]
        if item.tags.fansub and item.tags.fansub != uploader_disp and item.tags.fansub not in ("见字幕文件", "见片头", "见压缩包", "-"):
            info_lines.append(f"Fansub / Studio: {item.tags.fansub}")

        if item.rate_stars or item.rate > 0:
            info_lines.append(f"Rating: {item.display_rating}  |  Downloads: {item.downloads_count}")
        elif item.downloads_count > 0:
            info_lines.append(f"Downloads: {item.downloads_count}")

        info_lbl = tk.Label(
            frame,
            text="\n".join(info_lines),
            bg="#11111b",
            fg="#cdd6f4",
            font=("Segoe UI", 8),
            justify=tk.LEFT,
            padx=8,
            pady=4
        )
        info_lbl.pack(anchor=tk.W)

        self.tip_window.update_idletasks()
        w = self.tip_window.winfo_width()
        h = self.tip_window.winfo_height()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        pos_x = min(x + 16, screen_w - w - 10)
        pos_y = min(y + 18, screen_h - h - 10)
        self.tip_window.wm_geometry(f"+{pos_x}+{pos_y}")

    def _on_leave(self, event=None) -> None:
        self._hide()
        self.current_iid = None
        if self.scheduled_id:
            self.tree.after_cancel(self.scheduled_id)
            self.scheduled_id = None

    def _hide(self) -> None:
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None


class SubtitlePickerGui:
    """Tkinter-based subtitle search and download GUI window with Douban ID, Quick Chips, Context Menu, and Column Sorting."""

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
        self.sort_column_state = {"col": "score", "reverse": True}

        logger.info(f"[GUI] Initialized with video='{video_path}', custom_query='{initial_query}'")

        self._init_window()
        self._init_styles()
        self._create_widgets()
        self._init_context_menu()
        self._init_tooltip()

        # Start initial resolution / search
        self.root.after(100, self.start_initial_load)

    def _init_window(self) -> None:
        """Initialize main window properties."""
        self.root = tk.Tk()
        self.root.title("MPV Chinese Subtitle Downloader (SubHD & Zimuku)")
        self.root.geometry("1060x620")
        self.root.minsize(880, 480)

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

        self.columns_meta = {
            "provider": ("Source", 65, tk.CENTER, False),
            "lang": ("Lang", 75, tk.CENTER, False),
            "format": ("Format", 60, tk.CENTER, False),
            "type": ("Type", 75, tk.CENTER, False),
            "fansub": ("Uploader / Group", 120, tk.W, False),
            "title": ("Subtitle Name / Release", 420, tk.W, True),
            "rating": ("Rating", 105, tk.CENTER, False),
            "score": ("Match", 55, tk.CENTER, False)
        }

        columns = tuple(self.columns_meta.keys())
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")

        for col, (header_label, col_w, col_anchor, is_stretch) in self.columns_meta.items():
            self.tree.heading(col, text=header_label, command=lambda c=col: self._sort_by_column(c))
            self.tree.column(col, width=col_w, anchor=col_anchor, stretch=is_stretch)

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

    def _init_context_menu(self) -> None:
        """Create right-click context menu for table rows."""
        self.context_menu = tk.Menu(self.root, tearoff=0, bg="#252538", fg="#cdd6f4", activebackground="#45475a", activeforeground="#ffffff")
        self.context_menu.add_command(label="🔍 View Details", command=self.on_view_details)
        self.context_menu.add_command(label="🌐 Open in Browser", command=self.on_open_browser)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="⬇️ Download & Load Subtitle", command=self.on_download_selected)

        self.tree.bind("<Button-3>", self._show_context_menu)
        self.tree.bind("<Button-2>", self._show_context_menu)

    def _show_context_menu(self, event) -> None:
        """Display right-click context menu on row under cursor."""
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            try:
                self.context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.context_menu.grab_release()

    def _init_tooltip(self) -> None:
        """Attach hover tooltip to Treeview."""
        self.tooltip = TreeviewTooltip(self.root, self.tree, self._get_item_by_iid)

    def _get_item_by_iid(self, iid: str) -> Optional[SubtitleItem]:
        try:
            idx = int(iid)
            if 0 <= idx < len(self.results):
                return self.results[idx]
        except Exception:
            pass
        return None

    def _sort_by_column(self, col: str) -> None:
        """Sort search results when a column header is clicked."""
        if not self.results:
            return

        current_col = self.sort_column_state.get("col")
        current_rev = self.sort_column_state.get("reverse", False)

        new_rev = not current_rev if current_col == col else (col in ("score", "rating"))
        self.sort_column_state = {"col": col, "reverse": new_rev}

        def _sort_key(item: SubtitleItem):
            if col == "provider":
                return item.provider.lower()
            elif col == "lang":
                return item.tags.display_lang()
            elif col == "format":
                return "/".join(item.tags.fmt)
            elif col == "type":
                return item.tags.display_type()
            elif col == "fansub":
                return item.tags.display_uploader_or_group().lower()
            elif col == "title":
                return item.title.lower()
            elif col == "rating":
                return item.rate
            elif col == "score":
                return item.score
            return 0

        self.results.sort(key=_sort_key, reverse=new_rev)

        # Update headings with sort indicator
        for c, (orig_name, _, _, _) in self.columns_meta.items():
            if c == col:
                indicator = " ▼" if new_rev else " ▲"
                self.tree.heading(c, text=f"{orig_name}{indicator}")
            else:
                self.tree.heading(c, text=orig_name)

        self._render_tree_rows()

    def on_view_details(self) -> None:
        """Open a dedicated modal dialog showing detailed subtitle metadata and async remarks."""
        selected = self.tree.selection()
        if not selected:
            return
        item = self._get_item_by_iid(selected[0])
        if not item:
            return

        detail_win = tk.Toplevel(self.root)
        detail_win.title(f"Subtitle Details - [{item.provider.upper()}] {item.id}")
        detail_win.geometry("680x480")
        detail_win.minsize(560, 380)
        detail_win.configure(bg=self.bg_color)
        detail_win.transient(self.root)

        try:
            detail_win.wm_attributes("-topmost", True)
            detail_win.attributes("-topmost", True)
            detail_win.lift()
        except Exception:
            pass

        # Center detail dialog relative to main window
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 340
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 240
        detail_win.geometry(f"+{max(0, x)}+{max(0, y)}")

        container = ttk.Frame(detail_win, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        # Header Title
        title_box = tk.Text(container, wrap=tk.WORD, height=2, bg="#181825", fg="#89b4fa", font=("Segoe UI", 10, "bold"), bd=1, relief=tk.SOLID)
        title_box.insert("1.0", item.title)
        title_box.config(state=tk.DISABLED)
        title_box.pack(fill=tk.X, pady=(0, 10))

        # Details Grid
        grid_frame = ttk.Frame(container)
        grid_frame.pack(fill=tk.X, pady=(0, 10))

        details = [
            ("Source Provider:", f"{item.provider.upper()}"),
            ("Subtitle ID:", f"{item.id}"),
            ("Language:", f"{item.tags.display_lang()}"),
            ("Format:", f"{'/'.join(f.upper() for f in item.tags.fmt) or '-'}"),
            ("Type / Source:", f"{item.tags.display_type()}"),
            ("Uploader:", f"{item.tags.uploader or '-'}"),
            ("Fansub / Studio:", f"{item.tags.fansub or '-'}"),
            ("Rating Stars:", f"{item.display_rating}"),
            ("Downloads Count:", f"{item.downloads_count or '-'}"),
            ("Match Score:", f"{int(item.score)}")
        ]

        # 2-column layout for metadata
        for idx, (label, val) in enumerate(details):
            r = idx // 2
            c = (idx % 2) * 2
            lbl = ttk.Label(grid_frame, text=label, font=("Segoe UI", 9, "bold"), foreground=self.subtext_color)
            lbl.grid(row=r, column=c, sticky=tk.W, pady=2, padx=(0, 6))

            val_lbl = ttk.Label(grid_frame, text=val, font=("Segoe UI", 9), foreground=self.fg_color)
            val_lbl.grid(row=r, column=c + 1, sticky=tk.W, pady=2, padx=(0, 16))

        # Asynchronous Description / Remarks Text Area
        desc_label = ttk.Label(container, text="Subtitle Description & Remarks:", font=("Segoe UI", 9, "bold"), foreground=self.accent_color)
        desc_label.pack(anchor=tk.W, pady=(4, 2))

        desc_box = tk.Text(
            container,
            wrap=tk.WORD,
            height=6,
            bg="#181825",
            fg="#cdd6f4",
            font=("Segoe UI", 9),
            bd=1,
            relief=tk.SOLID,
            padx=6,
            pady=6
        )
        desc_box.insert("1.0", "Loading detailed remarks from webpage...\n")
        desc_box.config(state=tk.DISABLED)
        desc_box.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        def _fetch_description_async():
            try:
                remarks = "No additional description provided."
                prov = self.service.providers.get(item.provider)
                if prov and item.page_url:
                    resp = getattr(prov, "_fetch_page", None)
                    if callable(resp):
                        r = prov._fetch_page(item.page_url)
                    else:
                        r = prov.session.get(item.page_url, timeout=5)

                    if r and r.status_code == 200:
                        soup = BeautifulSoup(r.content.decode("utf-8", "ignore"), "html.parser")
                        if item.provider == "subhd":
                            desc_el = soup.select_one("div.subtitle-description, div.lh-lg.subtitle-description")
                            if desc_el:
                                remarks = desc_el.get_text("\n", strip=True)
                        elif item.provider == "zimuku":
                            fieldset = soup.find("fieldset")
                            if fieldset:
                                remarks = fieldset.get_text("\n", strip=True)

                def _update_desc():
                    if desc_box.winfo_exists():
                        desc_box.config(state=tk.NORMAL)
                        desc_box.delete("1.0", tk.END)
                        desc_box.insert("1.0", remarks)
                        desc_box.config(state=tk.DISABLED)

                detail_win.after(0, _update_desc)
            except Exception as e:
                logger.debug(f"[GUI] Detail fetch error: {e}")

        threading.Thread(target=_fetch_description_async, daemon=True).start()

        # Action Buttons inside Details
        btn_frame = ttk.Frame(container)
        btn_frame.pack(fill=tk.X)

        browser_btn = tk.Button(
            btn_frame,
            text=" 🌐 Open in Browser ",
            command=lambda: webbrowser.open(item.page_url),
            bg="#313244",
            fg="#89dceb",
            font=("Segoe UI", 9),
            relief=tk.FLAT,
            padx=10,
            pady=4,
            cursor="hand2"
        )
        browser_btn.pack(side=tk.LEFT)

        dl_btn = tk.Button(
            btn_frame,
            text=" ⬇️ Download & Load ",
            command=lambda: [detail_win.destroy(), self.on_download_selected()],
            bg=self.btn_primary_bg,
            fg=self.btn_primary_fg,
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            padx=12,
            pady=4,
            cursor="hand2"
        )
        dl_btn.pack(side=tk.RIGHT)

    def on_open_browser(self) -> None:
        """Open the webpage of the currently selected subtitle in the system default browser."""
        selected = self.tree.selection()
        if not selected:
            return
        item = self._get_item_by_iid(selected[0])
        if item and item.page_url:
            logger.info(f"[GUI] Opening URL in browser: {item.page_url}")
            webbrowser.open(item.page_url)

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

        self._render_tree_rows()

        first_item = self.tree.get_children()
        if first_item:
            self.tree.selection_set(first_item[0])
            self.tree.focus(first_item[0])

        self.status_var.set(f"Found {len(results)} subtitles. Select an item and click Download, or right-click for details.")
        logger.info(f"[GUI] Populated {len(results)} items in table.")

    def _render_tree_rows(self) -> None:
        """Render all rows from self.results into Treeview."""
        self.tree.delete(*self.tree.get_children())
        for idx, item in enumerate(self.results):
            tags = item.tags
            lang_display = tags.display_lang()
            fmt_display = "/".join(f.upper() for f in tags.fmt) if tags.fmt else "-"
            type_display = tags.display_type()
            uploader_group_display = tags.display_uploader_or_group()
            rating_display = item.display_rating
            score_display = f"{int(item.score)}"

            self.tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    item.provider.upper(),
                    lang_display,
                    fmt_display,
                    type_display,
                    uploader_group_display,
                    item.title,
                    rating_display,
                    score_display
                )
            )

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
            logger.info(f"[GUI] Download success, saved primary to: {result.saved_path}")
            # Emit all extracted secondary subtitle tracks
            for p in getattr(result, "all_saved_paths", []):
                if p != result.saved_path:
                    print(f"[SUBTITLE_EXTRACTED]{p}")
            # Emit primary selected subtitle
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
