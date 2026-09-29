"""Specio Catalog — main window (read-only catalog browser).
The window never writes to the catalog database: it only opens it with
``mode=ro`` through :class:`core.catalog_db.CatalogDB` and displays the
results produced by :func:`core.search.search_species`.
"""
from __future__ import annotations
import math
import os
import re
import sys
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import quote
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from core import lang
from core.ask import MAX_PROFILES, QaTurn, build_qa_prompt, detect_group
from core.chat_format import parse_markup
from core.describe import (
    DescribeReply, build_menu, build_prompt, keep_asked_keywords, parse_reply,
)
from core.ollama import OllamaError, check_ollama, generate, get_response, list_models
from core.catalog_db import CatalogDB, CatalogNotReady
from core.config import auto_detect_root, configured_catalog_root, load_settings, save_catalog_root, save_setting
from core.determinator import (
    Constraint,
    applicable_fields,
    determine,
    filter_field_labels,
    key_step,
    match_type_for,
    resolve_field,
    value_options,
)
from core.profile_normalize import format_structured_items, load_vocab
from core.search import CRITERIA, SpeciesResult, list_categories, normalize, search_species
try:  # Pillow renders JPG photos inside Tk
    from PIL import Image, ImageTk
    PIL_OK = True
except Exception:  # pragma: no cover - Pillow is in requirements.txt
    PIL_OK = False
PHOTO_MAX = (560, 380)

# Every spelling of "Ctrl + wheel" Windows can send. A precision trackpad
# reports <Control-MouseWheel> with a delta, a notched wheel reports
# <Control-Button-4/5>; a window that binds only one of them is dead on the
# hardware that speaks the other. Kept in one place so the main window and the
# reading window cannot drift apart again.
_ZOOM_WHEELS = ("<Control-MouseWheel>", "<Control-Button-4>", "<Control-Button-5>")

