import asyncio
import aiohttp
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import json
import re
import copy
from datetime import datetime
from threading import Thread, Lock
import queue
import time

SKIP_HEADERS = {"content-length", "accept-encoding", "connection", "te", "transfer-encoding"}

_BG     = "#1e1e2e"
_PANEL  = "#252535"
_CARD   = "#2d2d42"
_BORDER = "#414160"
_FG     = "#cdd6f4"
_MUTED  = "#6c7086"
_BLUE   = "#89b4fa"
_GREEN  = "#a6e3a1"
_RED    = "#f38ba8"
_YELLOW = "#f9e2af"
_PURPLE = "#cba6f7"
_CYAN   = "#89dceb"
_ORANGE = "#fab387"

SECTION_COLORS = [_BLUE, _RED, _GREEN, _ORANGE]


def extract_json_body(raw: str):
    """Extract (url, headers, json_data) from a raw HTTP request or bare JSON paste."""
    lines = raw.strip().split('\n')
    url, headers = None, {}

    first = lines[0].strip()
    m = re.match(r"^(POST|GET|PUT|PATCH|DELETE)\s+(\S+)\s+HTTP/\S+$", first, re.I)
    if m:
        path = m.group(2)
        for line in lines[1:]:
            line = line.strip()
            if not line:
                break
            if ':' in line and not line.startswith('{'):
                k, _, v = line.partition(':')
                k = k.strip()
                if k.lower() not in SKIP_HEADERS:
                    headers[k] = v.strip()
        host = headers.get('Host', '')
        if host:
            url = f"https://{host}{path}"

    start = raw.find('{')
    if start == -1:
        raise ValueError("No JSON object found in pasted text")

    json_text = raw[start:].rstrip()
    while json_text and json_text[-1] not in '}]':
        json_text = json_text[:-1]

    depth, in_str, esc, end = 0, False, False, 0
    for i, ch in enumerate(json_text):
        if esc:
            esc = False
            continue
        if ch == '\\':
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    fragment = json_text[:end] if end else json_text

    for candidate in [fragment, re.sub(r',\s*([}\]])', r'\1', fragment)]:
        try:
            return url, headers, json.loads(candidate)
        except json.JSONDecodeError:
            continue

    raise ValueError("Could not parse JSON body")


class RequestSenderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Request Sender — Quad Section Trigger")
        self.root.minsize(1100, 720)
        self.root.geometry("1100x720")

        self._stats_lock   = Lock()
        self.request_count = 0
        self.success_count = 0
        self.error_count   = 0
        self.start_time    = None

        self.is_running  = False
        self._pending_id = None
        self._loop       = None

        self._stat_labels = {}
        self.sections     = []

        self._setup_theme()
        self._build_ui()

        self.log_queue = queue.Queue()
        self._process_log_queue()
        self._start_async_loop()

        self.add_log("=" * 70, "info")
        self.add_log("QUAD-SECTION REQUEST TRIGGER  —  READY", "success")
        self.add_log("Paste raw HTTP request into each section → Load → START.", "info")
        self.add_log("Loop fires §1 & §4 together, waits delay, then §2 & §3.", "info")
        self.add_log("=" * 70, "info")

    # ── theme ──────────────────────────────────────────────────────────────────

    def _setup_theme(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except Exception:
            pass
        s.configure(".", background=_BG, foreground=_FG, fieldbackground=_PANEL,
                    bordercolor=_BORDER, troughcolor=_PANEL,
                    selectbackground=_BLUE, selectforeground=_BG, font=("Arial", 9))
        s.configure("TFrame",            background=_BG)
        s.configure("TLabelframe",       background=_BG, bordercolor=_BORDER, relief="flat")
        s.configure("TLabelframe.Label", background=_BG, foreground=_BLUE, font=("Arial", 9, "bold"))
        s.configure("TEntry",            fieldbackground=_PANEL, foreground=_FG,
                    insertcolor=_FG, bordercolor=_BORDER, padding=4)
        s.configure("TScrollbar",        background=_PANEL, troughcolor=_BG,
                    bordercolor=_BORDER, arrowcolor=_MUTED)
        self.root.configure(bg=_BG)

    # ── layout ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_topbar()
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        left = ttk.Frame(paned)
        paned.add(left, weight=3)
        right = ttk.Frame(paned)
        paned.add(right, weight=2)
        self._build_sections_grid(left)
        self._build_right_panel(right)
        self._build_statusbar()

    # ── top bar ────────────────────────────────────────────────────────────────

    def _build_topbar(self):
        bar = tk.Frame(self.root, bg=_PANEL, height=50)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)

        def _sep():
            tk.Frame(bar, bg=_BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=8)

        tk.Label(bar, text="QUAD-SECTION TRIGGER",
                 bg=_PANEL, fg=_BLUE, font=("Arial", 11, "bold")).pack(side=tk.LEFT, padx=(14, 0))
        _sep()

        tk.Label(bar, text="Price:", bg=_PANEL, fg=_MUTED, font=("Arial", 9)).pack(side=tk.LEFT, padx=(0, 4))
        self.global_price_var = tk.StringVar()
        ttk.Entry(bar, textvariable=self.global_price_var, width=8).pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(bar, text="Size:", bg=_PANEL, fg=_MUTED, font=("Arial", 9)).pack(side=tk.LEFT, padx=(0, 4))
        self.global_size_var = tk.StringVar()
        ttk.Entry(bar, textvariable=self.global_size_var, width=8).pack(side=tk.LEFT, padx=(0, 6))

        self._flat_btn(bar, "Apply All", self.apply_global_values, fg=_PURPLE).pack(
            side=tk.LEFT, pady=10)
        _sep()

        tk.Label(bar, text="Delay (ms):", bg=_PANEL, fg=_MUTED,
                 font=("Arial", 9)).pack(side=tk.LEFT, padx=(0, 4))
        self.delay_var = tk.StringVar(value="500")
        delay_entry = ttk.Entry(bar, textvariable=self.delay_var, width=7)
        delay_entry.pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(bar, text="Sets/min:", bg=_PANEL, fg=_MUTED,
                 font=("Arial", 9)).pack(side=tk.LEFT, padx=(0, 4))
        self.cycles_var = tk.StringVar(value="60")  # 30000/500 = 60
        cycles_entry = ttk.Entry(bar, textvariable=self.cycles_var, width=6)
        cycles_entry.pack(side=tk.LEFT)

        def _delay_to_cycles(*_):
            try:
                d = int(self.delay_var.get())
                if d > 0:
                    self.cycles_var.set(str(round(30000 / d, 2)).rstrip('0').rstrip('.'))
            except ValueError:
                pass

        def _cycles_to_delay(*_):
            try:
                spm = float(self.cycles_var.get())
                if spm > 0:
                    self.delay_var.set(str(round(30000 / spm)))
            except ValueError:
                pass

        delay_entry.bind("<FocusOut>", _delay_to_cycles)
        delay_entry.bind("<Return>",   _delay_to_cycles)
        cycles_entry.bind("<FocusOut>", _cycles_to_delay)
        cycles_entry.bind("<Return>",   _cycles_to_delay)
        _sep()

        self.start_btn = tk.Button(
            bar, text="▶  START", width=10,
            bg="#1a6b3a", fg="white", activebackground="#145230", activeforeground="white",
            font=("Arial", 10, "bold"), relief=tk.FLAT, bd=0, cursor="hand2",
            command=self.start_loop,
        )
        self.start_btn.pack(side=tk.LEFT, padx=(0, 6), pady=10)

        self.stop_btn = tk.Button(
            bar, text="⏹  STOP", width=10,
            bg="#6b1a1a", fg="white", activebackground="#521414", activeforeground="white",
            font=("Arial", 10, "bold"), relief=tk.FLAT, bd=0, cursor="hand2",
            state=tk.DISABLED, command=self.stop_loop,
        )
        self.stop_btn.pack(side=tk.LEFT, pady=10)

        _sep()
        tk.Button(
            bar, text="✕ Cancel Unmatched",
            bg="#7a4000", fg="white", activebackground="#5a2e00", activeforeground="white",
            font=("Arial", 9, "bold"), relief=tk.FLAT, bd=0, cursor="hand2",
            command=self._cancel_unmatched,
        ).pack(side=tk.LEFT, padx=(0, 10), pady=10)

        _sep()
        self.global_status_lbl = tk.Label(bar, text="Ready", bg=_PANEL, fg=_MUTED,
                                          font=("Arial", 9))
        self.global_status_lbl.pack(side=tk.LEFT, padx=6)

    # ── 2×2 section grid ───────────────────────────────────────────────────────

    def _build_sections_grid(self, parent):
        grid = tk.Frame(parent, bg=_BG)
        grid.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        for r in range(2):
            grid.rowconfigure(r, weight=1)
        for c in range(2):
            grid.columnconfigure(c, weight=1)

        for i, (row, col) in enumerate([(0, 0), (0, 1), (1, 0), (1, 1)]):
            frame = self._build_one_section(grid, i + 1, SECTION_COLORS[i])
            frame.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)
            self.sections.append(frame)

    def _build_one_section(self, parent, num: int, color: str) -> tk.Frame:
        default_side = "BACK" if num in (1, 3) else "LAY"

        outer = tk.Frame(parent, bg=color)
        card  = tk.Frame(outer, bg=_CARD, padx=8, pady=8)
        card.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # header
        hdr = tk.Frame(card, bg=_CARD)
        hdr.pack(fill=tk.X, pady=(0, 5))
        tk.Label(hdr, text=f"  SECTION {num}  ", bg=color, fg=_BG,
                 font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        status_lbl = tk.Label(hdr, text="Ready", bg=_CARD, fg=_MUTED,
                              font=("Arial", 8, "bold"))
        status_lbl.pack(side=tk.RIGHT)

        # raw request textarea
        raw_text = scrolledtext.ScrolledText(
            card, font=("Consolas", 7), wrap=tk.NONE, height=5,
            bg=_PANEL, fg=_FG, insertbackground=_FG,
            selectbackground=_BLUE, selectforeground=_BG,
            relief=tk.FLAT, bd=0,
        )
        raw_text.pack(fill=tk.X, pady=(0, 4))

        # paste / load row (populated after sd is defined)
        btn_row = tk.Frame(card, bg=_CARD)
        btn_row.pack(anchor=tk.W, pady=(0, 6))

        # price / size / side row
        pss = tk.Frame(card, bg=_CARD)
        pss.pack(fill=tk.X, pady=(0, 4))

        tk.Label(pss, text="Price:", bg=_CARD, fg=_FG,
                 font=("Arial", 9)).pack(side=tk.LEFT, padx=(0, 3))
        price_var = tk.StringVar()
        ttk.Entry(pss, textvariable=price_var, width=7).pack(side=tk.LEFT, padx=(0, 8))

        tk.Label(pss, text="Size:", bg=_CARD, fg=_FG,
                 font=("Arial", 9)).pack(side=tk.LEFT, padx=(0, 3))
        size_var = tk.StringVar()
        ttk.Entry(pss, textvariable=size_var, width=7).pack(side=tk.LEFT, padx=(0, 8))

        # Side is fixed per section: 1&3 = BACK (blue), 2&4 = LAY (red)
        side_var = tk.StringVar(value=default_side)
        tk.Label(
            pss, text="",
            bg="#1565C0" if default_side == "BACK" else "#B71C1C",
            width=5, height=1,
        ).pack(side=tk.LEFT, padx=(0, 4))

        # uuid row
        uuid_row = tk.Frame(card, bg=_CARD)
        uuid_row.pack(fill=tk.X, pady=(0, 4))
        tk.Label(uuid_row, text="UUID:", bg=_CARD, fg=_MUTED,
                 font=("Arial", 8)).pack(side=tk.LEFT, padx=(0, 4))
        uuid_var = tk.StringVar()
        uuid_entry = ttk.Entry(uuid_row, textvariable=uuid_var, font=("Consolas", 7),
                               state="readonly")
        uuid_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # send button
        send_btn = tk.Button(
            card, text=f"Send §{num}",
            bg=color, fg=_BG, activebackground=_BORDER, activeforeground=_FG,
            font=("Arial", 9, "bold"), relief=tk.FLAT, bd=0, cursor="hand2",
        )
        send_btn.pack(fill=tk.X, pady=(4, 0))

        sd = {
            'num':          num,
            'raw_text':     raw_text,
            'price_var':    price_var,
            'size_var':     size_var,
            'side_var':     side_var,
            'uuid_var':     uuid_var,
            'status_label': status_lbl,
            'url':          None,
            'headers':      None,
            'json_data':    None,
            'market_key':   None,
        }
        outer.section_data = sd

        def _paste(d=sd):
            try:
                d['raw_text'].delete("1.0", tk.END)
                d['raw_text'].insert("1.0", self.root.clipboard_get())
                self.root.after(50, lambda: self._load_section(d))
            except Exception:
                pass

        send_btn.config(command=lambda d=sd: self._send_section_now(d))

        # Auto-load on Ctrl+V paste into the text area
        raw_text.bind("<<Paste>>", lambda _, d=sd: self.root.after(50, lambda: self._load_section(d)))

        tk.Button(
            btn_row, text="  Paste", command=_paste,
            bg=_PANEL, fg=_FG, activebackground=_BORDER, activeforeground=_FG,
            font=("Arial", 8), relief=tk.FLAT, bd=0, cursor="hand2", padx=8, pady=3,
        ).pack(side=tk.LEFT, padx=(0, 4))

        tk.Button(
            btn_row, text="⬇ Load", command=lambda d=sd: self._load_section(d),
            bg=_CARD, fg=_CYAN, activebackground=_BORDER, activeforeground=_CYAN,
            font=("Arial", 8), relief=tk.FLAT, bd=0, cursor="hand2", padx=8, pady=3,
        ).pack(side=tk.LEFT)

        return outer

    # ── right panel ────────────────────────────────────────────────────────────

    def _build_right_panel(self, parent):
        sf = ttk.LabelFrame(parent, text="  Statistics", padding=6)
        sf.pack(fill=tk.X, padx=6, pady=(6, 0))
        self._build_stats(sf)

        lf = ttk.LabelFrame(parent, text="  Logs", padding=6)
        lf.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.log_text = scrolledtext.ScrolledText(
            lf, font=("Consolas", 9),
            bg=_PANEL, fg=_FG, insertbackground=_FG,
            selectbackground=_BLUE, selectforeground=_BG,
            relief=tk.FLAT, bd=0,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        for tag, clr in [("info", _BLUE), ("success", _GREEN), ("error", _RED),
                         ("warning", _YELLOW), ("trigger", _PURPLE)]:
            self.log_text.tag_config(tag, foreground=clr)
        clear_row = tk.Frame(lf, bg=_BG)
        clear_row.pack(fill=tk.X, pady=(6, 0))
        self._flat_btn(clear_row, "Clear",
                       lambda: self.log_text.delete("1.0", tk.END), fg=_RED).pack(side=tk.RIGHT)

    def _build_stats(self, parent):
        grid = tk.Frame(parent, bg=_BG)
        grid.pack(fill=tk.X)
        for c in range(4):
            grid.columnconfigure(c, weight=1)
        for col, (key, label, color) in enumerate([
            ("total",   "TOTAL",   _FG),
            ("success", "SUCCESS", _GREEN),
            ("errors",  "ERRORS",  _RED),
            ("rate",    "REQ/SEC", _CYAN),
        ]):
            f = tk.Frame(grid, bg=_CARD, padx=8, pady=6)
            f.grid(row=0, column=col, padx=3, pady=3, sticky="nsew")
            val_lbl = tk.Label(f, text="0", bg=_CARD, fg=color, font=("Arial", 14, "bold"))
            val_lbl.pack()
            tk.Label(f, text=label, bg=_CARD, fg=_MUTED, font=("Arial", 7)).pack()

            class _P:
                def __init__(self, lbl): self._lbl = lbl
                def config(self, text=""): self._lbl.config(text=str(text))

            self._stat_labels[key] = _P(val_lbl)

    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=_PANEL, height=26)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        bar.pack_propagate(False)
        self.status_lbl = tk.Label(bar, text="Ready", bg=_PANEL, fg=_MUTED,
                                   font=("Arial", 8), anchor=tk.W)
        self.status_lbl.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
        self.rate_lbl = tk.Label(bar, text="Total: 0  |  OK: 0  |  Errors: 0",
                                 bg=_PANEL, fg=_MUTED, font=("Consolas", 8))
        self.rate_lbl.pack(side=tk.RIGHT, padx=10)

    # ── helpers ────────────────────────────────────────────────────────────────

    def _flat_btn(self, parent, text, cmd, fg=_FG):
        return tk.Button(parent, text=text, command=cmd,
                         bg=_CARD, fg=fg, activebackground=_BORDER, activeforeground=fg,
                         font=("Arial", 9), relief=tk.FLAT, bd=0, cursor="hand2",
                         padx=10, pady=4)

    def _start_async_loop(self):
        def _run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()
        Thread(target=_run, daemon=True, name="asyncio-loop").start()
        while self._loop is None or not self._loop.is_running():
            time.sleep(0.005)

    # ── load section ───────────────────────────────────────────────────────────

    def _load_section(self, sd: dict):
        num = sd['num']
        raw = sd['raw_text'].get("1.0", tk.END).strip()
        if not raw:
            messagebox.showwarning("Warning", f"Section {num}: Paste a request first!")
            return
        try:
            url, headers, json_data = extract_json_body(raw)
        except ValueError as exc:
            sd['status_label'].config(text="Parse Error", fg=_RED)
            self.add_log(f"§{num}: {exc}", "error")
            messagebox.showerror("Parse Error", str(exc))
            return

        if not isinstance(json_data, dict) or not json_data:
            messagebox.showerror("Error", f"Section {num}: JSON must be a non-empty object.")
            return

        market_key = next(iter(json_data))
        bet_list   = json_data.get(market_key, [])
        if not isinstance(bet_list, list) or not bet_list:
            messagebox.showerror("Error", f"Section {num}: No bet list under key '{market_key}'.")
            return

        bet = bet_list[0]
        sd['url']        = url or "https://ex.pb77.co/customer/api/placeBets"
        sd['headers']    = headers or {}
        sd['json_data']  = json_data
        sd['market_key'] = market_key

        sd['price_var'].set(str(bet.get('price', '')))
        sd['size_var'].set(str(bet.get('size', '')))
        sd['uuid_var'].set(str(bet.get('betUuid', '')))

        loaded_side = bet.get('side', '')
        # Side is fixed per section (1&3=BACK, 2&4=LAY); ignore side from loaded data.

        sd['status_label'].config(text="Loaded", fg=_GREEN)
        self.add_log(
            f"§{num} loaded — market: {market_key}, "
            f"price: {bet.get('price')}, size: {bet.get('size')}, "
            f"side: {loaded_side or '?'}",
            "success",
        )

    # ── build payload ──────────────────────────────────────────────────────────

    def _build_payload(self, sd: dict):
        """Validate fields and build request dict. Returns None on any error."""
        num = sd['num']
        if not sd['json_data']:
            self.add_log(f"§{num}: Load a request first!", "error")
            return None

        price_s = sd['price_var'].get().strip()
        size_s  = sd['size_var'].get().strip()
        side    = sd['side_var'].get()

        try:
            price = float(price_s)
            size  = float(size_s)
            assert price > 0 and size > 0 and side in ('BACK', 'LAY')
        except Exception:
            self.add_log(f"§{num}: Invalid price/size/side ({price_s}/{size_s}/{side})", "error")
            return None

        body = copy.deepcopy(sd['json_data'])
        mk   = sd['market_key'] or next(iter(body))
        bet  = body[mk][0]

        bet['price'] = price
        bet['size']  = size
        bet['side']  = side

        ts             = int(datetime.now().timestamp() + 2)
        sel_id         = bet.get('selectionId', '')
        bet['betUuid'] = f"{mk}_{sel_id}_0__{ts}_INLINE"
        sd['uuid_var'].set(bet['betUuid'])

        hdrs = dict(sd['headers'])
        if 'X-Csrf-Token' in hdrs:
            cookie = hdrs.get('Cookie', '')
            if 'CSRF-TOKEN=' in cookie:
                token = cookie.split('CSRF-TOKEN=')[-1].split(';')[0]
                if token:
                    hdrs['X-Csrf-Token'] = token

        sd['status_label'].config(text="Sending…", fg=_BLUE)
        self.add_log(f"§{num}: {side}  price={price}  size={size}  uuid=…{ts}", "trigger")
        return {
            'num':    num,
            'url':    sd['url'],
            'headers': hdrs,
            'body':   body,
            'status': sd['status_label'],
        }

    # ── async HTTP send ────────────────────────────────────────────────────────

    async def _do_send(self, payload: dict):
        num  = payload['num']
        hdrs = {**payload['headers'], 'Content-Type': 'application/json'}
        try:
            conn = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=conn) as session:
                async with session.post(
                    payload['url'], json=payload['body'], headers=hdrs,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    code = resp.status
                    with self._stats_lock:
                        self.request_count += 1
                        if code == 200:
                            self.success_count += 1
                        else:
                            self.error_count += 1

                    if code == 200:
                        try:
                            rj = await resp.json(content_type=None)
                            failed, err_msg, offer = False, "", ""
                            for _, md in rj.items():
                                if not isinstance(md, dict):
                                    continue
                                if md.get('status') == 'FAIL':
                                    failed  = True
                                    ec      = md.get('error', '?')
                                    ex      = md.get('exception', {})
                                    err_msg = f"{ec} ({ex.get('id','')}) {ex.get('message','')[:60]}"
                                elif md.get('status') == 'SUCCESS':
                                    oids = md.get('offerIds', {})
                                    if oids:
                                        offer = f" IDs:{oids}"
                            if failed:
                                self.root.after(0, lambda p=payload, msg=err_msg:
                                    (p['status'].config(text="FAILED", fg=_RED),
                                     self.add_log(f"§{p['num']}: ✗ {msg}", "error")))
                            else:
                                self.root.after(0, lambda p=payload, o=offer:
                                    (p['status'].config(text="✓ OK", fg=_GREEN),
                                     self.add_log(f"§{p['num']}: ✓ SUCCESS{o}", "success")))
                        except Exception:
                            self.root.after(0, lambda p=payload:
                                (p['status'].config(text="✓ 200", fg=_GREEN),
                                 self.add_log(f"§{p['num']}: ✓ HTTP 200", "success")))
                    else:
                        self.root.after(0, lambda p=payload, c=code:
                            (p['status'].config(text=f"HTTP {c}", fg=_RED),
                             self.add_log(f"§{p['num']}: ✗ HTTP {c}", "error")))
        except Exception as ex:
            with self._stats_lock:
                self.error_count += 1
            self.root.after(0, lambda p=payload, e=str(ex):
                (p['status'].config(text="Error", fg=_RED),
                 self.add_log(f"§{p['num']}: ✗ {e}", "error")))

        self.root.after(0, self._refresh_stats)

    def _fire(self, indices: list):
        for i in indices:
            if i < len(self.sections):
                payload = self._build_payload(self.sections[i].section_data)
                if payload:
                    asyncio.run_coroutine_threadsafe(self._do_send(payload), self._loop)

    def _send_section_now(self, sd: dict):
        payload = self._build_payload(sd)
        if payload:
            asyncio.run_coroutine_threadsafe(self._do_send(payload), self._loop)

    # ── loop control ───────────────────────────────────────────────────────────

    def start_loop(self):
        if self.is_running:
            messagebox.showwarning("Warning", "Loop already running!")
            return
        try:
            delay = int(self.delay_var.get())
            assert delay >= 0
        except (ValueError, AssertionError):
            messagebox.showerror("Error", "Delay must be ≥ 0 ms.")
            return

        with self._stats_lock:
            self.request_count = self.success_count = self.error_count = 0
        self.start_time = time.time()
        self.is_running = True

        self.start_btn.config(state=tk.DISABLED, bg="#555555")
        self.stop_btn.config(state=tk.NORMAL, bg="#6b1a1a")
        self.global_status_lbl.config(text="Running…", fg=_GREEN)
        rate = round(30000 / delay, 2) if delay > 0 else "∞"
        self.add_log(f"LOOP STARTED — delay {delay} ms between pairs  ({rate} sets/min)", "success")
        self._cycle_part1()

    def _cycle_part1(self):
        if not self.is_running:
            return
        self.add_log("→ §1 & §4", "trigger")
        self._fire([0, 3])
        self._pending_id = self.root.after(self._get_delay(), self._cycle_part2)

    def _cycle_part2(self):
        if not self.is_running:
            return
        self.add_log("→ §2 & §3", "trigger")
        self._fire([1, 2])
        self._pending_id = self.root.after(self._get_delay(), self._cycle_part1)

    def _get_delay(self) -> int:
        try:
            return max(0, int(self.delay_var.get()))
        except ValueError:
            return 500

    def stop_loop(self):
        self.is_running = False
        if self._pending_id:
            self.root.after_cancel(self._pending_id)
            self._pending_id = None
        self.start_btn.config(state=tk.NORMAL, bg="#1a6b3a")
        self.stop_btn.config(state=tk.DISABLED, bg="#555555")
        self.global_status_lbl.config(text="Stopped", fg=_YELLOW)
        self.add_log("LOOP STOPPED", "warning")
        self._refresh_stats()

    # ── cancel unmatched ───────────────────────────────────────────────────────

    def _cancel_unmatched(self):
        """POST /customer/api/cancelBets/all for Section 1 and Section 4 in parallel."""
        from urllib.parse import urlparse

        targets = []
        for idx, label in [(0, "§1"), (3, "§4")]:
            sd = self.sections[idx].section_data
            if not sd['headers'] or not sd['url']:
                self.add_log(f"Cancel skipped {label}: section not loaded", "warning")
                continue
            hdrs = dict(sd['headers'])
            if 'X-Csrf-Token' in hdrs:
                cookie = hdrs.get('Cookie', '')
                if 'CSRF-TOKEN=' in cookie:
                    token = cookie.split('CSRF-TOKEN=')[-1].split(';')[0]
                    if token:
                        hdrs['X-Csrf-Token'] = token
            hdrs['Content-Type'] = 'application/json'
            host = urlparse(sd['url']).netloc
            targets.append((label, f"https://{host}/customer/api/cancelBets/all", hdrs))

        if not targets:
            messagebox.showwarning("No Session", "Load Section 1 or Section 4 first.")
            return

        body = {"betTypes": ["EXCHANGE"]}
        for lbl, url, _ in targets:
            self.add_log(f"Cancel {lbl} → {url}", "warning")

        async def _do_one(lbl, url, hdrs):
            try:
                conn = aiohttp.TCPConnector(ssl=False)
                async with aiohttp.ClientSession(connector=conn) as session:
                    async with session.post(
                        url, json=body, headers=hdrs,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        code = resp.status
                        if code == 200:
                            try:
                                rj = await resp.json(content_type=None)
                                self.add_log(f"Cancel {lbl}: ✓ {json.dumps(rj)[:120]}", "success")
                            except Exception:
                                self.add_log(f"Cancel {lbl}: ✓ HTTP 200", "success")
                        else:
                            txt = await resp.text()
                            self.add_log(f"Cancel {lbl}: ✗ HTTP {code} — {txt[:120]}", "error")
            except Exception as ex:
                self.add_log(f"Cancel {lbl}: ✗ {ex}", "error")

        async def _do_both():
            await asyncio.gather(*[_do_one(lbl, url, hdrs) for lbl, url, hdrs in targets])

        if self._loop:
            asyncio.run_coroutine_threadsafe(_do_both(), self._loop)

    # ── global controls ────────────────────────────────────────────────────────

    def apply_global_values(self):
        gp = self.global_price_var.get().strip()
        gs = self.global_size_var.get().strip()
        if not gp and not gs:
            messagebox.showwarning("Warning", "Enter Price or Size to apply!")
            return
        for frame in self.sections:
            sd = frame.section_data
            if gp:
                sd['price_var'].set(gp)
            if gs:
                sd['size_var'].set(gs)
        parts = []
        if gp: parts.append(f"Price={gp}")
        if gs:  parts.append(f"Size={gs}")
        self.add_log(f"Applied to all sections: {', '.join(parts)}", "info")

    # ── stats & log ────────────────────────────────────────────────────────────

    def _refresh_stats(self):
        with self._stats_lock:
            t, s, e = self.request_count, self.success_count, self.error_count
        elapsed = (time.time() - self.start_time) if self.start_time else 0
        rate    = t / elapsed if elapsed > 0 else 0
        self._stat_labels["total"].config(text=f"{t:,}")
        self._stat_labels["success"].config(text=f"{s:,}")
        self._stat_labels["errors"].config(text=f"{e:,}")
        self._stat_labels["rate"].config(text=f"{rate:.1f}")
        self.rate_lbl.config(text=f"Total: {t:,}  |  OK: {s:,}  |  Errors: {e:,}")

    def add_log(self, message: str, tag: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_queue.put((f"[{ts}] {message}\n", tag))

    def _process_log_queue(self):
        try:
            while True:
                entry, tag = self.log_queue.get_nowait()
                self.log_text.insert(tk.END, entry, tag)
                self.log_text.see(tk.END)
        except queue.Empty:
            pass
        self.root.after(50, self._process_log_queue)


def main():
    root = tk.Tk()
    RequestSenderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