# Web lookups — the same 🌐 CoL / 🌐 WIKIPEDIA buttons as SpecioIdentify.
COL_SEARCH_URL = "https://www.catalogueoflife.org/data/search"
WIKIPEDIA_SPECIES_URL = "https://en.wikipedia.org/wiki/"
class CatalogBrowser:
    """Read-only browser over the catalog of a SpecioIdentify project."""
    def __init__(self, root: tk.Tk) -> None:
        self.win = root
        self.win.title(lang.t("app_title"))
        self.win.geometry("1150x720")
        self.win.minsize(980, 620)
        # Windows lets a window be dragged so its bottom edge goes under the
        # taskbar, and the row holding the model selector and the ask button is
        # packed at the very bottom - so it vanished and took the folder, CoL
        # and Wikipedia buttons with it. The window is pulled back instead of
        # letting its last row leave the work area.
        #
        # None means "not built yet": <Configure> fires hundreds of times while
        # the widgets are still being created, and reacting then would run this
        # against a window that has no size and no position worth correcting.
        self._placing: bool | None = None
        self._work_area_cache: tuple[int, int] | None = None
        self.win.bind("<Configure>", self._keep_on_screen)
        self.db: CatalogDB | None = None
        self.results: list[SpeciesResult] = []
        self.photos: list = []
        self.photo_index = 0
        self.current: SpeciesResult | None = None
        self._photo_image = None  # keep a reference so Tk does not GC the image
        self._crit_map: dict[str, str] = {}
        self._crit_key: str = next(iter(CRITERIA))
        self._cat_values: list[str | None] = []
        self._cat_displays: list[str] = []
        self._labels: list[tuple[tk.Widget, str]] = []
        self._view_map: dict[str, str] = {}
        self._view_mode: str = "tree"
        self._tree_ids: dict[str, str] = {}
        # Visible dividers between the main blocks + the active drag state.
        self._dividers: list[tk.Widget] = []
        self._drag = None
        # Phase A determinator: trait-filter panel state.
        self.det_active = False
        self._det_constraints: list[Constraint] = []
        self._det_status: dict[str, str] = {}
        self._det_field_map: dict[str, str] = {}
        self._det_base: list[SpeciesResult] = []
        self.det_rows: list[dict] = []
        # Phase B — guided dichotomous key inside the determinator panel.
        self._det_mode = "free"             # "free" rows | "key" guided key
        self._key_answers: list[dict] = []   # {"field","label","value"|None}
        self._det_key_current = None         # KeyStep being answered, if any
        # Group node iid -> full taxon path (kingdom..genus); lets a
        # right-click find the node inside the whole-catalog tree and keeps
        # identically named taxa under different parents apart.
        self._node_path: dict[str, tuple[str, ...]] = {}
        self._full_tree_cache: dict | None = None  # whole-catalog taxonomy
        self._aborted = False
        # First _do_search() runs at startup: keep the tree collapsed then.
        self._first_search_done = False
        self.suggestions: list[str] = []
        self.text_zoom_size = 10  # Ctrl+wheel page zoom (SpecioIdentify-style)
        self._open_catalog()
        self._build()
        self._refresh_language()
        self._do_search()
        if self.db is None:
            self.status_var.set(lang.t("status_not_open"))
    # ------------------------------------------------------- catalog opening
    def _open_catalog(self) -> None:
        """Configured root first, then auto-detect, then ask the user."""
        candidates: list[Path] = []
        configured = configured_catalog_root()
        if configured is not None:
            candidates.append(configured)
        auto = auto_detect_root()
        if auto is not None and auto not in candidates:
            candidates.append(auto)
        for candidate in candidates:
            try:
                self.db = CatalogDB(candidate)
            except CatalogNotReady:
                continue
            if configured is None or candidate != configured:
                save_catalog_root(candidate)
            return
        while self.db is None and not self._aborted:
            candidate = self._ask_root()
            if candidate is None:
                self._aborted = True
                break
            try:
                self.db = CatalogDB(candidate)
            except CatalogNotReady as exc:
                messagebox.showerror(
                    lang.t("db_error_title"),
                    lang.t("status_open_fail", err=exc),
                )
            else:
                save_catalog_root(candidate)
    def _ask_root(self) -> Path | None:
        """Ask for the SpecioIdentify folder; None means the user cancelled."""
        messagebox.showinfo(lang.t("choose_root_title"), lang.t("choose_root_msg"))
        chosen = filedialog.askdirectory(title=lang.t("choose_root_title"))
        if not chosen:
            return None
        path = Path(chosen)
        if not (path / "output" / "catalog.db").is_file():
            messagebox.showerror(
                lang.t("db_error_title"), lang.t("invalid_root_msg")
            )
            return None
        return path
    # ------------------------------------------------------------- widgets
    def _build(self) -> None:
        self.status_var = tk.StringVar(value="")
        top = ttk.Frame(self.win, padding=(8, 6))
        top.pack(fill="x")
        # The app names itself, as Specio Identify does. The left half of this
        # row was empty once the language switch moved to the status bar, and
        # an unnamed window gives no clue what is open when several are.
        self.brand_label = ttk.Label(
            top, text=lang.t("brand_name"), font=("Segoe UI", 13, "bold")
        )
        self.brand_label.pack(side="left")
        self.brand_sub = ttk.Label(
            top, text=lang.t("brand_sub"), foreground="#666666"
        )
        self.brand_sub.pack(side="left", padx=(8, 0))
        self.lang_var = tk.StringVar(value=lang.current_language())
        self.change_btn = ttk.Button(
            top, text=lang.t("change_catalog_btn"), command=self._on_change_catalog
        )
        self.change_btn.pack(side="right")
        # Search toolbar + autocomplete list share one vertical container so
        # suggestions always appear directly under the search entry.
        self.search_area = ttk.Frame(self.win)
        self.search_area.pack(fill="x")
        search = ttk.Frame(self.search_area, padding=(8, 0))
        search.pack(fill="x")
        self.search_label = ttk.Label(search, text=lang.t("search_lbl"))
        self.search_label.pack(side="left")
        self.query_var = tk.StringVar()
        self.query_entry = ttk.Entry(search, textvariable=self.query_var, width=32)
        self.query_entry.pack(side="left", padx=(4, 8))
        self.query_entry.bind("<Return>", lambda _e: self._do_search())
        self.query_entry.bind("<KeyRelease>", self._on_search_keyrelease)
        self.criteria_label = ttk.Label(search, text=lang.t("criteria_lbl"))
        self.criteria_label.pack(side="left", padx=(8, 4))
        self.crit_box = ttk.Combobox(search, state="readonly", width=20, values=[])
        self.crit_box.pack(side="left", padx=(0, 8))
        self.crit_box.bind("<<ComboboxSelected>>", lambda _e: self._do_search())
        self.category_label = ttk.Label(search, text=lang.t("category_lbl"))
        self.category_label.pack(side="left", padx=(8, 4))
        self.cat_box = ttk.Combobox(search, state="readonly", width=16, values=[])
        self.cat_box.pack(side="left", padx=(0, 8))
        self.cat_box.bind("<<ComboboxSelected>>", self._on_category_changed)
        self.search_btn = ttk.Button(
            search, text=lang.t("search_btn"), command=self._do_search
        )
        self.search_btn.pack(side="left")
        self.det_toggle_btn = ttk.Button(
            search, text=lang.t("det_btn"), command=self._toggle_determinator
        )
        self.det_toggle_btn.pack(side="left", padx=(8, 0))
        # Remember the toolbar row: the determinator panel packs right
        # below it (before the autocomplete suggestion list).
        self.search_frame = search
        # Determinator panel (Phase A): hidden until toggled; constraint
        # rows are created on demand by _det_add_row(). Phase B adds the
        # guided dichotomous key as a second mode of the same panel.
        self.det_panel = ttk.Frame(self.search_area, padding=(8, 4))
        self.det_title = ttk.Label(self.det_panel, text=lang.t("det_title"))
        self.det_title.pack(anchor="w")
        self._det_mode_var = tk.StringVar(value="free")
        self.det_mode_frame = ttk.Frame(self.det_panel)
        self.det_mode_frame.pack(fill="x", pady=(2, 0))
        self.det_mode_free_radio = ttk.Radiobutton(
            self.det_mode_frame, text=lang.t("det_mode_free"),
            value="free", variable=self._det_mode_var,
            command=self._det_mode_changed,
        )
        self.det_mode_free_radio.pack(side="left")
        self.det_mode_key_radio = ttk.Radiobutton(
            self.det_mode_frame, text=lang.t("det_mode_key"),
            value="key", variable=self._det_mode_var,
            command=self._det_mode_changed,
        )
        self.det_mode_key_radio.pack(side="left", padx=(12, 0))
        self.det_rows_frame = ttk.Frame(self.det_panel)
        self.det_rows_frame.pack(fill="x", pady=(2, 0))
        self.det_add_btn = ttk.Button(
            self.det_panel, text=lang.t("det_add"), command=self._det_add_row
        )
        self.det_add_btn.pack(anchor="w", pady=(4, 0))
        # Guided-key view: created now, packed only in key mode.
        self.det_key_frame = ttk.Frame(self.det_panel, padding=(0, 4))
        self.det_key_progress = ttk.Label(self.det_key_frame, text="")
        self.det_key_progress.pack(anchor="w")
        self.det_key_path_lbl = ttk.Label(
            self.det_key_frame, text="", wraplength=460, justify="left"
        )
        self.det_key_path_lbl.pack(anchor="w", pady=(2, 0))
        self.det_key_question = ttk.Label(
            self.det_key_frame, text="", font=("", 10, "bold")
        )
        self.det_key_question.pack(anchor="w", pady=(2, 0))
        self.det_key_options = ttk.Frame(self.det_key_frame)
        self.det_key_options.pack(fill="x", pady=(2, 0))
        self.det_key_unknown_lbl = ttk.Label(self.det_key_frame, text="")
        self.det_key_unknown_lbl.pack(anchor="w")
        key_btns = ttk.Frame(self.det_key_frame)
        key_btns.pack(fill="x", pady=(4, 0))
        self.det_key_back_btn = ttk.Button(
            key_btns, text=lang.t("det_key_back"), command=self._det_key_back
        )
        self.det_key_back_btn.pack(side="left")
        self.det_key_skip_btn = ttk.Button(
            key_btns, text=lang.t("det_key_skip"),
            command=lambda: self._det_key_answer(None),
        )
        self.det_key_skip_btn.pack(side="left", padx=(6, 0))
        self.det_key_restart_btn = ttk.Button(
            key_btns, text=lang.t("det_key_restart"),
            command=self._det_key_restart,
        )
        self.det_key_restart_btn.pack(side="left", padx=(6, 0))
        # Bottom status bar: packed side="bottom" BEFORE main, so the packer
        # carves the lowest strip for it and main fills everything above.
        # (With the old default side="top" the bar sat in the middle of the
        # window, right under the search toolbar, easy to miss.)
        self.status_label = ttk.Label(
            self.win, textvariable=self.status_var, padding=(10, 2), anchor="w"
        )
        self.status_label.pack(side="bottom", fill="x")
        # Guide and language live in the bottom bar, as in SpecioIdentify: the
        # language switch belongs next to the status line rather than at the
        # top of the search area, where it competed with the toolbar.
        self.help_button = ttk.Button(
            self.status_label, text=lang.t("help_button"),
            command=self._show_help,
        )
        self.help_button.pack(side="right", padx=4)
        # Built here, not up in the toolbar: a widget can only be packed into
        # the parent it was created with, and the status bar is what the guide
        # and the language switch belong to.
        self.lang_label = ttk.Label(
            self.status_label, text=lang.t("language_lbl")
        )
        self.lang_label.pack(side="right", padx=(0, 4))
        self.lang_box = ttk.Combobox(
            self.status_label, textvariable=self.lang_var, values=("ro", "en"),
            width=5, state="readonly",
        )
        self.lang_box.pack(side="right", padx=(0, 8))
        self.lang_box.bind("<<ComboboxSelected>>", self._on_language)
        ttk.Separator(self.win, orient="horizontal").pack(side="bottom", fill="x")
        # The question box claims its strip before main does. Packed after,
        # main's expand=True took the whole window and pushed the chat off the
        # bottom edge, where it was invisible however well it was styled.
        self._build_chat()
        # A grab handle between the results and the log, the same idea as the
        # block dividers, so the split is visible instead of a hairline the
        # user has to hunt for.
        self._chat_grip = tk.Frame(
            self.win, height=5, background=self._GRIP_IDLE,
            cursor="sb_v_double_arrow", takefocus=0,
        )
        self._chat_grip.pack(side="bottom", fill="x")
        self._dividers.append(self._chat_grip)
        self._chat_grip.bind("<Button-1>", self._chat_drag_start)
        self._chat_grip.bind("<B1-Motion>", self._chat_drag_move)
        self._chat_grip.bind("<ButtonRelease-1>", self._chat_drag_end)
        main = ttk.Frame(self.win, padding=(8, 2))
        main.pack(fill="both", expand=True)

        # Draggable split: navigation pane (left) <-> details (right).
        self.main_paned = ttk.PanedWindow(main, orient="horizontal")
        self.main_paned.pack(fill="both", expand=True)

        left = ttk.Frame(self.main_paned, padding=(0, 0, 8, 0))
        self.main_paned.add(left, weight=1)
        self.results_label = ttk.Label(left, text=lang.t("results_lbl"))
        self.results_label.pack(anchor="w")
        # View toggle (tree vs flat list), shown above the navigation pane.
        view_row = ttk.Frame(left)
        view_row.pack(fill="x", pady=(4, 0))
        self.view_label = ttk.Label(view_row, text=lang.t("view_lbl"))
        self.view_label.pack(side="left")
        self.view_var = tk.StringVar()
        self._view_map = {
            "tree": lang.t("view_tree"),
            "list": lang.t("view_list"),
        }
        self.view_var.set(self._view_map["tree"])
        self.view_box = ttk.Combobox(
            view_row,
            textvariable=self.view_var,
            values=list(self._view_map.values()),
            state="readonly",
            width=12,
        )
        self.view_box.pack(side="left", padx=(4, 0))
        self.view_box.bind("<<ComboboxSelected>>", self._on_view_change)
        # Divider between the navigation block and the detail block. Packed
        # before the scrolling panes so it reserves its width first.
        self._add_block_divider(self.main_paned, 0, left)
        # Flat list view, in a container with its own vertical scrollbar —
        # same wiring as the tree view and the profile pane, so the list is
        # not the only scrollable area without a visible scrollbar.
        self.list_container = ttk.Frame(left)
        self.list_container.pack(fill="both", expand=True, pady=(4, 0))
        self.list_vsb = ttk.Scrollbar(
            self.list_container, orient="vertical"
        )
        self.list_pane = tk.Listbox(
            self.list_container, width=44, exportselection=False,
            yscrollcommand=self.list_vsb.set,
        )
        self.list_vsb.configure(command=self.list_pane.yview)
        self.list_pane.grid(row=0, column=0, sticky="nsew")
        self.list_vsb.grid(row=0, column=1, sticky="ns")
        self.list_container.rowconfigure(0, weight=1)
        self.list_container.columnconfigure(0, weight=1)
        self.list_pane.bind("<<ListboxSelect>>", self._on_select)
        # Tree view with its own vertical scrollbar, in a dedicated frame.
        tree_container = ttk.Frame(left)
        tree_container.pack(fill="both", expand=True, pady=(4, 0))
        self.tree_pane = ttk.Treeview(tree_container, show="tree", displaycolumns=())
        tree_vsb = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree_pane.yview)
        self.tree_pane.configure(yscrollcommand=tree_vsb.set)
        self.tree_pane.grid(row=0, column=0, sticky="nsew")
        tree_vsb.grid(row=0, column=1, sticky="ns")
        tree_container.rowconfigure(0, weight=1)
        tree_container.columnconfigure(0, weight=1)
        self.tree_pane.bind("<<TreeviewSelect>>", self._on_tree_select)
        # Right-click on a group: reveal its full subtree inside the same
        # tree view (children from the whole catalog, not only from the
        # current search results) so navigation can continue bottom-up the
        # same way it starts top-down at startup.
        self.tree_pane.bind("<Button-3>", self._on_tree_right_click)
        # Autocomplete suggestion list lives directly under the search bar
        # (window level), never inside the scrolling navigation pane.
        self.suggestion_list = tk.Listbox(self.search_area, height=6,
                                          exportselection=False)
        self.suggestion_list.bind("<<ListboxSelect>>", self._on_suggestion_select)
        self.suggestion_list.bind("<Escape>", lambda _e: self.suggestion_list.pack_forget())
        right = ttk.Frame(self.main_paned)
        self.main_paned.add(right, weight=2)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        self.detail_title = ttk.Label(right, font=("", 12, "bold"))
        self.detail_title.pack(anchor="w")
        self.detail_common = ttk.Label(right, wraplength=820, justify="left")
        self.detail_common.pack(anchor="w", pady=(2, 4))
        # Movable split: photo panel (left) <-> profile text (right).
        self.paned = ttk.PanedWindow(right, orient="horizontal")
        self.paned.pack(fill="both", expand=True, pady=(2, 0))
        photo_side = ttk.Frame(self.paned, padding=(0, 0, 6, 0))
        self.paned.add(photo_side, weight=3)
        # The photo block is taller than the window can be: a full-size photo is
        # ~380px, and with the question log taking the bottom strip there is
        # less than that left on a small screen. The action buttons sat last in
        # the pack order, so they were the first thing clipped - and they are
        # the row you actually need (open folder, CoL, Wikipedia). A scrollable
        # column keeps all of it reachable instead of choosing a victim.
        photo_canvas = tk.Canvas(
            photo_side, highlightthickness=0, borderwidth=0,
            background="white",
        )
        photo_scroll = ttk.Scrollbar(
            photo_side, orient="vertical", command=photo_canvas.yview
        )
        photo_canvas.configure(yscrollcommand=photo_scroll.set)
        photo_canvas.pack(side="left", fill="both", expand=True)
        photo_scroll.pack(side="right", fill="y")
        photo_inner = ttk.Frame(photo_canvas)
        _photo_win = photo_canvas.create_window(
            (0, 0), window=photo_inner, anchor="nw"
        )

        def _photo_refit(event=None):
            width = photo_canvas.winfo_width()
            if width > 1:
                photo_canvas.itemconfigure(_photo_win, width=width)
            photo_canvas.configure(
                scrollregion=photo_canvas.bbox("all")
            )

        def _photo_wheel(event):
            photo_canvas.yview_scroll(
                -1 if event.delta > 0 or event.num == 4 else 1, "units"
            )
            return "break"

        photo_inner.bind("<Configure>", _photo_refit)
        photo_canvas.bind("<Configure>", _photo_refit)
        for widget in (photo_canvas, photo_inner):
            widget.bind("<MouseWheel>", _photo_wheel)
            widget.bind("<Button-4>", _photo_wheel)
            widget.bind("<Button-5>", _photo_wheel)
        self._photo_canvas = photo_canvas
        self._photo_inner = photo_inner

        self.photo_label = ttk.Label(photo_inner, width=60, anchor="center")
        self.photo_label.pack(anchor="center", pady=(4, 0))
        self.photo_nav_label = ttk.Label(photo_inner, anchor="center")
        self.photo_nav_label.pack(anchor="center")
        nav_frame = ttk.Frame(photo_inner)
        nav_frame.pack(anchor="center", pady=(2, 4))
        self.prev_btn = ttk.Button(
            nav_frame, text=lang.t("prev_btn"), command=self._prev_photo, width=6
        )
        self.prev_btn.pack(side="left", padx=4)
        self.next_btn = ttk.Button(
            nav_frame, text=lang.t("next_btn"), command=self._next_photo, width=6
        )
        self.next_btn.pack(side="left", padx=4)
        self.detail_date = ttk.Label(photo_inner, wraplength=380, justify="left")
        self.detail_date.pack(anchor="w", pady=(6, 0))
        self.detail_loc = ttk.Label(photo_inner, wraplength=380, justify="left")
        self.detail_loc.pack(anchor="w")
        self.detail_file = ttk.Label(photo_inner, wraplength=380, justify="left")
        self.detail_file.pack(anchor="w")
        # Row: open folder + web lookups, immediately next to each other.
        # The two 🌐 buttons behave exactly like the SpecioIdentify ones.
        action_row = ttk.Frame(photo_inner)
        action_row.pack(fill="x", pady=(8, 4))
        self.open_folder_btn = ttk.Button(
            action_row, text=lang.t("open_folder_btn"),
            command=self._open_species_folder,
        )
        self.open_folder_btn.pack(side="left")
        self.col_btn = ttk.Button(
            action_row, text=lang.t("btn_open_col"),
            command=self._browse_col,
        )
        self.col_btn.pack(side="left", padx=(6, 0))
        self.wiki_btn = ttk.Button(
            action_row, text=lang.t("btn_open_wikipedia"),
            command=self._browse_wikipedia,
        )
        self.wiki_btn.pack(side="left", padx=(6, 0))
        # Divider between the photo/details block and the profile block, so
        # the second sash is visible and grabbable like the first one.
        self._add_block_divider(self.paned, 0, photo_side)
        profile_side = ttk.Frame(self.paned, padding=(6, 0, 0, 0))
        self.paned.add(profile_side, weight=4)
        self.profile_label = ttk.Label(profile_side, text=lang.t("profile_lbl"))
        self.profile_label.pack(anchor="w")
        profile_wrap = ttk.Frame(profile_side)
        profile_wrap.pack(fill="both", expand=True, pady=(2, 0))
        profile_scroll = ttk.Scrollbar(profile_wrap, orient="vertical")
        self.profile_text = tk.Text(
            profile_wrap, wrap="word", width=46,
            yscrollcommand=profile_scroll.set, state="disabled",
        )
        profile_scroll.config(command=self.profile_text.yview)
        profile_scroll.pack(side="right", fill="y")
        self.profile_text.pack(side="left", fill="both", expand=True)
        self._configure_rich_text(self.profile_text)
        self._labels = [
            (self.lang_label, "language_lbl"),
            (self.search_label, "search_lbl"),
            (self.criteria_label, "criteria_lbl"),
            (self.category_label, "category_lbl"),
            (self.search_btn, "search_btn"),
            (self.det_toggle_btn, "det_btn"),
            (self.det_title, "det_title"),
            (self.det_add_btn, "det_add"),
            (self.det_mode_free_radio, "det_mode_free"),
            (self.det_mode_key_radio, "det_mode_key"),
            (self.det_key_back_btn, "det_key_back"),
            (self.det_key_skip_btn, "det_key_skip"),
            (self.det_key_restart_btn, "det_key_restart"),
            (self.results_label, "results_lbl"),
            (self.view_label, "view_lbl"),
            (self.profile_label, "profile_lbl"),
            (self.open_folder_btn, "open_folder_btn"),
            (self.col_btn, "btn_open_col"),
            (self.wiki_btn, "btn_open_wikipedia"),
            (self.prev_btn, "prev_btn"),
            (self.next_btn, "next_btn"),
            (self.change_btn, "change_catalog_btn"),
        ]
        # Ctrl + wheel resizes the whole page, like SpecioIdentify. The
        # toplevel binding catches wheel events bubbled up from any child.
        self.win.bind("<Control-MouseWheel>", self._zoom_page)
        self.win.bind("<Control-Button-4>", self._zoom_page)
        self.win.bind("<Control-Button-5>", self._zoom_page)
        self._apply_page_fonts()
        # Phase 3: the "describe and find" box, packed into search_area
        # after the toolbar and the determinator panel, so it sits below them.
        self._build_ai_panel()
        # Only now is the window worth keeping on screen: every widget exists,
        # so its bottom row is real and there is a size to compare against.
        self._placing = False

    # -------------------------------------------------- block dividers
    # The ttk sash between two blocks is drawn by the theme and is almost
    # invisible here, so the three main blocks looked glued together and the
    # resize handles could not be found. Each divider is a real, visible bar
    # that doubles as the drag handle; the native sash keeps working too.
    _GRIP_IDLE = "#c9ccd1"
    _GRIP_HOT = "#6b7a8f"

    def _add_block_divider(self, paned, index: int, parent, side: str = "right") -> None:
        """Adds a visible, draggable divider for *paned*'s sash *index*.

        The bar is packed on the inner edge of the left-hand block, so it
        marks the border the user wants to see and can be grabbed directly.
        """
        grip = tk.Frame(
            parent,
            width=1,
            background=self._GRIP_IDLE,
            cursor="sb_h_double_arrow",
            takefocus=0,
        )
        grip.pack(side=side, fill="y", padx=1)
        self._dividers.append(grip)

        def on_press(event):
            self._drag = (paned, index, event.x_root, paned.sashpos(index))
            grip.configure(background=self._GRIP_HOT)

        def on_motion(event):
            if not getattr(self, "_drag", None):
                return
            target, sash, start_x, start_pos = self._drag
            width = target.winfo_width()
            if width <= 1:
                return
            wanted = start_pos + (event.x_root - start_x)
            target.sashpos(sash, max(0, min(width, wanted)))

        def on_release(_event):
            self._drag = None
            grip.configure(background=self._GRIP_IDLE)

        def on_enter(_event):
            if not getattr(self, "_drag", None):
                grip.configure(background=self._GRIP_HOT)

        def on_leave(_event):
            if not getattr(self, "_drag", None):
                grip.configure(background=self._GRIP_IDLE)

        def on_double(_event):
            # Double-click restores an even split, the usual escape hatch
            # when a block was dragged too small to grab again.
            target, sash = paned, index
            target.sashpos(sash, target.winfo_width() // 3)

        grip.bind("<ButtonPress-1>", on_press)
        grip.bind("<B1-Motion>", on_motion)
        grip.bind("<ButtonRelease-1>", on_release)
        grip.bind("<Enter>", on_enter)
        grip.bind("<Leave>", on_leave)
        grip.bind("<Double-Button-1>", on_double)

    # -------------------------------------------------- rich text + page zoom
    def _get_rich_fonts(self) -> dict:
        """Body/bold/italic/heading fonts at the current zoom size.

        One shared set of ``tkfont.Font`` objects: configuring their size
        updates every tag and widget that references them at once.
        """
        size = self.text_zoom_size
        fonts = getattr(self, "_rich_fonts", None)
        if fonts is None:
            fonts = {
                "body": tkfont.Font(family="Segoe UI", size=size),
                "bold": tkfont.Font(family="Segoe UI", size=size, weight="bold"),
                "italic": tkfont.Font(family="Segoe UI", size=size, slant="italic"),
                "h1": tkfont.Font(family="Segoe UI", size=size + 5, weight="bold"),
                "h2": tkfont.Font(family="Segoe UI", size=size + 3, weight="bold"),
                "h3": tkfont.Font(family="Segoe UI", size=size + 1, weight="bold"),
            }
            self._rich_fonts = fonts
            return fonts
        fonts["body"].configure(size=size)
        fonts["bold"].configure(size=size)
        fonts["italic"].configure(size=size)
        fonts["h1"].configure(size=size + 5)
        fonts["h2"].configure(size=size + 3)
        fonts["h3"].configure(size=size + 1)
        return fonts

    def _configure_rich_text(self, widget: tk.Text) -> None:
        """Visual tags for the simple-Markdown renderer (SpecioIdentify style)."""
        fonts = self._get_rich_fonts()
        widget.configure(font=fonts["body"])
        widget.tag_configure("h1", font=fonts["h1"], spacing1=10, spacing3=6)
        widget.tag_configure("h2", font=fonts["h2"], spacing1=8, spacing3=5)
        widget.tag_configure("h3", font=fonts["h3"], spacing1=6, spacing3=4)
        widget.tag_configure("bold", font=fonts["bold"])
        widget.tag_configure("italic", font=fonts["italic"])
        widget.tag_configure("body", spacing1=2, spacing3=2)
        widget.tag_configure(
            "list", lmargin1=0, lmargin2=0, spacing1=2, spacing3=2
        )
        widget.tag_configure(
            "rule", foreground="#777777", spacing1=4, spacing3=4
        )

    def _insert_rich_text(self, widget: tk.Text, text: str) -> None:
        """Render a small Markdown subset (headings, lists, rules) into a Text."""
        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()

            if not stripped:
                widget.insert(tk.END, "\n")
                continue

            # Preserve leading spaces for indentation
            leading_spaces = len(line) - len(line.lstrip())

            if re.fullmatch(r"[-*_]{3,}", stripped):
                if leading_spaces > 0:
                    widget.insert(tk.END, " " * leading_spaces)
                widget.insert(
                    tk.END,
                    "------------------------------\n",
                    ("rule",),
                )
                continue

            heading = re.match(r"^(#{1,3})\s+(.*)$", stripped)
            if heading:
                if leading_spaces > 0:
                    widget.insert(tk.END, " " * leading_spaces)
                level = len(heading.group(1))
                self._insert_inline_rich_text(
                    widget, heading.group(2).strip(), (f"h{level}",)
                )
                widget.insert(tk.END, "\n")
                continue

            list_item = re.match(r"^([-*+]|\d+[.)])\s+(.*)$", stripped)
            if list_item:
                if leading_spaces > 0:
                    widget.insert(tk.END, " " * leading_spaces)
                marker = list_item.group(1)
                if marker in {"*", "+"}:
                    marker = "-"
                widget.insert(tk.END, f"{marker} ", ("list",))
                self._insert_inline_rich_text(
                    widget, list_item.group(2).strip(), ("list",)
                )
                widget.insert(tk.END, "\n")
                continue

            if leading_spaces > 0:
                widget.insert(tk.END, " " * leading_spaces)
            self._insert_inline_rich_text(widget, stripped, ("body",))
            widget.insert(tk.END, "\n")

    def _insert_inline_rich_text(
        self, widget: tk.Text, text: str, base_tags: tuple[str, ...]
    ) -> None:
        """Apply ``**bold**`` and ``*italic*`` (Markdown inline) into a Text."""
        pattern = re.compile(
            r"(\*\*|__)(.+?)\1|(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"
            r"|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)"
        )
        cursor = 0
        for match in pattern.finditer(text):
            if match.start() > cursor:
                widget.insert(tk.END, text[cursor : match.start()], base_tags)
            if match.group(1):
                formatted_text = match.group(2)
                formatted_tags = base_tags + ("bold",)
            elif match.group(3) is not None:
                formatted_text = match.group(3)
                formatted_tags = base_tags + ("italic",)
            else:
                formatted_text = match.group(4)
                formatted_tags = base_tags + ("italic",)
            widget.insert(tk.END, formatted_text, formatted_tags)
            cursor = match.end()
        if cursor < len(text):
            widget.insert(tk.END, text[cursor:], base_tags)

    def _apply_page_fonts(self) -> None:
        """Push the current zoom size to the tree, list and detail labels."""
        size = self.text_zoom_size
        # Treeview items take their font from the style, not -font.
        ttk.Style(self.win).configure("Treeview", font=("Segoe UI", size))
        self.list_pane.configure(font=("Segoe UI", size))
        self.suggestion_list.configure(font=("Segoe UI", size))
        self.detail_title.configure(font=("Segoe UI", size + 2, "bold"))
        for label in (
            self.detail_common,
            self.photo_nav_label,
            self.detail_date,
            self.detail_loc,
            self.detail_file,
        ):
            label.configure(font=("Segoe UI", size))

    def _zoom_page(self, event=None):
        """Ctrl + mouse wheel grows/shrinks the whole page (SpecioIdentify).

        Always stops the event. Returning "break" only at the size limit let
        the wheel carry on to the widget's own scrolling, so Ctrl+wheel both
        resized the text and scrolled the page - in the reading window, where
        the text is long, the movement hid the change. A plain wheel still
        scrolls; holding the modifier is what reserves it for size.
        """
        if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0:
            delta = 1
        else:
            delta = -1
        new_size = max(8, min(24, self.text_zoom_size + delta))
        if new_size != self.text_zoom_size:
            self.text_zoom_size = new_size
            self._get_rich_fonts()  # tags follow automatically (shared Font objects)
            self._apply_page_fonts()
            read = getattr(self, "_read_text", None)
            if read is not None and read.winfo_exists():
                # Re-insert at the new size, so the reading window reflows
                # instead of keeping the line breaks of the old font, and stay
                # on the same line rather than jumping to the end.
                self._read_fill(jump_to_end=False)
        return "break"

    # ------------------------------------------------------------- language
    def _refresh_language(self) -> None:
        self.win.title(lang.t("app_title"))
        for widget, key in self._labels:
            widget.config(text=lang.t(key))
        # rebuild criteria / category comboboxes with translated displays
        self._crit_map = {lang.t(key): key for key in CRITERIA}
        self.crit_box["values"] = list(self._crit_map)
        current_crit = getattr(self, "_crit_key", next(iter(CRITERIA)))
        for display, key in self._crit_map.items():
            if key == current_crit:
                self.crit_box.set(display)
                break
        self._rebuild_categories()
        # rebuild the view combobox with translated labels, preserving
        # the currently selected internal mode ("tree" / "list").
        self._view_map = {
            "tree": lang.t("view_tree"),
            "list": lang.t("view_list"),
        }
        self.view_box["values"] = list(self._view_map.values())
        self.view_var.set(self._view_map.get(self._view_mode, self._view_map["tree"]))
        self._det_refresh_options()
        if self.det_active and self._det_mode == "key":
            self._det_render_key()
        self._render_left()
        if self.current is None:
            self._show_empty_details()
        else:
            self._show_details(self.current)
    def _show_help(self) -> None:
        """Open the guide in its own window, reusing it if already open.

        Follows SpecioIdentify: a transient window, Escape closes it, and the
        text has its own size control so a long page can be read without
        widening the whole application. Reopening brings the existing window
        forward instead of stacking a second copy of the same guide.
        """
        existing = getattr(self, "help_window", None)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            return
        win = tk.Toplevel(self.win)
        self.help_window = win
        win.title(lang.t("help_title"))
        win.geometry("860x680")
        win.minsize(420, 320)
        win.transient(self.win)
        win.bind("<Escape>", lambda _event: win.destroy())

        self.help_font_size = getattr(self, "help_font_size", 11)
        self.help_font = tkfont.Font(
            root=self.win, family="Segoe UI", size=self.help_font_size
        )
        self.help_bold = tkfont.Font(
            root=self.win, family="Segoe UI", size=self.help_font_size, weight="bold"
        )

        bar = ttk.Frame(win, padding=(10, 8, 10, 0))
        bar.pack(fill="x")
        self.help_size_label = ttk.Label(bar, text=lang.t("help_size"))
        self.help_size_label.pack(side="left", padx=(0, 8))
        ttk.Button(
            bar, text="A−", width=4, command=lambda: self._resize_help_font(-1)
        ).pack(side="left")
        self.help_size_value = ttk.Label(bar, width=4, anchor="center")
        self.help_size_value.pack(side="left")
        ttk.Button(
            bar, text="A+", width=4, command=lambda: self._resize_help_font(1)
        ).pack(side="left")

        wrap = ttk.Frame(win, padding=(10, 8, 10, 10))
        wrap.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(wrap, orient="vertical")
        self.help_text = tk.Text(
            wrap, wrap="word", font=self.help_font, padx=12, pady=10,
            spacing1=2, spacing3=4, background="#ffffff", relief="solid",
            borderwidth=1, state="disabled", cursor="arrow",
            yscrollcommand=scroll.set,
        )
        scroll.config(command=self.help_text.yview)
        scroll.pack(side="right", fill="y")
        self.help_text.pack(side="left", fill="both", expand=True)
        self.help_text.tag_configure("head", font=self.help_bold,
                                     foreground="#1a3a5c", spacing1=12, spacing3=4)
        self.help_text.tag_configure("body", font=self.help_font, lmargin1=10)
        self.help_text.tag_configure("key", font=self.help_bold,
                                     foreground="#444444")
        self._resize_help_font(reset=True)
        self._fill_help()

    def _fill_help(self) -> None:
        """Write the guide, in whatever language is active right now.

        Owns the editable state of the widget: a Text ignores inserts while it
        is disabled, so it has to be opened, filled and closed again here or
        the first open would come up blank.
        """
        self.help_text.configure(state="normal")
        self.help_text.delete("1.0", "end")
        for heading, lines in lang.t("help_body").items():
            self.help_text.insert("end", heading + "\n", "head")
            for line in lines:
                self.help_text.insert("end", line + "\n", "body")
            self.help_text.insert("end", "\n", "body")
        self.help_text.configure(state="disabled")
        self.help_text.see("1.0")

    def _resize_help_font(self, delta=0, reset=False) -> None:
        size = self.help_font_size if not reset else 11
        if not reset:
            size = max(8, min(28, self.help_font_size + delta))
        self.help_font_size = size
        self.help_font.configure(size=size)
        self.help_bold.configure(size=size)
        self.help_size_value.configure(text=str(size))

    def _on_language(self, _event=None) -> None:
        lang.set_language(self.lang_var.get())
        self._refresh_language()
        self.lang_label.configure(text=lang.t("language_lbl"))
        self.brand_label.configure(text=lang.t("brand_name"))
        self.brand_sub.configure(text=lang.t("brand_sub"))
        help_text = getattr(self, "help_text", None)
        if help_text is not None and help_text.winfo_exists():
            self._fill_help()
            help_text.tag_configure("head", font=self.help_bold,
                                    foreground="#1a3a5c", spacing1=12, spacing3=4)
            help_text.tag_configure("body", font=self.help_font, lmargin1=10)

    # ------------------------------------------------------------ catalogue
    def _rebuild_categories(self) -> None:
        cats: list[str | None] = [None]
        displays = [lang.t("all_cat")]
        if self.db is not None:
            for cat in list_categories(self.db):
                cats.append(cat)
                displays.append(cat)
        self._cat_values = cats
        self._cat_displays = displays
        self.cat_box["values"] = displays
        self.cat_box.set(displays[0])
    def _on_change_catalog(self) -> None:
        candidate = self._ask_root()
        if candidate is None:
            return
        try:
            db = CatalogDB(candidate)
        except CatalogNotReady as exc:
            messagebox.showerror(
                lang.t("db_error_title"), lang.t("status_open_fail", err=exc)
            )
            return
        self.db = db
        save_catalog_root(candidate)
        self._full_tree_cache = None  # catalog changed: rebuild the full tree
        self.status_var.set(lang.t("status_ready", root=candidate))
        self._rebuild_categories()
        self._do_search()
    # -------------------------------------------------------------- search
    def _do_search(self) -> None:
        if self.db is None:
            self.status_var.set(lang.t("status_not_open"))
            return
        query = self.query_var.get().strip()
        crit_key = self._crit_map.get(self.crit_box.get(), next(iter(CRITERIA)))
        self._crit_key = crit_key
        category = None
        if self.cat_box.get() in self._cat_displays:
            idx = self._cat_displays.index(self.cat_box.get())
            category = self._cat_values[idx]
        base = search_species(self.db, query, crit_key, category)
        self._det_base = base
        self.results = base
        self._det_status = {}
        constraints_active = False
        if self.det_active:
            constraints = self._collect_constraints()
            if constraints:
                constraints_active = True
                vocab = load_vocab(self.db.catalog_root)
                exact, incomplete = determine(base, constraints, vocab)
                self._det_status = {
                    m.species.scientific_name: m.status
                    for m in exact + incomplete
                }
                # Best match first: more of the requested traits actually
                # confirmed on that species. The determinator and the
                # describe-and-find box both land here, so the user always
                # sees the strongest candidates at the top.
                exact.sort(key=lambda m: -len(m.matched))
                incomplete.sort(key=lambda m: -len(m.matched))
                self.results = [m.species for m in exact] + [
                    m.species for m in incomplete
                ]
            self._det_refresh_options()
        self._render_left()
        n_photos = sum(len(r.photos) for r in self.results)
        if constraints_active and not self.results:
            status_text = lang.t("det_none")
        elif constraints_active:
            n_exact = sum(1 for s in self._det_status.values() if s == "exact")
            status_text = lang.t(
                "det_summary",
                n=len(self.results),
                m=n_photos,
                e=n_exact,
                i=len(self.results) - n_exact,
            )
        else:
            status_text = lang.t(
                "results_count", n=len(self.results), m=n_photos
            )
        self.status_var.set(status_text)
        self.current = None
        self.photos = []
        self.photo_index = 0
        self._show_empty_details()
        first_search = not self._first_search_done
        self._first_search_done = True
        # At startup keep the tree fully collapsed (kingdoms only): the
        # auto-selection below expands every ancestor of the first result.
        if self.results and not first_search:
            self._select_first()
    # -------------------------------------------------------- determinator
    def _toggle_determinator(self) -> None:
        """Show/hide the trait-filter panel and (re)run the search."""
        self.det_active = not self.det_active
        if self.det_active:
            self.det_panel.pack(fill="x", after=self.search_frame)
            self._det_apply_mode()
        else:
            self.det_panel.pack_forget()
            self._det_status = {}
        self._do_search()
        if not self.det_active:
            return
        if self._det_mode == "key":
            self._det_render_key()
        elif not self.det_rows:
            self._det_add_row()

    def _det_apply_mode(self) -> None:
        """Show either the constraint rows or the guided-key view."""
        for widget in (
            self.det_title,
            self.det_mode_frame,
            self.det_rows_frame,
            self.det_add_btn,
            self.det_key_frame,
        ):
            widget.pack_forget()
        if self._det_mode == "key":
            self.det_mode_frame.pack(fill="x")
            self.det_key_frame.pack(fill="x")
        else:
            self.det_title.pack(anchor="w")
            self.det_mode_frame.pack(fill="x", pady=(2, 0))
            self.det_rows_frame.pack(fill="x", pady=(2, 0))
            self.det_add_btn.pack(anchor="w", pady=(4, 0))

    def _det_mode_changed(self) -> None:
        """Radiobutton callback: switch free filter <-> guided key."""
        self._det_mode = self._det_mode_var.get()
        if not self.det_active:
            return  # panel hidden: the view is applied when it opens
        self._det_apply_mode()
        self._do_search()
        if self._det_mode == "key":
            self._det_render_key()

    def _det_add_row(self) -> None:
        """Append one field+value constraint row to the panel."""
        row: dict = {"field_key": None, "_det_seen_text": ""}
        frame = ttk.Frame(self.det_rows_frame)
        frame.pack(fill="x", pady=1)
        field_box = ttk.Combobox(frame, state="normal", width=24, values=[])
        field_box.pack(side="left", padx=(0, 6))
        value_box = ttk.Combobox(frame, state="normal", width=26, values=[])
        value_box.pack(side="left", padx=(0, 6))
        rm_btn = ttk.Button(
            frame, text="✕", width=2,
            command=lambda r=row: self._det_remove_row(r),
        )
        rm_btn.pack(side="left")
        row.update(frame=frame, field_box=field_box, value_box=value_box)
        # Type-ahead keeps the keyboard focus in the entry: suppress the
        # native <Map> focus grab of the popdown listbox (a widget-level
        # binding runs before the ComboboxListbox tag, so "break" wins).
        popdown = str(
            field_box.tk.call("ttk::combobox::PopdownWindow", str(field_box))
        )
        field_box.tk.call("bind", f"{popdown}.f.l", "<Map>", "break")
        field_box.bind(
            "<<ComboboxSelected>>",
            lambda _e, r=row: self._det_on_field_selected(r),
        )
        field_box.bind(
            "<KeyRelease>",
            lambda e, r=row: self._det_on_field_typed(r, e),
        )
        field_box.bind("<Return>", lambda _e, r=row: self._det_on_field_return(r))
        field_box.bind("<Tab>", lambda _e, r=row: self._det_unpost_field(r))
        field_box.bind(
            "<<PrevWindow>>", lambda _e, r=row: self._det_unpost_field(r)
        )
        # Browsing (Down key or the dropdown arrow) shows the full list.
        field_box.bind("<Down>", lambda _e, r=row: self._det_browse_values(r))
        field_box.bind(
            "<Button-1>", lambda e, r=row: self._det_on_field_press(r, e)
        )
        value_box.bind("<<ComboboxSelected>>", lambda _e: self._do_search())
        value_box.bind("<Return>", lambda _e: self._do_search())
        self.det_rows.append(row)
        self._det_refresh_options()

    def _det_remove_row(self, row: dict) -> None:
        """Drop one constraint row, then re-run the search."""
        if row in self.det_rows:
            self.det_rows.remove(row)
        row["frame"].destroy()
        self._do_search()

    def _det_on_field_selected(self, row: dict) -> None:
        self._det_set_field(
            row, self._det_field_map.get(row["field_box"].get().strip())
        )
        row["field_box"]["values"] = list(self._det_field_map)
        row["_det_seen_text"] = row["field_box"].get()
        row["value_box"].focus_set()

    def _det_on_field_typed(self, row: dict, event=None) -> None:
        """Type-ahead: narrow the dropdown and post it while text changes.

        ``event`` is the <KeyRelease> that triggered the call; when the
        text did not change (Escape, arrows, modifiers) the popup state is
        left alone so the native Unpost/Post bindings keep working.
        """
        field_box = row["field_box"]
        typed = field_box.get()
        if event is not None and typed == row.get("_det_seen_text"):
            return
        row["_det_seen_text"] = typed
        options = filter_field_labels(typed, self._det_field_map)
        field_box["values"] = options
        self._det_set_field(row, resolve_field(typed, self._det_field_map))
        if typed.strip() and options:
            field_box.tk.call("ttk::combobox::Post", str(field_box))
        else:
            self._det_unpost_field(row)

    @staticmethod
    def _det_unpost_field(row: dict) -> None:
        """Close the field dropdown (safe when it was never posted)."""
        row["field_box"].tk.call(
            "ttk::combobox::Unpost", str(row["field_box"])
        )

    def _det_browse_values(self, row: dict) -> None:
        """Down/arrow click: restore the full field list for browsing."""
        if self._det_field_map:
            row["field_box"]["values"] = list(self._det_field_map)

    def _det_on_field_press(self, row: dict, event) -> None:
        """Clicking the arrow/border (not the text) browses all fields."""
        try:
            elem = row["field_box"].identify(event.x, event.y)
        except tk.TclError:
            return
        if elem != "textarea":
            self._det_browse_values(row)

    def _det_on_field_return(self, row: dict) -> None:
        """Enter closes the list; go to the value box (or search if set)."""
        self._det_unpost_field(row)
        value_box = row["value_box"]
        if value_box.get().strip():
            self._do_search()
        else:
            value_box.focus_set()

    def _det_set_field(self, row: dict, key: str | None) -> None:
        """Apply a field selection; a changed field invalidates its value."""
        if row.get("field_key") == key:
            return
        row["field_key"] = key
        row["value_box"].set("")
        self._det_update_value_options(row)

    def _det_update_value_options(self, row: dict) -> None:
        if self.db is None or not row.get("field_key"):
            row["value_box"]["values"] = []
            return
        vocab = load_vocab(self.db.catalog_root)
        row["value_box"]["values"] = value_options(
            self._det_base, row["field_key"], vocab
        )

    def _det_refresh_options(self) -> None:
        """Rebuild field/value combo options, preserving row selections."""
        if self.db is None or not self.det_rows:
            return
        vocab = load_vocab(self.db.catalog_root)
        labels = vocab.get("field_labels") or {}
        fields = applicable_fields(self._det_base, vocab)
        self._det_field_map = {labels.get(f, f): f for f in fields}
        inv = {v: k for k, v in self._det_field_map.items()}
        displays = list(self._det_field_map)
        for row in self.det_rows:
            key = row.get("field_key")
            if key not in fields:
                row["field_key"] = None
                row["field_box"].set("")
            else:
                row["field_box"].set(inv.get(key, ""))
            row["_det_seen_text"] = row["field_box"].get()
            row["field_box"]["values"] = displays
            self._det_update_value_options(row)

    def _collect_constraints(self) -> list[Constraint]:
        if self.db is None:
            return []
        vocab = load_vocab(self.db.catalog_root)
        out: list[Constraint] = []
        if self._det_mode == "key":
            for ans in self._key_answers:
                key, value = ans.get("field"), ans.get("value")
                if key and value:
                    out.append(
                        Constraint(
                            field=key,
                            value=value,
                            match=match_type_for(key, vocab),
                        )
                    )
            return out
        for row in self.det_rows:
            key = row.get("field_key")
            value = row["value_box"].get().strip()
            if key and value:
                out.append(
                    Constraint(
                        field=key, value=value,
                        match=match_type_for(key, vocab),
                    )
                )
        return out

    def _det_display_name(self, name: str) -> str:
        """Species caption: '?' marks a determinator-incomplete match."""
        if self._det_status.get(name) == "incomplete":
            return f"{name}  ?"
        return name

    # ------------------------------------------------------ guided key (B)
    def _det_key_answer(self, value: str | None) -> None:
        """Record the current answer (None = skip) and advance the key."""
        step = self._det_key_current
        if step is None:
            return
        self._key_answers.append(
            {"field": step.field, "label": step.label, "value": value}
        )
        self._det_key_current = None
        self._do_search()
        self._det_render_key()

    def _det_key_back(self) -> None:
        """Undo the last answer; constraints and results follow."""
        if not self._key_answers:
            return
        self._key_answers.pop()
        self._det_key_current = None
        self._do_search()
        self._det_render_key()

    def _det_key_restart(self) -> None:
        """Clear every answer and start the key over."""
        self._key_answers.clear()
        self._det_key_current = None
        self._do_search()
        self._det_render_key()

    def _det_render_key(self) -> None:
        """Redraw progress plus the next question (or the end message)."""
        if self.db is None or self._det_mode != "key":
            return
        vocab = load_vocab(self.db.catalog_root)
        constraints = self._collect_constraints()
        exact, incomplete = determine(self._det_base, constraints, vocab)
        remaining = len(exact) + len(incomplete)
        total = len(self._det_base)
        self.det_key_progress.config(
            text=lang.t(
                "det_key_progress",
                step=len(self._key_answers) + 1,
                n=remaining,
                total=total,
                e=len(exact),
                i=len(incomplete),
            )
        )
        if self._key_answers:
            parts: list[str] = []
            for ans in self._key_answers:
                lbl = ans.get("label") or ans.get("field") or ""
                val = ans.get("value")
                if val is None:
                    shown = f"[{lang.t('det_key_skipped')}]"
                elif len(val) > 28:
                    shown = val[:27] + "…"
                else:
                    shown = val
                parts.append(f"{lbl}: {shown}")
            self.det_key_path_lbl.config(
                text=lang.t("det_key_path", path="  ›  ".join(parts))
            )
        else:
            self.det_key_path_lbl.config(text="")
        for child in self.det_key_options.winfo_children():
            child.destroy()
        step = None
        if remaining >= 2:
            step = key_step(
                self._det_base,
                constraints,
                vocab,
                {a["field"] for a in self._key_answers},
            )
        self._det_key_current = step
        if remaining == 0:
            self.det_key_question.config(text=lang.t("det_key_none"))
            self.det_key_unknown_lbl.config(text="")
        elif remaining == 1:
            self.det_key_question.config(text=lang.t("det_key_one"))
            self.det_key_unknown_lbl.config(text="")
        elif step is None:
            self.det_key_question.config(
                text=lang.t("det_key_exhausted", n=remaining)
            )
            self.det_key_unknown_lbl.config(text="")
        else:
            self.det_key_question.config(text=step.label)
            cols = 4 if len(step.options) <= 16 else 5
            for i, (disp, cnt) in enumerate(step.options):
                shown = disp if len(disp) <= 40 else disp[:39] + "…"
                btn = ttk.Button(
                    self.det_key_options,
                    text=f"{shown} ({cnt})",
                    command=lambda v=disp: self._det_key_answer(v),
                )
                btn.grid(
                    row=i // cols, column=i % cols, sticky="ew", padx=2, pady=2
                )
            for col in range(cols):
                self.det_key_options.columnconfigure(col, weight=1)
            self.det_key_unknown_lbl.config(
                text=lang.t("det_key_unknown", u=step.unknown)
                if step.unknown
                else ""
            )
        self.det_key_back_btn.config(
            state="normal" if self._key_answers else "disabled"
        )
        self.det_key_skip_btn.config(
            state="normal" if step else "disabled"
        )

    def _render_left(self) -> None:
        """Show the navigation pane (tree or flat list) from current results."""
        is_tree = self.view_var.get() == self._view_map["tree"]
        if is_tree:
            self._view_mode = "tree"
            self._show_tree()
            self.list_container.pack_forget()
            self.tree_pane.master.pack(fill="both", expand=True, pady=(4, 0))
        else:
            self._view_mode = "list"
            self._show_list()
            self.tree_pane.master.pack_forget()
            self.list_container.pack(fill="both", expand=True, pady=(4, 0))
    def _show_list(self) -> None:
        self.list_pane.delete(0, "end")
        for res in self.results:
            self.list_pane.insert("end", self._det_display_name(res.scientific_name))
    def _show_tree(self) -> None:
        from core.taxonomy_tree import build_tree
        self.tree_pane.delete(*self.tree_pane.get_children())
        self._tree_ids.clear()
        self._node_path.clear()
        names = [r.scientific_name for r in self.results]
        if not names:
            return
        categories = {r.scientific_name: r.category for r in self.results}
        tree = build_tree(self.db.catalog_root, names, categories)
        other = tree.pop(None, [])
        def recurse(node: dict, parent: str, path: tuple[str, ...]) -> None:
            for label in sorted((k for k in node if k is not None), key=str.lower):
                child = node[label]
                # Group iids spell out the whole taxon path, so identically
                # named taxa under different parents (e.g. two genera 'Iris')
                # never clash and a right-click knows where a node lives.
                iid = "n:" + "/".join(path + (label,))
                self._node_path[iid] = path + (label,)
                # Ranks below the kingdoms start collapsed; nodes open on
                # demand (or when a search selects a species).
                self.tree_pane.insert(parent, "end", iid, text=label)
                recurse(child, iid, path + (label,))
            for name in node.get(None, []):
                iid = "sp:" + name
                self._tree_ids[name] = iid
                self.tree_pane.insert(
                    parent, "end", iid, text=self._det_display_name(name)
                )

        # Top level: the kingdoms themselves (Regnul Animalia, Regnul
        # Plantae, ...), all collapsed so only this level is visible when
        # the application opens.
        for kingdom in sorted(tree, key=str.lower):
            iid = "n:" + kingdom
            self._node_path[iid] = (kingdom,)
            label = f"{lang.t('tree_kingdom')} {kingdom}"
            self.tree_pane.insert("", "end", iid, text=label)
            recurse(tree[kingdom], iid, (kingdom,))
        if other:
            iid = "other"
            self.tree_pane.insert("", "end", iid, text=lang.t("tree_other"))
            for name in other:
                sp = "sp:" + name
                self._tree_ids[name] = sp
                self.tree_pane.insert(
                    iid, "end", sp, text=self._det_display_name(name)
                )
    def _select_first(self) -> None:
        """Re-activate the selection after the navigation pane is rebuilt.

        Switching views rebuilds the pane from scratch, so something has to be
        selected again. It must be the species already open, not results[0]:
        picking the second result in the list and then flipping to the tree
        used to jump to the first species, losing the one you were reading.
        Falls back to the first result only when nothing was open.
        """
        target = self.current
        if target is not None:
            index = next(
                (i for i, r in enumerate(self.results)
                 if r.scientific_name == target.scientific_name),
                None,
            )
        else:
            index = None
        if index is None:
            index = 0 if self.results else None
        if index is None:
            return
        is_tree = self.view_var.get() == self._view_map["tree"]
        if is_tree:
            iid = self._tree_ids.get(self.results[index].scientific_name)
            if iid is not None:
                self._open_ancestors(iid)
                self.tree_pane.see(iid)
                self.tree_pane.selection_set(iid)
                return
        self.list_pane.selection_clear(0, "end")
        self.list_pane.selection_set(index)
        self._on_select()
    def _on_select(self, _event=None) -> None:
        selection = self.list_pane.curselection()
        if not selection or not self.results:
            return
        res = self.results[selection[0]]
        self._show_species(res)
    def _on_tree_select(self, _event=None) -> None:
        selected = self.tree_pane.selection()
        if not selected or self.db is None:
            return
        iid = selected[0]
        if not str(iid).startswith("sp:"):
            return
        self._open_ancestors(str(iid))
        name = str(iid)[3:]
        results_by_name = {r.scientific_name: r for r in self.results}
        res = results_by_name.get(name)
        if res is None:
            # Species revealed through the context menu is not part of the
            # current search results: load it straight from the catalog.
            res = self._fetch_species(name)
        if res is None:
            return
        self._show_species(res)

    def _show_species(self, res: SpeciesResult) -> None:
        self.current = res
        self.photos = list(res.photos)
        self.photo_index = 0
        self._show_details(res)

    def _open_ancestors(self, iid: str) -> None:
        """Expand every parent of ``iid`` so a collapsed node becomes visible."""
        pid = self.tree_pane.parent(iid)
        while pid:
            self.tree_pane.item(pid, open=True)
            pid = self.tree_pane.parent(pid)

    # ----------------------------------------------------- right-click reveal
    def _on_tree_right_click(self, event: tk.Event) -> None:
        """Right-click on a group: reveal its full subtree in place.

        The descendants missing from the visible tree (taken from the
        WHOLE catalog, not only from the current search results) are
        inserted directly into the same tree view, exactly like the nodes
        a normal top-down navigation starts with; from there the user
        keeps expanding and clicking as usual. A right-click on a species
        just opens it.
        """
        iid = self.tree_pane.identify_row(event.y)
        if not iid:
            return
        if str(iid).startswith("sp:"):
            self.tree_pane.selection_set(iid)
            self._open_ancestors(str(iid))
            self._on_tree_select()
            return
        self._reveal_subtree(str(iid))

    def _full_tree(self) -> dict:
        """Taxonomy tree over the WHOLE catalog, not just current results."""
        if self._full_tree_cache is None and self.db is not None:
            from core.taxonomy_tree import build_tree
            everything = search_species(self.db, "")
            names = [r.scientific_name for r in everything]
            categories = {r.scientific_name: r.category for r in everything}
            self._full_tree_cache = build_tree(
                self.db.catalog_root, names, categories
            )
        return self._full_tree_cache or {}

    def _full_node(self, path: tuple[str, ...]) -> dict | None:
        """Nested dict of the taxon at ``path`` inside the full catalog tree."""
        node: object = self._full_tree()
        for level in path:
            if not isinstance(node, dict) or level not in node:
                return None
            node = node[level]
        return node if isinstance(node, dict) else None

    def _reveal_subtree(self, iid: str) -> None:
        """Insert the FULL subtree of a group node into the visible tree.

        Already present nodes are left untouched; only the descendants
        that the current search results left out are added, recursively,
        then the node is opened one level (deeper levels stay collapsed,
        exactly like a fresh top-down tree).
        """
        path = self._node_path.get(iid)
        if not path:
            return
        node = self._full_node(path)
        if node is None:
            return
        self._insert_subtree(iid, path, node)
        self.tree_pane.item(iid, open=True)

    def _insert_subtree(self, iid: str, path: tuple[str, ...], node: dict) -> None:
        """Recursively insert every child of ``node`` missing under ``iid``."""
        for label in sorted((k for k in node if k is not None), key=str.lower):
            child_path = path + (label,)
            child_iid = "n:" + "/".join(child_path)
            if not self.tree_pane.exists(child_iid):
                self.tree_pane.insert(iid, "end", child_iid, text=label)
                self._node_path[child_iid] = child_path
            self._insert_subtree(child_iid, child_path, node[label])
        for name in sorted(node.get(None, []), key=str.lower):
            sp_iid = "sp:" + name
            self._tree_ids[name] = sp_iid
            if not self.tree_pane.exists(sp_iid):
                self.tree_pane.insert(
                    iid, "end", sp_iid, text=self._det_display_name(name)
                )

    def _fetch_species(self, name: str) -> SpeciesResult | None:
        """Load one species by exact scientific name straight from the catalog."""
        if self.db is None:
            return None
        for res in search_species(self.db, name, "scientific"):
            if res.scientific_name == name:
                return res
        return None

    # ------------------------------------------------------------- search ui
    def _on_search_keyrelease(self, _event: tk.Event | None = None) -> None:
        """Autocomplete: show suggestions after ≥3 typed characters."""
        query = self.query_var.get().strip()
        if len(query) >= 3 and self.db is not None:
            try:
                from core.search import suggest_names
                self.suggestions = suggest_names(self.db, query)
            except Exception:
                self.suggestions = []
            self._render_suggestions()
        else:
            self.suggestions = []
            self.suggestion_list.pack_forget()
    def _render_suggestions(self) -> None:
        self.suggestion_list.delete(0, "end")
        for s in self.suggestions:
            self.suggestion_list.insert("end", s)
        if self.suggestions:
            if not self.suggestion_list.winfo_ismapped():
                self.suggestion_list.pack(fill="x", pady=(0, 4))
            self.suggestion_list.selection_clear(0, "end")
        else:
            self.suggestion_list.pack_forget()
    def _on_suggestion_select(self, _event: tk.Event | None = None) -> None:
        idx = self.suggestion_list.curselection()
        if idx:
            value = self.suggestion_list.get(idx[0])
            self.query_var.set(value)
            self.suggestion_list.pack_forget()
    def _on_category_changed(self, _event=None) -> None:
        """Switching group starts a new question.

        The describe-and-find box keeps a conversation - "e mai inalta" refines
        the previous description - but a description of a bird has nothing to
        do with the plants. Carrying the old keywords over would rank the new
        group by words that only described the old one.
        """
        if getattr(self, "_ai_keywords", None) or getattr(self, "_ai_history", None):
            self._ai_reset()
        self._do_search()

    def _set_view(self, mode: str) -> None:
        """Switch the navigation view and make the panes follow.

        Setting the StringVar only changes the text in the box. The combo is
        bound to <<ComboboxSelected>>, which the window manager sends when a
        person picks an item and never when code assigns one - so the label
        said "List" while the tree stayed on screen. Going through the same
        handler the user's own click does keeps the box and the panes in step.
        """
        if self.view_var.get() == self._view_map.get(mode):
            return
        self.view_var.set(self._view_map[mode])
        self._on_view_change()

    def _on_view_change(self, _event=None) -> None:
        self._render_left()
        if self.results:
            self._select_first()
    # -------------------------------------------------------------- details
    def _show_empty_details(self) -> None:
        self.detail_title.config(text=lang.t("detail_none"))
        self.detail_common.config(text="")
        self.photo_label.config(image="", text="")
        self._photo_image = None
        self.photo_nav_label.config(text="")
        self.detail_date.config(text="")
        self.detail_loc.config(text="")
        self.detail_file.config(text="")
        self.profile_text.config(state="normal")
        self.profile_text.delete("1.0", "end")
        self.profile_text.config(state="disabled")
    def _show_details(self, res: SpeciesResult) -> None:
        self.detail_title.config(text=res.scientific_name)
        common = ", ".join(part for part in (res.ro_name, res.en_name) if part)
        self.detail_common.config(
            text=lang.t("common_lbl") + " " + common if common else ""
        )
        self._render_photo()
        self._render_profile(res)
    def _render_photo(self) -> None:
        if self.current is None:
            return
        if not self.photos:
            self.photo_label.config(image="", text=lang.t("no_photo"))
            self._photo_image = None
            self.photo_nav_label.config(text="")
            self.detail_date.config(text="")
            self.detail_loc.config(text="")
            self.detail_file.config(text="")
            return
        photo = self.photos[self.photo_index]
        self.photo_nav_label.config(
            text=lang.t("photo_nav", i=self.photo_index + 1, n=len(self.photos))
        )
        self.detail_date.config(
            text=lang.t("date_lbl") + " " + (photo.photo_date or "—")
        )
        self.detail_loc.config(
            text=lang.t("loc_lbl") + " " + (photo.manual_location or "—")
        )
        self.detail_file.config(
            text=lang.t("file_lbl") + " " + (photo.catalog_path or "—")
        )
        if photo.resolved is None and not PIL_OK:
            self.photo_label.config(image="", text=lang.t("no_photo"))
            self._photo_image = None
            return
        if photo.resolved is None:
            self.photo_label.config(image="", text=lang.t("photo_missing"))
            self._photo_image = None
            return
        if not PIL_OK:
            self.photo_label.config(image="", text=lang.t("no_photo"))
            self._photo_image = None
            return
        try:
            with Image.open(photo.resolved) as img:
                img.thumbnail(PHOTO_MAX)
                self._photo_image = ImageTk.PhotoImage(img.copy())
        except Exception:
            self.photo_label.config(image="", text=lang.t("no_photo"))
            self._photo_image = None
            return
        self.photo_label.config(image=self._photo_image, text="")
    def _render_profile(self, res: SpeciesResult) -> None:
        self.profile_text.config(state="normal")
        self.profile_text.delete("1.0", "end")
        self._insert_rich_text(
            self.profile_text, res.profile_response or lang.t("no_profile")
        )
        # Layer B — secțiunea „Date structurate” (normalizată la citire).
        vocab = load_vocab(self.db.catalog_root) if self.db else None
        items = format_structured_items(res.profile_fields, vocab)
        if items:
            self.profile_text.insert(tk.END, "\n")
            self.profile_text.insert(
                tk.END, "------------------------------\n", ("rule",)
            )
            self._insert_inline_rich_text(
                self.profile_text,
                f"**{lang.t('structured_lbl')}**",
                ("body",),
            )
            self.profile_text.insert(tk.END, "\n")
            for label, value in items:
                self._insert_inline_rich_text(
                    self.profile_text, f"{label}: {value}\n", ("list",)
                )
        self.profile_text.config(state="disabled")

    def _prev_photo(self) -> None:
        if self.photos and self.photo_index > 0:
            self.photo_index -= 1
            self._render_photo()
    def _next_photo(self) -> None:
        if self.photos and self.photo_index < len(self.photos) - 1:
            self.photo_index += 1
            self._render_photo()
    # -------------------------------------------------------------- actions
    def _browse_col(self) -> None:
        """🌐 CoL: open Catalogue of Life with the name in the clipboard.

        The CoL search page does not accept a query in the URL, so the
        species name is copied automatically — on the page it is just
        Ctrl+V (same behaviour as SpecioIdentify).
        """
        name = self.current.scientific_name if self.current else ""
        name = (name or "").strip()
        if not name:
            messagebox.showinfo(lang.t("web_title"), lang.t("web_no_species"))
            return
        try:
            self.win.clipboard_clear()
            self.win.clipboard_append(name)
            self.win.update()  # keeps the clipboard after the app closes
            self.status_var.set(lang.t("web_copied_clipboard", name=name))
        except Exception:
            pass
        webbrowser.open(COL_SEARCH_URL)

    def _browse_wikipedia(self) -> None:
        """🌐 WIKIPEDIA: open the species article for the selected species."""
        name = self.current.scientific_name if self.current else ""
        name = (name or "").strip()
        if not name:
            messagebox.showinfo(lang.t("web_title"), lang.t("web_no_species"))
            return
        url = WIKIPEDIA_SPECIES_URL + quote(name.replace(" ", "_"))
        webbrowser.open(url)
        self.status_var.set(lang.t("status_web_open", name=name))

    def _open_species_folder(self) -> None:
        res = self.current
        if res is None:
            return
        for photo in res.photos:
            if photo.resolved is not None and photo.resolved.parent.is_dir():
                os.startfile(photo.resolved.parent)  # noqa: S606
                return
        messagebox.showwarning(lang.t("app_title"), lang.t("folder_missing"))

    # ------------------------------------------- describe & find (phase 3)
    #
    # The model turns free text into (field, value) filters only; the
    # filtering itself stays in core.determinator, against the real
    # catalogue. So this panel can never show a species that is not in
    # the database — see core/describe.py for the gate that enforces it.

    def _ai_settings(self) -> dict:
        s = load_settings()

        def _int(key, default):
            try:
                return int(str(s.get(key, default)).strip())
            except (TypeError, ValueError):
                return default

        try:
            threshold = float(str(s.get("describe_snap_threshold", "0.68")).strip())
        except (TypeError, ValueError):
            threshold = 0.68

        return {
            # The drop-down wins over the file: switching model in the window
            # must take effect immediately, not only after a restart.
            "model": (getattr(self, "ai_model_var", None) and
                      self.ai_model_var.get() or s.get("describe_model") or "").strip(),
            "url": (s.get("ollama_url") or "http://localhost:11434").strip(),
            "num_ctx": _int("describe_num_ctx", 16384),
            "num_predict": _int("describe_num_predict", 2000),
            "thinking": str(s.get("describe_thinking", "")).strip().lower()
            in ("1", "true", "yes", "da"),
            "threshold": threshold,
            "max_results": max(1, _int("describe_max_results", 5)),
        }

    def _build_ai_panel(self) -> None:
        cfg = self._ai_settings()
        self._ai_history: list[tuple[str, list]] = []
        self._ai_keywords: list[str] = []
        self._ai_scores: dict[str, float] = {}
        self._ai_results: list = []
        self._ai_busy = False
        self._ai_cancel = False
        self._ai_last_reply = DescribeReply()

        self.ai_panel = ttk.Labelframe(
            self.search_area, text=lang.t("ai_title"), padding=(8, 4)
        )
        row = ttk.Frame(self.ai_panel)
        row.pack(fill="x")
        self.ai_entry = ttk.Entry(row, width=46)
        self.ai_entry.pack(side="left")
        self.ai_entry.bind("<Return>", lambda _e: self._ai_run())
        self.ai_btn = ttk.Button(row, text=lang.t("ai_btn"), command=self._ai_run)
        self.ai_btn.pack(side="left", padx=(6, 0))
        self.ai_stop_btn = ttk.Button(
            row, text=lang.t("ai_cancel"), command=self._ai_cancel_run
        )
        self.ai_stop_btn.pack(side="left", padx=(6, 0))
        self.ai_stop_btn.state(["disabled"])
        self.ai_reset_btn = ttk.Button(
            row, text=lang.t("ai_reset"), command=self._ai_reset
        )
        self.ai_reset_btn.pack(side="left", padx=(6, 0))

        self._ai_models_done = False
        self._ai_models_result: list[str] = []
        # True only when the describe box was the one that opened the
        # determinator panel, so a reset can close it again. A panel the
        # user opened by hand must survive a reset untouched.
        self._ai_opened_det = False
        self._ai_refresh_models()

        self.ai_status = ttk.Label(
            self.ai_panel, text=lang.t("ai_hint"), anchor="w",
            justify="left", wraplength=900,
        )
        self.ai_status.pack(fill="x", pady=(4, 0))

        self.ai_toggle = ttk.Button(
            self.search_frame, text=lang.t("ai_title"), command=self._toggle_ai
        )
        self.ai_toggle.pack(side="left", padx=(8, 0))
        if not cfg["model"]:
            self.ai_status.configure(text=lang.t("ai_offline"))
            for w in (self.ai_entry, self.ai_btn, self.ai_stop_btn):
                w.state(["disabled"])

    def _ai_refresh_models(self) -> None:
        """Ask Ollama which models are installed, without freezing the window.

        The worker only fills a list; the widget is touched from the main
        thread through the same queue-and-poll pattern the search uses.
        """
        import queue
        import threading

        self._ai_models_queue = queue.Queue()
        self._ai_models_done = False
        url = self._ai_settings()["url"]

        def worker():
            try:
                self._ai_models_queue.put(list_models(url))
            except Exception:
                self._ai_models_queue.put([])

        threading.Thread(target=worker, daemon=True).start()
        self.win.after(40, self._ai_poll_models)

    def _ai_poll_models(self) -> None:
        try:
            models = self._ai_models_queue.get_nowait()
        except Exception:
            if not self._ai_models_done:
                self.win.after(60, self._ai_poll_models)
            return
        self._ai_models_done = True
        current = self.ai_model_var.get().strip()
        if not models:
            # Ollama unreachable: keep whatever the settings file said rather
            # than emptying the box and leaving the user with no model at all.
            self.ai_model_combo.configure(values=[current] if current else [])
            return
        if current and current not in models:
            models = [current] + models
        self.ai_model_combo.configure(values=models)
        if not current and models:
            self.ai_model_var.set(models[0])

    # Words too common in a profile to narrow anything down.
    _AI_STOPWORDS = frozenset(
        "si in de la cu pe un o care pentru este sunt are nu se ca "
        "pasare pasari planta plante animal animale"
        .split()
    )
    # Bare numbers and units match every profile that states a measurement;
    # "13-15 cm" is handled by the field filters, not by word counting.
    _AI_NUMERIC = frozenset(
        "cm mm m cm2 lungime inaltime latime greutate anvergura "
        "mas kg g ani luna zile".split()
    )
    # A word present in more than this share of the candidates cannot tell
    # them apart, so it is ignored outright instead of carrying a token weight.
    _AI_MAX_SHARE = 0.5

    def _apply_keywords(self, keywords: list[str]) -> None:
        """Rank ``self.results`` by how much of the description they contain.

        Words are compared on a short stem, so "albastra" still reaches
        "albastre" and "albastru", and each is weighted by how rare it is
        across the current candidates. A word only counts when it actually
        separates something: "cioc" occurs in 98 of 98 bird profiles and
        "petale" in 113 of 118 plants, so both are noise and are dropped. A
        leftover sliver of weight would otherwise let every species stay in
        the list with a meaningless score.

        Nothing is invented: the list is only reordered and shortened.
        """
        if not keywords:
            self._ai_scores = {}
            return
        words: set[str] = set()
        for phrase in keywords:
            for token in normalize(phrase).split():
                if len(token) >= 2 and token not in self._AI_STOPWORDS:
                    words.add(token)
        words -= set(self._AI_NUMERIC)
        if not words or not self.results:
            self._ai_scores = {}
            return

        total = len(self.results)
        texts = [normalize(r.profile_response or "") for r in self.results]

        def _stem(word: str) -> str:
            # Enough characters to survive Romanian inflection
            # (albastra / albastre / albastru) without collapsing distinct
            # words (petale / petala) into one.
            return word[:6] if len(word) >= 6 else word

        stems = {_stem(w): w for w in words}
        doc_freq = {
            stem: sum(1 for t in texts if stem in t) for stem in stems
        }
        weights = {
            stem: math.log(total / df) if df else 0.0
            for stem, df in doc_freq.items()
            if df and df <= total * self._AI_MAX_SHARE
        }
        if not weights:
            # Everything the user said is common to all candidates: the honest
            # answer is "this description does not narrow anything", so the
            # list stays as it was rather than being emptied.
            self._ai_scores = {}
            return

        scored = []
        for res, text in zip(self.results, texts):
            score = sum(v for stem, v in weights.items() if stem in text)
            if score > 0:
                scored.append((score, res))
        scored.sort(key=lambda pair: -pair[0])
        self._ai_scores = {r.scientific_name: round(n, 2) for n, r in scored}
        self.results = [r for _n, r in scored]
        self._render_left()

    def _ai_model_selected(self, _event=None) -> None:
        model = self.ai_model_var.get().strip()
        if not model:
            return
        try:
            save_setting("describe_model", model)
        except OSError as exc:
            messagebox.showwarning(
                lang.t("ai_error_title"), str(exc), parent=self.win
            )

    # ------------------------------------------------------- chat with AI (B)
    def _build_chat(self) -> None:
        """Permanent question box under the results.

        The describe box asks "which species match?". This one asks "why that
        one?", and takes follow-ups. It is fed the profiles of what is on
        screen, so the answer is grounded in the catalogue rather than in the
        model's general knowledge.

        The log is styled rather than left as plain text: a question from the
        user and an answer from the catalogue have to be tellable apart at a
        glance, and an answer can run to several sentences.
        """
        self._qa_history: list = []
        self._qa_busy = False
        self._qa_cancel = False
        self._qa_question = ""
        self._qa_sent: list[str] = []
        self._qa_pinned = None
        # Set by "new topic": the next question starts fresh, so it must not be
        # read as a follow-up and must not inherit the previous results.
        self._qa_fresh_topic = False
        # chat log line number -> the criteria that line describes, so a click
        # can bring them back into the determinator rows.
        self._qa_notes: dict[int, list] = {}
        self._qa_topic_line = 0
        self._read_win = None
        self._read_text = None
        self._read_all = False
        self._chat_open = True

        self.chat_frame = ttk.LabelFrame(
            self.win, text=lang.t("chat_title"), padding=(6, 2)
        )
        self.chat_frame.pack(side="bottom", fill="x", padx=8, pady=(4, 6))

        # The log reuses the window's shared Font objects, so Ctrl+wheel resizes
        # it together with the rest of the page instead of needing its own
        # zoom. A private font here silently stopped following the page.
        fonts = self._get_rich_fonts()
        self._chat_font = fonts["body"]
        self._chat_font_bold = fonts["bold"]

        # Packed bottom and before the log, so the controls claim their space
        # first. Packed the other way round, the expanding log took the room
        # and the row of buttons was the thing clipped away when the frame
        # got short - dragging the splitter or enlarging the font with
        # Ctrl+wheel were both enough to hide the model selector and the ask
        # button. Only the log is allowed to give way now.
        self._chat_controls = ttk.Frame(self.chat_frame)
        self._chat_controls.pack(side="bottom", fill="x")

        body = ttk.Frame(self.chat_frame)
        body.pack(fill="both", expand=True)
        self.chat_log = tk.Text(
            body, height=7, wrap="word", state="disabled",
            relief="solid", borderwidth=1, background="#ffffff",
            padx=10, pady=6, spacing1=2, spacing3=4,
            font=self._chat_font, cursor="arrow",
        )
        scroll = ttk.Scrollbar(body, orient="vertical")
        self.chat_log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.chat_log.pack(side="left", fill="both", expand=True)
        self.chat_log.tag_configure("question", font=self._chat_font_bold,
                                    foreground="#1a3a5c", spacing1=8)
        self.chat_log.tag_configure("answer", font=self._chat_font,
                                    foreground="#222222", lmargin1=14)
        self.chat_log.tag_configure("label", font=self._chat_font_bold,
                                    foreground="#6a7a3a", lmargin1=14)
        self.chat_log.tag_configure("note", font=self._chat_font,
                                    foreground="#777777", lmargin1=14)
        # One bold variant per colour already in use, so a marked-up species
        # name keeps the colour of the block it sits in.
        for name, colour in (("answer", "#222222"), ("question", "#1a3a5c"),
                             ("label", "#6a7a3a"), ("note", "#777777")):
            self.chat_log.tag_configure(
                name + "_bold", font=self._chat_font_bold,
                foreground=colour, lmargin1=14,
            )
        # Criteria notes are clickable, so they have to look like it.
        self.chat_log.tag_configure(
            "note_link", font=self._chat_font,
            foreground="#1a5fb4", lmargin1=14, underline=True,
        )
        self.chat_log.tag_bind("note_link", "<Button-1>", self._qa_note_clicked)

        row = ttk.Frame(self._chat_controls)
        row.pack(fill="x", pady=(5, 0))
        # The model selector lives with the question box. It drives both AI
        # paths, but asking is where the choice gets made, so that is where it
        # belongs - and it leaves the find box with one job only.
        ttk.Label(row, text=lang.t("ai_model_lbl")).pack(side="left")
        self.ai_model_var = tk.StringVar(value=self._ai_settings()["model"])
        self.ai_model_combo = ttk.Combobox(
            row, textvariable=self.ai_model_var, state="readonly", width=20,
        )
        self.ai_model_combo.pack(side="left", padx=(4, 0))
        self.ai_model_combo.bind(
            "<<ComboboxSelected>>", self._ai_model_selected
        )
        ttk.Button(
            row, text=lang.t("ai_model_refresh"),
            command=self._ai_refresh_models, width=3,
        ).pack(side="left", padx=(4, 0))
        self._chat_new_btn = ttk.Button(
            row, text=lang.t("chat_new"), command=self._qa_new_topic, width=12,
        )
        self._chat_new_btn.pack(side="right")
        ttk.Button(
            row, text=lang.t("chat_read"), command=self._qa_read_window, width=9,
        ).pack(side="right", padx=(0, 6))

        row2 = ttk.Frame(self._chat_controls)
        row2.pack(fill="x", pady=(4, 0))
        self.why_btn = ttk.Button(
            row2, text=lang.t("chat_why"), command=self._qa_ask_why, width=9
        )
        self.why_btn.pack(side="left")
        self.chat_entry = ttk.Entry(row2, font=self._chat_font)
        self.chat_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.chat_entry.bind("<Return>", lambda _e: self._qa_ask())
        self.chat_send = ttk.Button(
            row2, text=lang.t("chat_send"), command=self._qa_ask, width=11
        )
        self.chat_send.pack(side="left", padx=(6, 0))
        self.chat_stop = ttk.Button(
            row2, text=lang.t("ai_cancel"), command=self._qa_cancel_run, width=9
        )
        self.chat_stop.pack(side="left", padx=(6, 0))
        self.chat_stop.state(["disabled"])
        self._toggle_chat_btn = ttk.Button(
            row2, text="▾", width=3, command=self._toggle_chat
        )
        self._toggle_chat_btn.pack(side="left", padx=(6, 0))
        self._chat_append(lang.t("chat_hint"), tag="note")

    def _qa_new_topic(self) -> None:
        """Start a fresh subject: the next question ignores earlier answers.

        The history is what lets a follow-up say "and in winter?". It is also
        what made a new question answer the old one: the model was told the
        blue lanceolate-leaved flower conversation, so it reused that
        description for a yellow flower. Clearing it makes the split explicit
        and the user controls it.
        """
        self._qa_history = []
        self._qa_question = ""
        self._qa_sent = []
        self._qa_pinned = None
        self._qa_fresh_topic = True
        # Line in the log where the current subject starts. The reading window
        # shows from here down, so a finished subject does not follow the user
        # into the next one.
        self._qa_topic_line = 0
        self._chat_append(lang.t("chat_new_topic"), tag="note")
        self._qa_topic_line = int(self.chat_log.index("end-2l").split(".")[0])

    def _chat_segments(self, start_line: int = 0):
        """The log as (text, is_bold, tag) runs, for the read-along window.

        ``start_line`` drops everything above it, which is how the reading
        window shows one subject at a time. Read out of the widget rather than
        kept alongside it, so the two cannot drift apart: whatever is on
        screen, tags and all, is what the separate window shows.
        """
        runs = []
        for element in self.chat_log.dump("1.0", "end", text=True):
            # dump reports the run and its position but not the run's tags, so
            # those are read back from the widget for the index it reports.
            if element[0] != "text" or not element[1]:
                continue
            if int(element[2].split(".")[0]) < start_line:
                continue
            base = "note"
            bold = False
            for name in self.chat_log.tag_names(element[2]):
                if name in ("question", "label", "note"):
                    base = name
                elif name.endswith("_bold"):
                    bold = True
            runs.append((element[1], bold, base))
        return runs

    def _qa_read_window(self) -> None:
        """Open the conversation in its own window, at a readable width.

        The log is as wide as the window, and a 100-character line is past the
        point where the eye can find the start of the next one. A separate
        window lets the line get short without taking the results away, so the
        answer can be read next to the species it is about.

        Only the current subject is shown. "New topic" is the user saying this
        exchange is finished, so carrying the finished one into the new one
        would fill the page with text about a species they have moved on from.
        The full log is still in the main window, scrolled, for when it is
        wanted.
        """
        if getattr(self, "_read_win", None) is not None and self._read_win.winfo_exists():
            self._read_win.deiconify()
            self._read_win.lift()
            self._read_fill()
            return
        top = tk.Toplevel(self.win)
        top.title(lang.t("chat_read_title"))
        # ~70 characters: the width a line actually stays readable at.
        top.geometry("760x620")
        top.minsize(380, 240)
        self._read_win = top
        # All three wheel spellings, exactly as the main window binds them.
        # A precision trackpad sends <Control-MouseWheel> and a notched wheel
        # sends <Control-Button-4/5>; binding only the latter left the reading
        # window dead on the machine whose main window worked.
        for widget in (top,):
            for wheel in _ZOOM_WHEELS:
                widget.bind(wheel, self._zoom_page)
        bar = ttk.Frame(top, padding=(8, 6, 8, 0))
        bar.pack(fill="x")
        self._read_scope = ttk.Label(bar, anchor="w")
        self._read_scope.pack(side="left")
        self._read_toggle = ttk.Button(
            bar, text=lang.t("chat_read_all"), command=self._qa_read_scope, width=14,
        )
        self._read_toggle.pack(side="right")
        fonts = self._get_rich_fonts()
        frame = ttk.Frame(top, padding=8)
        frame.pack(fill="both", expand=True)
        text = tk.Text(
            frame, wrap="word", font=fonts["body"], padx=14, pady=10,
            spacing1=4, spacing3=8, background="#ffffff", relief="solid",
            borderwidth=1, cursor="arrow",
        )
        for wheel in _ZOOM_WHEELS:
            text.bind(wheel, self._zoom_page)
        self._read_text = text
        bar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.tag_configure("question", font=fonts["bold"], foreground="#1a3a5c",
                           spacing1=10)
        text.tag_configure("label", font=fonts["bold"], foreground="#6a7a3a")
        text.tag_configure("note", font=fonts["body"], foreground="#777777")
        text.tag_configure("link", font=fonts["body"], foreground="#1a5fb4",
                           underline=True)
        self._read_fill()

    def _qa_read_scope(self) -> None:
        """Switch the reading window between this subject and the whole log.

        The subject view is the one you want while working; going back to a
        finished subject to compare two species needs the other one, and
        re-reading everything by scrolling up in a narrow window is no fun.
        """
        self._read_all = not getattr(self, "_read_all", False)
        self._read_fill()

    def _read_fill(self, jump_to_end: bool = True) -> None:
        """Put the current subject in the reading window, and keep it current.

        Refilled whenever the log changes while the window is open, so an
        answer that arrives after it was opened still shows up instead of the
        window sitting on a stale snapshot. A refill triggered by zooming
        passes ``jump_to_end=False`` and keeps the line the reader was on:
        scrolling to the end on every Ctrl+wheel threw the page away under
        the cursor, which is what made the resize look like it had done
        nothing at all.
        """
        text = getattr(self, "_read_text", None)
        if text is None or not text.winfo_exists():
            return
        whole = getattr(self, "_read_all", False)
        if getattr(self, "_read_scope", None) is not None:
            self._read_scope.configure(text=lang.t(
                "chat_read_scope_all" if whole else "chat_read_scope"
            ))
            self._read_toggle.configure(text=lang.t(
                "chat_read" if whole else "chat_read_all"
            ))
        # The first line on screen, as a fraction of the old text, so the same
        # part of the answer is still under the reader's eye afterwards.
        was_at_end = text.yview()[1] >= 0.999
        first = text.index("@0,0")
        text.configure(state="normal")
        text.delete("1.0", "end")
        start = 0 if whole else self._qa_topic_line
        for chunk, bold, tag in self._chat_segments(start):
            name = "link" if (tag == "note" and bold) else tag
            if tag != "note" and bold:
                name = "question"
            text.insert("end", chunk, name)
        text.configure(state="disabled")
        if jump_to_end and not was_at_end:
            text.see(first)
        elif jump_to_end:
            text.see("end")
        else:
            text.see(first)

    def _chat_drag_start(self, event) -> None:
        """Remember where the split was, so the drag is measured from it."""
        self._chat_drag = {
            "y": event.y_root,
            "height": self.chat_frame.winfo_height(),
        }
        self._chat_grip.configure(background=self._GRIP_HOT)

    def _chat_drag_move(self, event) -> None:
        """Grow the log upward: dragging up makes it taller, not shorter.

        The pointer moves up while the log grows, which is the way every other
        splitter on screen behaves. The minimum keeps a few lines; the maximum
        leaves the results at least a third of the window, so the log can never
        be dragged until there is nothing left to read about.
        """
        if not getattr(self, "_chat_drag", None):
            return
        window = self.win.winfo_height()
        wanted = self._chat_drag["height"] - (event.y_root - self._chat_drag["y"])
        # A minimum, never a fixed height: the controls row needs its own space
        # whatever happens, and pinning the frame would clip it again as soon
        # as the log was asked for a few more lines.
        needed = self._chat_controls.winfo_reqheight() + 40
        self.chat_frame.configure(height=max(needed, min(window - 220, wanted)))
        # The frame now has a height of its own, so it must stop deriving one
        # from the log. The controls are packed at the bottom first, so they
        # are still served before the log gets what is left.
        self.chat_frame.pack_propagate(False)

    def _chat_drag_end(self, _event) -> None:
        self._chat_drag = None
        self._chat_grip.configure(background=self._GRIP_IDLE)

    def _work_area(self) -> tuple[int, int]:
        """The screen rectangle a window may actually occupy, taskbar excluded.

        Using the raw screen height is the usual shortcut and it is wrong by
        exactly the height of the taskbar, which is what pushed the bottom row
        off. Falls back to the plain screen if the call is unavailable.
        """
        if self._work_area_cache is not None:
            return self._work_area_cache
        area: tuple[int, int] = (0, self.win.winfo_screenheight())
        try:
            import ctypes

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long),
                ]

            rect = RECT()
            # SPI_GETWORKAREA
            if (ctypes.windll.user32.SystemParametersInfoW(
                    0x0030, 0, ctypes.byref(rect), 0)
                    and rect.right > rect.left and rect.bottom > rect.top):
                area = (rect.top, rect.bottom)
        except Exception:
            pass
        self._work_area_cache = area
        return area

    def _keep_on_screen(self, event=None) -> None:
        """Nudge the window back up when its bottom row leaves the work area.

        The offset matters: wm geometry "+x+y" places the outer frame while
        winfo_rooty() reports the client area, and the title bar sits between
        them. Correcting with the raw number never actually brought the bottom
        into view, so the window was repositioned on every <Configure> for as
        long as it was held there. The gap is measured once and reused.
        """
        if event is not None and event.widget is not self.win:
            return
        if self._placing is None or self._placing:
            return
        if not self.win.winfo_ismapped():
            return
        top, bottom = self._work_area()
        height = self.win.winfo_height()
        if height >= bottom - top:
            return  # taller than the work area: moving it cannot help
        y = self.win.winfo_rooty()
        if y + height <= bottom:
            return
        self._placing = True
        try:
            wanted = max(top, bottom - height) - self._frame_offset()
            self.win.geometry(f"+{self.win.winfo_rootx()}+{wanted}")
        finally:
            self.win.after_idle(self._clear_placing)

    def _frame_offset(self) -> int:
        """How far the client area sits below the position wm geometry was given.

        Measured, not assumed: it is the title bar plus the border, and both
        follow the Windows theme and the user's display settings. Asking the
        window manager to put the outer frame at the position the client
        reports, then reading back where the client landed, gives the gap.
        """
        cached = getattr(self, "_frame_offset_cache", None)
        if cached is not None:
            return cached
        offset = 0
        try:
            before = self.win.winfo_rooty()
            self.win.geometry(f"+{self.win.winfo_rootx()}+{before}")
            self.win.update_idletasks()
            offset = self.win.winfo_rooty() - before
        except Exception:
            offset = 0
        self._frame_offset_cache = offset
        return offset

    def _clear_placing(self) -> None:
        self._placing = False

    def _toggle_chat(self) -> None:
        """Collapse the log so the species list gets the height back."""
        self._chat_open = not self._chat_open
        if self._chat_open:
            self.chat_log.pack(side="left", fill="both", expand=True)
            self._toggle_chat_btn.configure(text="▾")
        else:
            self.chat_log.pack_forget()
            self._toggle_chat_btn.configure(text="▴")

    def _chat_append(self, text: str, tag: str = "answer", note_for=None) -> None:
        """Add one block, honouring the **bold** the model writes.

        The species names come back marked up, and a Text widget has no idea
        what "**" means, so the markers are turned into real bold runs instead
        of being shown or stripped. When ``note_for`` is given the line is
        stored as clickable and that criteria can be brought back on click.
        """
        bold_tag = tag + "_bold"
        self.chat_log.configure(state="normal")
        for chunk, is_bold in parse_markup(text):
            self.chat_log.insert("end", chunk, (bold_tag if is_bold else tag,))
        # Read the line back after writing: "end-1c" is then the end of the line
        # just added, whether the log was empty before or not.
        line = int(self.chat_log.index("end-1c").split(".")[0])
        if note_for:
            self._qa_notes[line] = list(note_for)
            self.chat_log.tag_add("note_link", f"{line}.0", f"{line}.end")
        self.chat_log.insert("end", "\n")
        self.chat_log.configure(state="disabled")
        if getattr(self, "_read_text", None) is not None and self._read_text.winfo_exists():
            self._read_fill()
        self.chat_log.see("end")

    def _qa_cancel_run(self) -> None:
        self._qa_cancel = True

    def _toggle_ai(self) -> None:
        if self.ai_panel.winfo_ismapped():
            self.ai_panel.pack_forget()
        else:
            self.ai_panel.pack(fill="x", pady=(4, 0))
        self._apply_page_fonts()

    def _qa_candidates(self, ignore_current: bool = False) -> list:
        """Species the model is allowed to talk about: what is on screen.

        ``ignore_current`` drops the selected species, used for the first
        question of a new subject: the selection belongs to the subject the
        user just closed, and letting it lead the list is how the old answer
        came back under a new question.
        """
        chosen: list = []
        if self.current is not None and not ignore_current:
            chosen.append(self.current)
        seen = {r.scientific_name for r in chosen}
        for res in self.results:
            if res.scientific_name not in seen:
                chosen.append(res)
                seen.add(res.scientific_name)
        return chosen

    def _qa_ask_why(self) -> None:
        """Ask about one species without re-running the filter phase.

        "Why this one?" is a question about something already chosen, so it
        skips straight to the answer and leaves the list on screen alone.
        """
        target = self.current or (self.results[0] if self.results else None)
        if target is None:
            self._chat_append(lang.t("chat_no_species"))
            return
        question = lang.t("chat_why_q", name=target.scientific_name)
        self._qa_ask(only_species=target, text=question)

    def _qa_ask(self, only_species=None, text=None) -> None:
        if self._qa_busy or self.db is None:
            return
        question = (text if text is not None else self.chat_entry.get()).strip()
        if not question:
            return
        cfg = self._ai_settings()
        if not cfg["model"]:
            self._chat_append(lang.t("ai_offline"))
            return
        self._chat_append(lang.t("chat_you") + "  " + question, tag="question")
        if text is None:
            self.chat_entry.delete(0, "end")
        self._qa_question = question

        if only_species is not None:
            # Pinned: the answer phase must see only this one species.
            self._qa_pinned = only_species
            self._qa_sent = [only_species.scientific_name]
            self._qa_busy = True
            self._qa_cancel = False
            self.chat_send.state(["disabled"])
            self.chat_stop.state(["!disabled"])
            self.status_var.set(lang.t("chat_thinking"))
            self._qa_spawn_answer(question, cfg)
            self.win.after(40, self._qa_poll)
            return

        base = self._qa_group_base()
        # Keep the category box honest: if the question named a group, show it.
        named = self._qa_named_group()
        if named and named in self._cat_displays:
            self.cat_box.set(named)
        if not base:
            self._chat_append(lang.t("chat_no_species"))
            return
        vocab = load_vocab(self.db.catalog_root)
        menu = build_menu(base, vocab)
        if not menu:
            self._chat_append(lang.t("chat_no_species"))
            return

        # Phase 1: the model reads the description and chooses the filters.
        # Phase 2 (see _qa_poll) answers from the profiles that survive them.
        filter_prompt = build_prompt(
            menu, vocab, question, [], lang.current_language()
        )

        import queue
        import threading

        self._qa_queue = queue.Queue()
        self._qa_busy = True
        self._qa_cancel = False
        self.chat_send.state(["disabled"])
        self.chat_stop.state(["!disabled"])
        self.status_var.set(lang.t("chat_filtering"))

        def worker():
            raw = None
            error = None
            try:
                if not check_ollama(cfg["url"]):
                    error = lang.t("ai_error_ollama")
                else:
                    raw = get_response(generate(
                        cfg["url"], cfg["model"], filter_prompt,
                        num_ctx=cfg["num_ctx"],
                        num_predict=cfg["num_predict"],
                        thinking=cfg["thinking"],
                    ))
            except Exception as exc:
                error = str(exc)
            self._qa_queue.put(("filters", raw, error, question))

        threading.Thread(target=worker, daemon=True).start()
        self.win.after(40, self._qa_poll)

    def _qa_group_base(self) -> list:
        """Whole group, ignoring whatever is filtered on screen.

        The question box is deliberately independent of the search above it:
        a new sighting is a new question, not a refinement of the last one.
        A group named in the question ("v-am vazut o planta...") pins the
        base to that group, so the model cannot answer with birds.
        """
        category = None
        if self.cat_box.get() in self._cat_displays:
            category = self._cat_values[self._cat_displays.index(self.cat_box.get())]
        named = self._qa_named_group()
        if named:
            category = named
        return search_species(self.db, "", None, category)

    def _qa_named_group(self) -> str | None:
        return detect_group(self._qa_question)

    def _ai_apply_reply(self, base, vocab, reply, cfg, show_rows=True) -> int:
        """Run one model reply as filters, then rank by its keywords.

        Shared by the describe box and the question box so both filter the same
        way. ``show_rows`` is what separates them: the describe box writes the
        criteria into the visible rows, because showing them is the point of a
        search box. The question box keeps them off screen and offers them as a
        clickable note in the chat, so a follow-up question does not spend half
        the window on a panel nobody is reading.
        Returns the number of results left.
        """
        active = list(reply.constraints)
        if active:
            self._det_mode = "free"
            self.det_active = True
            if show_rows:
                if not self.det_panel.winfo_ismapped():
                    self.det_panel.pack(fill="x", pady=(4, 0))
                    self._ai_opened_det = True
                self._ai_sync_rows(active)
                self._do_search()
            else:
                # Applied straight to the group, bypassing the rows, and the
                # rows are cleared so nothing on screen disagrees with the
                # list. Clicking the note in the chat puts them back.
                self._ai_sync_rows([])
                if self._ai_opened_det and self.det_panel.winfo_ismapped():
                    self.det_panel.pack_forget()
                    self._ai_opened_det = False
                self._ai_apply_constraints(base, active, vocab)
        else:
            # No structured filter this time, so the rows must go too. Leaving
            # the previous question's rows in place showed plant criteria over
            # a list of mammals, and the next search silently applied them -
            # so the list could jump from 2 results to 17 with nothing in the
            # window to explain it. The rows always mirror what is applied.
            self._ai_sync_rows([])
            # An empty panel still eats half the window while showing nothing.
            # If the AI was the one that opened it, close it again; a panel the
            # user opened by hand is left alone, as it already was on reset.
            if self._ai_opened_det and self.det_panel.winfo_ismapped():
                self.det_panel.pack_forget()
                self._ai_opened_det = False
            self.results = list(base)
            self._det_status = {}
        self._ai_keywords = [k for k in reply.keywords if k]
        self._apply_keywords(self._ai_keywords)
        self._set_view("list")
        return len(self.results)

    def _ai_apply_constraints(self, base, constraints, vocab) -> None:
        """Filter ``base`` by ``constraints`` and show the result, no rows.

        The same order _do_search uses: confirmed traits first, then species
        that only answered some of them.
        """
        exact, incomplete = determine(base, list(constraints), vocab)
        exact.sort(key=lambda m: -len(m.matched))
        incomplete.sort(key=lambda m: -len(m.matched))
        self._det_base = base
        self.results = [m.species for m in exact] + [m.species for m in incomplete]
        self._det_status = {
            m.species.scientific_name: m.status for m in exact + incomplete
        }
        self._render_left()
        self._first_search_done = True

    def _qa_reason(self, reply) -> str:
        """Say out loud what narrowed the list, in the order it happened.

        A question like "a rodent of medium size" produces no criteria at all,
        only a search over the profile text. Empty rows plus a short list looked
        like the filter had been lost, so the reason is named explicitly instead
        of left to be inferred from which species survived.
        """
        parts = []
        if reply.constraints:
            parts.append(lang.t(
                "chat_reason_fields",
                names="; ".join(
                    f"{c.field} = {c.value}" for c in reply.constraints
                ),
            ))
        words = [w for w in reply.keywords if w]
        if words:
            parts.append(
                lang.t("chat_reason_words", names=", ".join(words))
            )
        if not parts:
            return lang.t("chat_reason_none")
        text = " · ".join(parts)
        # The "press here" hint only when there is something to press: a note
        # built from keywords alone has no criteria to bring back, so promising
        # a click there would be a dead end.
        if reply.constraints:
            return lang.t("chat_reason", text=text)
        return text

    def _qa_note_clicked(self, event) -> str | None:
        """Open the determinator for the criteria note that was clicked.

        The criteria live off screen on purpose, so this is the way to see or
        correct them: click the note, get the same editable rows the describe
        box fills in. One click, not a permanent second copy of the filter.
        """
        # Tk wants a full @x,y pixel position, not a bare y.
        line = int(self.chat_log.index(f"@0,{int(event.y)}").split(".")[0])
        constraints = self._qa_notes.get(line)
        if not constraints:
            return None
        self._det_mode = "free"
        self.det_active = True
        if not self.det_panel.winfo_ismapped():
            self.det_panel.pack(fill="x", pady=(4, 0))
            self._ai_opened_det = True
        self._ai_sync_rows(list(constraints))
        self._do_search()
        self.status_var.set(lang.t("chat_filters_opened"))
        return "break"

    def _qa_poll(self) -> None:
        """Two-phase turn: apply the model's filters, then answer from them."""
        try:
            kind, raw, error, question = self._qa_queue.get_nowait()
        except Exception:
            if self._qa_busy:
                self.win.after(60, self._qa_poll)
            return

        if kind == "filters":
            if error or self._qa_cancel:
                self._qa_end_turn(error)
                return
            cfg = self._ai_settings()
            base = self._qa_group_base()
            vocab = load_vocab(self.db.catalog_root)
            menu = build_menu(base, vocab)
            try:
                reply = parse_reply(raw, menu, vocab, cfg["threshold"])
            except Exception:
                reply = DescribeReply()
            reply.keywords = keep_asked_keywords(reply.keywords, question)
            # The model found nothing to filter on, which normally means a
            # question about what is already on screen ("ce mananca?"), not a
            # description, so the current results are kept. Not right after
            # "new topic" though: the user just declared the previous subject
            # closed, and keeping its results answered the new question from
            # them - the old species came back under a new question.
            fresh = self._qa_fresh_topic
            self._qa_fresh_topic = False
            if not reply.constraints and not reply.keywords and not fresh:
                if not self.results:
                    self._ai_apply_reply(base, vocab, reply, cfg, show_rows=False)
            else:
                self._ai_apply_reply(base, vocab, reply, cfg, show_rows=False)
            self._qa_sent = [r.scientific_name for r in self.results[:MAX_PROFILES]]
            self.status_var.set(lang.t("chat_found", n=len(self.results)))
            if not self.results:
                self._qa_end_turn(None, note=lang.t("chat_nothing"))
                return
            self._chat_append(
                self._qa_reason(reply), tag="note",
                note_for=reply.constraints or None,
            )
            self._qa_spawn_answer(question, cfg, ignore_current=fresh)
            self.win.after(40, self._qa_poll)
            return

        if error or self._qa_cancel:
            self._qa_end_turn(error)
            return
        text = (raw or "").strip() or lang.t("chat_empty")
        self._qa_end_turn(None, answer=text, question=question)

    def _qa_spawn_answer(self, question: str, cfg, ignore_current: bool = False) -> None:
        """Second call: the answer, grounded in whatever survived the filters."""
        if self._qa_pinned is not None:
            species = [self._qa_pinned]
            self._qa_pinned = None
        else:
            species = self._qa_candidates(ignore_current)[:MAX_PROFILES]
        if not species:
            self._qa_end_turn(None, note=lang.t("chat_nothing"))
            return
        prompt = build_qa_prompt(
            species, question, self._qa_history, lang.current_language()
        )
        self.status_var.set(lang.t("chat_thinking"))

        import threading

        def worker():
            answer = None
            error = None
            try:
                if not check_ollama(cfg["url"]):
                    error = lang.t("ai_error_ollama")
                else:
                    answer = get_response(generate(
                        cfg["url"], cfg["model"], prompt,
                        num_ctx=cfg["num_ctx"],
                        num_predict=max(cfg["num_predict"], 1200),
                        thinking=cfg["thinking"],
                    ))
            except Exception as exc:
                error = str(exc)
            self._qa_queue.put(("answer", answer, error, question))

        threading.Thread(target=worker, daemon=True).start()

    def _qa_end_turn(self, error, answer=None, question=None, note=None) -> None:
        self._qa_busy = False
        self.chat_send.state(["!disabled"])
        self.chat_stop.state(["disabled"])
        if error:
            self._chat_append(error, tag="note")
        elif note:
            self._chat_append(note, tag="note")
        elif answer is not None:
            self._chat_append(lang.t("chat_bot"), tag="label")
            self._chat_append(answer, tag="answer")
            if question:
                self._qa_history.append(
                    QaTurn(question, answer, list(self._qa_sent))
                )
                if len(self._qa_history) > 8:
                    del self._qa_history[:-8]
        self.status_var.set("")

    def _ai_candidates(self) -> list:
        """The species the model is allowed to talk about right now."""
        if self.db is None:
            return []
        if self.results:
            return list(self.results)
        return search_species(self.db, "", None, None)

    def _ai_cancel_run(self) -> None:
        self._ai_cancel = True

    def _ai_reset(self) -> None:
        self._ai_history = []
        self._ai_keywords = []
        self._ai_results = []
        self._ai_scores = {}
        self._ai_last_reply = DescribeReply()
        self.ai_entry.delete(0, "end")
        self._ai_sync_rows([])
        # Emptying the rows is not enough: the panel itself was packed open by
        # the describe box, and an empty frame still occupies vertical space.
        # Close it too, but only if we are the ones who opened it.
        if self._ai_opened_det:
            self.det_panel.pack_forget()
            self._ai_opened_det = False
        self.det_active = False
        self._do_search()
        self.ai_status.configure(text=lang.t("ai_hint"))

    def _ai_run(self) -> None:
        if self._ai_busy or self.db is None:
            return
        question = self.ai_entry.get().strip()
        if not question:
            return
        cfg = self._ai_settings()
        if not cfg["model"]:
            self.ai_status.configure(text=lang.t("ai_offline"))
            return
        base = self._ai_candidates()
        if not base:
            self.ai_status.configure(text=lang.t("ai_no_result"))
            return
        vocab = load_vocab(self.db.catalog_root)
        menu = build_menu(base, vocab)
        if not menu:
            self.ai_status.configure(text=lang.t("ai_no_result"))
            return
        prompt = build_prompt(
            menu, vocab, question, self._ai_history, lang.current_language()
        )

        self._ai_busy = True
        self._ai_cancel = False
        self.ai_status.configure(text=lang.t("ai_busy"))
        self.ai_btn.state(["disabled"])
        self.ai_stop_btn.state(["!disabled"])

        import queue
        import threading
        import time as _time

        self._ai_queue = queue.Queue()

        def worker():
            payload = None
            error = None
            started = _time.perf_counter()
            elapsed = 0.0
            try:
                if not check_ollama(cfg["url"]):
                    error = lang.t("ai_error_ollama")
                else:
                    data = generate(
                        cfg["url"], cfg["model"], prompt,
                        num_ctx=cfg["num_ctx"],
                        num_predict=cfg["num_predict"],
                        thinking=cfg["thinking"],
                    )
                    payload = get_response(data)
            except OllamaError as exc:
                error = str(exc)
            except Exception as exc:  # a worker must never kill the window
                error = str(exc)
            # Reported next to the model name so switching models in the
            # drop-down is an actual comparison, not a guess.
            elapsed = _time.perf_counter() - started
            self._ai_queue.put((payload, error, elapsed))

        threading.Thread(target=worker, daemon=True).start()
        # after() is only safe from the main thread, so the worker hands the
        # result to a queue and the main thread polls it.
        self.win.after(40, self._ai_poll, question, menu, vocab, cfg)

    def _ai_poll(self, question, menu, vocab, cfg) -> None:
        """Main-thread poller for the worker's result."""
        try:
            payload, error, elapsed = self._ai_queue.get_nowait()
        except Exception:
            if self._ai_busy:
                self.win.after(40, self._ai_poll, question, menu, vocab, cfg)
            return
        self._ai_finish(question, payload, error, menu, vocab, cfg, elapsed)

    def _ai_sync_rows(self, constraints: list) -> None:
        """Mirror the model's filters into the determinator rows.

        Writing them into the real rows is what makes the choice inspectable:
        the user sees exactly which traits were applied and can correct or
        delete any of them by hand, like any other criterion.
        """
        for row in list(self.det_rows):
            row["frame"].destroy()
        self.det_rows = []
        for c in constraints:
            self._det_add_row()
            row = self.det_rows[-1]
            row["field_key"] = c.field
            row["field_box"].set(c.field)
            row["value_box"].set(c.value)
        self._det_refresh_options()

    def _ai_finish(self, question, payload, error, menu, vocab, cfg, elapsed=0.0) -> None:
        self._ai_busy = False
        self.ai_btn.state(["!disabled"])
        self.ai_stop_btn.state(["disabled"])
        if self._ai_cancel:
            self.ai_status.configure(text=lang.t("ai_hint"))
            return
        if error:
            messagebox.showwarning(lang.t("ai_error_title"), error, parent=self.win)
            self.ai_status.configure(text=lang.t("ai_hint"))
            return

        reply = parse_reply(payload or "", menu, vocab, cfg["threshold"])
        self._ai_last_reply = reply
        self._ai_history.append((question, list(reply.constraints)))

        # Last resort, and a guarantee: whatever happens upstream, a question
        # the user typed is never thrown away. Models refuse short prompts -
        # "floare albastra" came back as "{}" with a note that there was "not
        # enough detail" - and an empty reply must still search for the words
        # the user actually wrote, which is exactly what keywords are for.
        if not reply.constraints and not reply.keywords:
            reply.keywords = [question]

        # Keywords accumulate in their own list. They cannot live in the
        # per-field dict below: they all share one pseudo-field, so each new
        # phrase would overwrite the previous one.
        for word in reply.keywords:
            if not any(word.casefold() == k.casefold() for k in self._ai_keywords):
                self._ai_keywords.append(word)

        # Every turn contributes to one filter set, so "e mai inalta" refines
        # the previous description instead of replacing it.
        merged: dict[str, object] = {}
        for _text, constraints in self._ai_history:
            for c in constraints:
                merged[c.field] = c
        active = list(merged.values())
        keywords = list(self._ai_keywords)

        if not active and not keywords:
            self._ai_sync_rows([])
            self._do_search()
            self.ai_status.configure(text=lang.t("ai_no_result"))
            return

        # Hand the filters to the deterministic panel and let the normal
        # search path render them: one result list, one set of rules.
        self._det_mode = "free"
        self.det_active = True
        if not self.det_panel.winfo_ismapped():
            self.det_panel.pack(fill="x", pady=(4, 0))
            self._ai_opened_det = True
        self._ai_sync_rows(active)
        self._do_search()

        # A described search is a flat ranking, not a taxonomy. The tree
        # groups by lineage and re-orders the list the user just ranked, so
        # switch to the flat view and let the normal selection take over.
        self._set_view("list")

        # Phrases the field list could not express are matched against the
        # profile text. A phrase is scored, not filtered: a description like
        # "cioc galben" never appears verbatim in a profile ("cioc" and
        # "galben" sit far apart), so a substring test would find nothing and
        # silently show everything. Counting the words that DO occur ranks the
        # catalogue instead of hiding it, and the species still come from the
        # database - the words only decide which of them are worth showing.
        self._ai_keywords = list(keywords)
        self._apply_keywords(self._ai_keywords)

        # Safety net: the model picks the constraints, and one over-eager
        # guess (a "frunza_dispozitie" nobody mentioned) can empty the list
        # even though the words clearly match something. Rather than showing a
        # bare "no result", fall back to the text ranking and say so - the
        # filters stay visible in the determinator rows, so the user can see
        # what was dropped and re-apply it deliberately.
        if not self.results and active and self._ai_keywords:
            self._ai_sync_rows([])
            self.det_active = False
            self._do_search()
            self._apply_keywords(self._ai_keywords)
            dropped_filters = ", ".join(f"{c.field}={c.value}" for c in active)
            if self.results:
                self.ai_status.configure(
                    text=lang.t("ai_relaxed", filters=dropped_filters)
                )
                return

        notes = []
        for now, was in reply.snapped.items():
            notes.append(lang.t("ai_snapped", was=was, now=now))
        if reply.dropped:
            notes.append(lang.t("ai_dropped", items=", ".join(reply.dropped)))
        if reply.unknown_fields:
            notes.append(
                lang.t("ai_unknown_field", fields=", ".join(reply.unknown_fields))
            )
        used = ", ".join(f"{c.field}={c.value}" for c in active)
        if keywords:
            prefix = (used + " · ") if used else ""
            used = prefix + lang.t("ai_words") + " " + ", ".join(
                f'"{k}"' for k in keywords
            )
        line = lang.t("ai_used") + " " + used if used else lang.t("ai_hint")
        if notes:
            line += "  ·  " + "  ·  ".join(notes)
        if elapsed:
            # Model name + time: the drop-down only earns its place if the
            # user can see what each choice costs.
            line += "  ·  " + f"{cfg['model']}  {lang.t('ai_elapsed', sec=f'{elapsed:.1f}')}"
        self.ai_status.configure(text=line)



def main() -> None:
    root = tk.Tk()
    CatalogBrowser(root)
    root.mainloop()
if __name__ == "__main__":
    main()
