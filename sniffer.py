"""
Request Sender + Sniffer — Single File
=======================================
Main window: Request Sender (4-section bet tester)
Header button "Sniffer" → opens Sniffer window (mitmproxy interceptor)

Requires: pip install mitmproxy requests
"""

import copy
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import textwrap
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from tkinter import font as tkfont
from tkinter import messagebox, scrolledtext, ttk

import requests as http_requests

# ══════════════════════════════════════════════════════════════════
#  SNIFFER — config & constants
# ══════════════════════════════════════════════════════════════════
PROXY_HOST     = "127.0.0.1"
PROXY_PORT     = 8081
IPC_PORT       = 9999
TARGET_DOMAINS = ["ex.indi2.club", "ex.pb77.co"]

ADDON_SOURCE = (
    "import json, socket, threading\n"
    "from mitmproxy import http\n\n"
    "TARGET_DOMAINS = %s\n"
    "TARGET_PATH    = '/customer/api/placeBets'\n"
    "IPC_HOST       = %s\n"
    "IPC_PORT       = %d\n\n"
    "def send_to_gui(raw_text):\n"
    "    def _send():\n"
    "        try:\n"
    "            envelope = json.dumps({'raw': raw_text}).encode('utf-8')\n"
    "            with socket.create_connection((IPC_HOST, IPC_PORT), timeout=2) as s:\n"
    "                s.sendall(len(envelope).to_bytes(4, 'big') + envelope)\n"
    "        except Exception:\n"
    "            pass\n"
    "    threading.Thread(target=_send, daemon=True).start()\n\n"
    "def get_host(req):\n"
    "    # HTTP/2 uses :authority pseudo-header, HTTP/1.x uses Host\n"
    "    for name, value in req.headers.items(multi=True):\n"
    "        nl = name.lower()\n"
    "        if nl == 'host' or nl == ':authority':\n"
    "            return value.split(':')[0].strip().lower()\n"
    "    # fallback to pretty_host\n"
    "    return (req.pretty_host or '').lower()\n\n"
    "class PlaceBetsAddon:\n"
    "    def request(self, flow):\n"
    "        req        = flow.request\n"
    "        host_clean = get_host(req)\n"
    "        path       = req.path.split('?')[0]\n"
    "        method     = req.method.upper()\n\n"
    "        if method != 'POST' or TARGET_PATH not in path:\n"
    "            return\n\n"
    "        matched = any(\n"
    "            host_clean == d or host_clean.endswith('.' + d)\n"
    "            for d in TARGET_DOMAINS\n"
    "        )\n"
    "        if not matched:\n"
    "            return\n\n"
    "        lines = [req.method + ' ' + req.path + ' HTTP/' + req.http_version]\n"
    "        host_seen = False\n"
    "        for name, value in req.headers.items(multi=True):\n"
    "            if name.startswith(':'):\n"
    "                continue  # skip HTTP/2 pseudo-headers like :authority :method etc\n"
    "            lines.append(name + ': ' + value)\n"
    "            if name.lower() == 'host':\n"
    "                host_seen = True\n"
    "        if not host_seen:\n"
    "            lines.insert(1, 'Host: ' + host_clean)\n"
    "        lines.append('')\n"
    "        try:\n"
    "            body = req.get_text()\n"
    "        except Exception:\n"
    "            body = req.content.decode('utf-8', errors='replace')\n"
    "        lines.append(body)\n"
    "        send_to_gui('\\n'.join(lines))\n\n"
    "addons = [PlaceBetsAddon()]\n"
) % (repr(TARGET_DOMAINS), repr(PROXY_HOST), IPC_PORT)
# Sniffer palette
S_BG      = "#0a0d0f"
S_BG2     = "#0f1419"
S_PANEL   = "#111820"
S_BORDER  = "#1e2d3d"
S_ACCENT  = "#00d4ff"
S_ACCENT2 = "#00ff9d"
S_WARN    = "#ff6b35"
S_DIM     = "#3a4a5a"
S_TEXT    = "#c8d8e8"
S_TEXT2   = "#7a9ab5"
S_CARD    = "#0d1823"
S_CARD_HL = "#152030"


# ══════════════════════════════════════════════════════════════════
#  SNIFFER WINDOW  (Toplevel — reusable, singleton)
# ══════════════════════════════════════════════════════════════════
class SnifferWindow(tk.Toplevel):
    """Opens as a child Toplevel of the sender app."""

    def __init__(self, master):
        super().__init__(master)
        self.title("Sniffer")
        self.configure(bg=S_BG)
        self.geometry("650x700")
        self.minsize(600, 300)

        self._proxy_proc   = None
        self._addon_path   = None
        self._running      = False
        self._requests     = []
        self._list_rows    = []
        self._selected_idx = None
        self._ipc_running  = True

        self._setup_fonts()
        self._build_ui()
        self._start_ipc_server()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Fonts ──────────────────────────────────────────────────
    def _setup_fonts(self):
        self.f_mono   = tkfont.Font(family="Courier New", size=10)
        self.f_mono_s = tkfont.Font(family="Courier New", size=9)
        self.f_mono_b = tkfont.Font(family="Courier New", size=10, weight="bold")
        self.f_ui     = tkfont.Font(family="Courier New", size=10)
        self.f_title  = tkfont.Font(family="Courier New", size=15, weight="bold")
        self.f_label  = tkfont.Font(family="Courier New", size=9)

    # ── UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=S_BG, height=54)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(hdr, text="◈ SNIFFER",
                 font=self.f_title, fg=S_ACCENT, bg=S_BG).pack(side="left", padx=20, pady=10)

        self._status_var = tk.StringVar(value="● IDLE")
        self._status_lbl = tk.Label(hdr, textvariable=self._status_var,
                                    font=self.f_label, fg=S_DIM, bg=S_BG)
        self._status_lbl.pack(side="left", padx=6)

        self._count_var = tk.StringVar(value="0 captured")
        tk.Label(hdr, textvariable=self._count_var,
                 font=self.f_label, fg=S_ACCENT2, bg=S_BG).pack(side="right", padx=20)

        tk.Frame(self, bg=S_BORDER, height=1).pack(fill="x")

        # Control bar
        ctrl = tk.Frame(self, bg=S_BG2, pady=7)
        ctrl.pack(fill="x")

        B = dict(font=self.f_ui, relief="flat", cursor="hand2", padx=12, pady=5, bd=0)

        self._btn_start = tk.Button(ctrl, text="▶  START", command=self._start_proxy,
                                    bg=S_ACCENT2, fg="#000", activebackground="#00cc7a", **B)
        self._btn_start.pack(side="left", padx=(14, 5))

        self._btn_stop = tk.Button(ctrl, text="■  STOP", command=self._stop_proxy,
                                   bg=S_WARN, fg="#fff", activebackground="#cc5522",
                                   state="disabled", **B)
        self._btn_stop.pack(side="left", padx=5)

        self._btn_delete = tk.Button(ctrl, text="🗑  DELETE", command=self._delete_selected,
                                     bg=S_PANEL, fg=S_WARN, activebackground=S_CARD_HL, **B)
        self._btn_delete.pack(side="left", padx=5)

        tk.Frame(ctrl, bg=S_DIM, width=1, height=26).pack(side="left", padx=12)

        self._btn_copy = tk.Button(ctrl, text="⎘  COPY SELECTED", command=self._copy_selected,
                                   bg=S_PANEL, fg=S_ACCENT, activebackground=S_CARD_HL, **B)
        self._btn_copy.pack(side="left", padx=5)

        self._btn_copy_all = tk.Button(ctrl, text="⎘  COPY ALL", command=self._copy_all,
                                       bg=S_PANEL, fg=S_TEXT2, activebackground=S_CARD_HL, **B)
        self._btn_copy_all.pack(side="left", padx=5)

        tk.Frame(ctrl, bg=S_DIM, width=1, height=26).pack(side="left", padx=12)

        self._btn_clear = tk.Button(ctrl, text="✕  CLEAR ALL", command=self._clear_all,
                                    bg=S_PANEL, fg=S_DIM, activebackground=S_CARD_HL, **B)
        self._btn_clear.pack(side="left", padx=5)

        tk.Label(ctrl, text=f"proxy  {PROXY_HOST}:{PROXY_PORT}",
                 font=self.f_label, fg=S_DIM, bg=S_BG2).pack(side="right", padx=16)

        tk.Frame(self, bg=S_BORDER, height=1).pack(fill="x")

        # Main pane
        main = tk.Frame(self, bg=S_BG)
        main.pack(fill="both", expand=True)

        # Left — list
        left = tk.Frame(main, bg=S_BG, width=324)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        tk.Label(left, text="CAPTURED REQUESTS", font=self.f_label,
                 fg=S_DIM, bg=S_BG, anchor="w").pack(fill="x", padx=14, pady=(10, 3))

        lw = tk.Frame(left, bg=S_BORDER)
        lw.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._list_canvas = tk.Canvas(lw, bg=S_CARD, bd=0, highlightthickness=0)
        lsb = tk.Scrollbar(lw, orient="vertical", command=self._list_canvas.yview)
        self._list_canvas.configure(yscrollcommand=lsb.set)
        lsb.pack(side="right", fill="y")
        self._list_canvas.pack(side="left", fill="both", expand=True)

        self._list_inner = tk.Frame(self._list_canvas, bg=S_CARD)
        self._list_canvas.create_window((0, 0), window=self._list_inner, anchor="nw")
        self._list_inner.bind("<Configure>", lambda e: self._list_canvas.configure(
            scrollregion=self._list_canvas.bbox("all")))

        # Divider
        tk.Frame(main, bg=S_BORDER, width=1).pack(side="left", fill="y")

        # Right — raw viewer
        right = tk.Frame(main, bg=S_BG)
        right.pack(side="left", fill="both", expand=True)

        rh = tk.Frame(right, bg=S_BG2, height=30)
        rh.pack(fill="x")
        rh.pack_propagate(False)
        tk.Label(rh, text="RAW REQUEST", font=self.f_label,
                 fg=S_DIM, bg=S_BG2).pack(side="left", padx=14, pady=6)
        self._raw_host_lbl = tk.Label(rh, text="", font=self.f_label, fg=S_ACCENT, bg=S_BG2)
        self._raw_host_lbl.pack(side="left")

        rw = tk.Frame(right, bg=S_BORDER)
        rw.pack(fill="both", expand=True, padx=14, pady=10)

        self._raw_text = tk.Text(
            rw, bg=S_CARD, fg=S_TEXT, font=self.f_mono,
            wrap="none", bd=0, padx=12, pady=10,
            state="disabled",
            selectbackground=S_BORDER, selectforeground=S_ACCENT,
            insertbackground=S_ACCENT, relief="flat",
            spacing1=1, spacing3=1,
        )
        rsby = tk.Scrollbar(rw, orient="vertical",   command=self._raw_text.yview)
        rsbx = tk.Scrollbar(rw, orient="horizontal", command=self._raw_text.xview)
        self._raw_text.configure(yscrollcommand=rsby.set, xscrollcommand=rsbx.set)
        rsby.pack(side="right",  fill="y")
        rsbx.pack(side="bottom", fill="x")
        self._raw_text.pack(fill="both", expand=True)

        # Status bar
        tk.Frame(self, bg=S_BORDER, height=1).pack(fill="x")
        self._log_var = tk.StringVar(
            value=f"Ready — set browser proxy to {PROXY_HOST}:{PROXY_PORT}")
        tk.Label(self, textvariable=self._log_var, font=self.f_label,
                 fg=S_TEXT2, bg=S_BG2, anchor="w", pady=5).pack(fill="x", padx=14)

    # ── IPC server ─────────────────────────────────────────────
    def _start_ipc_server(self):
        threading.Thread(target=self._ipc_loop, daemon=True).start()

    def _ipc_loop(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                srv.bind((PROXY_HOST, IPC_PORT))
            except OSError as e:
                self.after(0, lambda: self._log(f"IPC bind error: {e}"))
                return
            srv.listen(10)
            srv.settimeout(1)
            while self._ipc_running:
                try:
                    conn, _ = srv.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=self._handle_conn,
                                 args=(conn,), daemon=True).start()

    def _handle_conn(self, conn):
        with conn:
            hdr = b""
            while len(hdr) < 4:
                chunk = conn.recv(4 - len(hdr))
                if not chunk:
                    return
                hdr += chunk
            length = int.from_bytes(hdr, "big")
            buf = b""
            while len(buf) < length:
                chunk = conn.recv(min(4096, length - len(buf)))
                if not chunk:
                    return
                buf += chunk
            try:
                raw = json.loads(buf.decode("utf-8")).get("raw", "")
                self.after(0, lambda r=raw: self._on_request(r))
            except Exception:
                pass

    # ── Request received ───────────────────────────────────────
    @staticmethod
    def _extract_host(raw: str) -> str:
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                break
            low = stripped.lower()
            if low.startswith("host:"):
                return stripped.split(":", 1)[1].strip().split(":")[0]
        # fallback: Origin or Referer
        for line in raw.splitlines():
            stripped = line.strip()
            low = stripped.lower()
            if low.startswith("origin:") or low.startswith("referer:"):
                val = stripped.split(":", 1)[1].strip()
                val = val.replace("https://", "").replace("http://", "").split("/")[0]
                return val
        return "unknown"

    def _on_request(self, raw: str):
        self._requests.append(raw)
        idx = len(self._requests) - 1
        host = self._extract_host(raw)
        self._add_list_item(idx, host)
        self._count_var.set(f"{len(self._requests)} captured")
        self._log(f"Request #{idx + 1} from {host}")
        self._select(idx)

    def _add_list_item(self, idx: int, host: str):
        row = tk.Frame(self._list_inner, bg=S_CARD, cursor="hand2", pady=7, padx=10)
        row.pack(fill="x", padx=1, pady=1)

        tk.Label(row, text=f"#{idx + 1:03d}", font=self.f_label,
                 fg=S_DIM, bg=S_CARD, width=5, anchor="w").pack(side="left")
        tk.Label(row, text="POST", font=self.f_mono_s,
                 fg=S_ACCENT2, bg=S_CARD, width=5, anchor="w").pack(side="left")
        tk.Label(row, text=host, font=self.f_mono_s,
                 fg=S_TEXT, bg=S_CARD).pack(side="left", padx=4)
        tk.Label(row, text=datetime.now().strftime("%H:%M:%S"),
                 font=self.f_label, fg=S_DIM, bg=S_CARD).pack(side="right")

        def _click(e, i=idx):  self._select(i)
        def _rclick(e, i=idx): self._select(i); self._delete_selected()
        for w in [row] + row.winfo_children():
            w.bind("<Button-1>", _click)
            w.bind("<Button-3>", _rclick)

        row._idx = idx
        self._list_rows.append(row)
        self._list_canvas.update_idletasks()
        self._list_canvas.yview_moveto(1.0)

    def _select(self, idx: int):
        self._selected_idx = idx
        for row in self._list_rows:
            bg = S_CARD_HL if row._idx == idx else S_CARD
            row.configure(bg=bg)
            for w in row.winfo_children():
                w.configure(bg=bg)
        raw = self._requests[idx]
        self._raw_host_lbl.configure(text=self._extract_host(raw))
        self._set_raw(raw)

    def _set_raw(self, text: str):
        self._raw_text.configure(state="normal")
        self._raw_text.delete("1.0", "end")
        self._raw_text.insert("1.0", text)
        self._apply_highlight()
        self._raw_text.configure(state="disabled")

    def _apply_highlight(self):
        w = self._raw_text
        w.tag_config("req_line",  foreground=S_ACCENT,  font=self.f_mono_b)
        w.tag_config("hdr_name",  foreground=S_TEXT2)
        w.tag_config("hdr_colon", foreground=S_DIM)
        w.tag_config("hdr_val",   foreground=S_TEXT)
        w.tag_config("blank",     foreground=S_DIM)
        w.tag_config("body",      foreground=S_ACCENT2)
        lines = w.get("1.0", "end").splitlines()
        past_blank = False
        for i, line in enumerate(lines):
            ln = i + 1
            s, e = f"{ln}.0", f"{ln}.end"
            if i == 0:
                w.tag_add("req_line", s, e)
            elif not past_blank and line == "":
                past_blank = True
                w.tag_add("blank", s, e)
            elif past_blank:
                w.tag_add("body", s, e)
            else:
                m = re.match(r"^([^:]+)(:)(.*)", line)
                if m:
                    n2 = f"{ln}.{len(m.group(1))}"
                    c2 = f"{ln}.{len(m.group(1))+1}"
                    w.tag_add("hdr_name",  f"{ln}.0", n2)
                    w.tag_add("hdr_colon", n2, c2)
                    w.tag_add("hdr_val",   c2, e)

    # ── Proxy ──────────────────────────────────────────────────
    def _write_addon(self) -> str:
        fd, path = tempfile.mkstemp(suffix="_placebets_addon.py")
        with os.fdopen(fd, "w") as f:
            f.write(ADDON_SOURCE)
        return path

    def _start_proxy(self):
        if self._running:
            return
        if not shutil.which("mitmdump"):
            messagebox.showerror("mitmproxy not found",
                "mitmdump not found.\n\nInstall: pip install mitmproxy")
            return
        self._addon_path = self._write_addon()
        cmd = ["mitmdump", "-s", self._addon_path,
               "--listen-host", PROXY_HOST, "--listen-port", str(PROXY_PORT), "-q"]
        try:
            self._proxy_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except Exception as e:
            messagebox.showerror("Launch error", str(e))
            return
        self._running = True
        self._btn_start.configure(state="disabled")
        self._btn_stop.configure(state="normal")
        self._status_var.set("● RUNNING")
        self._status_lbl.configure(fg=S_ACCENT2)
        self._log(f"Proxy started — {PROXY_HOST}:{PROXY_PORT}")
        threading.Thread(target=self._watch_proc, daemon=True).start()

    def _watch_proc(self):
        if self._proxy_proc:
            self._proxy_proc.wait()
            if self._running:
                self.after(0, self._on_proxy_died)

    def _on_proxy_died(self):
        self._running = False
        self._btn_start.configure(state="normal")
        self._btn_stop.configure(state="disabled")
        self._status_var.set("● IDLE")
        self._status_lbl.configure(fg=S_DIM)
        self._log("Proxy exited unexpectedly")

    def _stop_proxy(self):
        if self._proxy_proc:
            self._proxy_proc.terminate()
            self._proxy_proc = None
        if self._addon_path and os.path.exists(self._addon_path):
            os.unlink(self._addon_path)
            self._addon_path = None
        self._running = False
        self._btn_start.configure(state="normal")
        self._btn_stop.configure(state="disabled")
        self._status_var.set("● IDLE")
        self._status_lbl.configure(fg=S_DIM)
        self._log("Proxy stopped")

    # ── Clipboard ──────────────────────────────────────────────
    def _copy_selected(self):
        if self._selected_idx is None:
            self._log("Nothing selected"); return
        self._to_clipboard(self._requests[self._selected_idx])
        self._log(f"Copied request #{self._selected_idx + 1}")

    def _copy_all(self):
        if not self._requests:
            self._log("Nothing to copy"); return
        sep = "\n" + "─" * 80 + "\n"
        self._to_clipboard(sep.join(self._requests))
        self._log(f"Copied all {len(self._requests)} requests")

    def _to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()

    # ── Delete ─────────────────────────────────────────────────
    def _delete_selected(self):
        if self._selected_idx is None:
            self._log("Nothing selected to delete"); return
        idx = self._selected_idx
        self._requests.pop(idx)
        saved = list(self._requests)
        self._requests.clear()
        self._list_rows.clear()
        self._selected_idx = None
        for w in self._list_inner.winfo_children():
            w.destroy()
        self._set_raw("")
        self._raw_host_lbl.configure(text="")
        for raw in saved:
            self._requests.append(raw)
            i = len(self._requests) - 1
            self._add_list_item(i, self._extract_host(raw))
        self._count_var.set(f"{len(self._requests)} captured")
        self._log(f"Deleted request #{idx + 1}")
        if self._requests:
            self._select(min(idx, len(self._requests) - 1))

    # ── Clear ──────────────────────────────────────────────────
    def _clear_all(self):
        self._requests.clear()
        self._list_rows.clear()
        self._selected_idx = None
        for w in self._list_inner.winfo_children():
            w.destroy()
        self._set_raw("")
        self._raw_host_lbl.configure(text="")
        self._count_var.set("0 captured")
        self._log("Cleared")

    def _log(self, msg: str):
        self._log_var.set(f"[{datetime.now().strftime('%H:%M:%S')}]  {msg}")

    def _on_close(self):
        self._ipc_running = False
        self._stop_proxy()
        self.destroy()


# ══════════════════════════════════════════════════════════════════
#  REQUEST SENDER APP  (main window)
# ══════════════════════════════════════════════════════════════════
class RequestSenderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Request Sender Project Tester")
        self.root.geometry("610x730")

        self.is_running     = False
        self.pending_task_id = None
        self.executor       = ThreadPoolExecutor(max_workers=4)
        self._sniffer_win   = None          # singleton sniffer window

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        main_container = tk.Frame(root)
        main_container.pack(fill='both', expand=True, padx=8, pady=8)

        # ── Title row with Sniffer button ─────────────────────
        title_row = tk.Frame(main_container)
        title_row.pack(fill='x', pady=(0, 8))

        tk.Label(title_row, text="Project Request Sender Tester",
                 font=('Arial', 14, 'bold')).pack(side='left')

        tk.Button(
            title_row, text="🔍 Sniffer",
            command=self.open_sniffer,
            bg='#1a1a2e', fg='#00d4ff',
            font=('Arial', 10, 'bold'),
            relief='flat', cursor='hand2',
            padx=12, pady=4, bd=0,
            activebackground='#0f1419', activeforeground='#00ff9d'
        ).pack(side='right')

        # ── Global Control Panel ───────────────────────────────
        control_frame = tk.Frame(main_container, bg='#E0E0E0', padx=12, pady=6)
        control_frame.pack(fill='x', pady=(0, 8))

        tk.Label(control_frame, text="Global Control:", font=('Arial', 10, 'bold'),
                 bg='#E0E0E0').pack(side='left', padx=(0, 10))

        tk.Label(control_frame, text="Price:", font=('Arial', 9),
                 bg='#E0E0E0').pack(side='left', padx=(0, 3))
        self.global_price_var = tk.StringVar()
        tk.Entry(control_frame, textvariable=self.global_price_var, width=6,
                 font=('Arial', 9)).pack(side='left', padx=(0, 8))

        tk.Label(control_frame, text="Size:", font=('Arial', 9),
                 bg='#E0E0E0').pack(side='left', padx=(0, 3))
        self.global_size_var = tk.StringVar()
        tk.Entry(control_frame, textvariable=self.global_size_var, width=6,
                 font=('Arial', 9)).pack(side='left', padx=(0, 8))

        tk.Button(control_frame, text="Apply All", command=self.apply_global_values,
                  bg='#9C27B0', fg='white', font=('Arial', 9, 'bold'),
                  width=8).pack(side='left', padx=(0, 15))

        tk.Label(control_frame, text="Delay (ms):", font=('Arial', 9),
                 bg='#E0E0E0').pack(side='left', padx=(0, 3))
        self.delay_var = tk.StringVar(value="500")
        tk.Entry(control_frame, textvariable=self.delay_var, width=6,
                 font=('Arial', 9)).pack(side='left', padx=(0, 10))

        self.start_stop_button = tk.Button(control_frame, text="▶ START",
                                           command=self.toggle_task,
                                           bg='#4CAF50', fg='white',
                                           font=('Arial', 10, 'bold'), width=8)
        self.start_stop_button.pack(side='left', padx=5)

        self.global_status = tk.Label(control_frame, text="Ready", font=('Arial', 9),
                                      bg='#E0E0E0', fg='gray')
        self.global_status.pack(side='left', padx=8)

        # ── 2×2 grid ──────────────────────────────────────────
        grid_container = tk.Frame(main_container)
        grid_container.pack(fill='both', expand=True, pady=(0, 8))
        grid_container.grid_rowconfigure(0, weight=1)
        grid_container.grid_rowconfigure(1, weight=1)
        grid_container.grid_columnconfigure(0, weight=1)
        grid_container.grid_columnconfigure(1, weight=1)

        self.sections = []
        for i, (row, col) in enumerate([(0,0),(0,1),(1,0),(1,1)]):
            section = self.create_section(grid_container, i + 1)
            section.grid(row=row, column=col, sticky='nsew', padx=4, pady=4)
            self.sections.append(section)

        ttk.Separator(main_container, orient='horizontal').pack(fill='x', pady=6)

        # ── Log ───────────────────────────────────────────────
        log_frame = tk.Frame(main_container)
        log_frame.pack(fill='both', expand=True)
        tk.Label(log_frame, text="Common Log:",
                 font=('Arial', 10, 'bold')).pack(anchor='w', pady=(0, 3))
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, width=120)
        self.log_text.pack(fill='both', expand=True)
        tk.Button(log_frame, text="Clear Log", command=self.clear_log,
                  bg='#FF9800', fg='white', font=('Arial', 9)).pack(anchor='e', pady=3)

    # ── Open Sniffer (singleton) ───────────────────────────────
    def open_sniffer(self):
        if self._sniffer_win and self._sniffer_win.winfo_exists():
            self._sniffer_win.lift()
            self._sniffer_win.focus_force()
        else:
            self._sniffer_win = SnifferWindow(self.root)

    # ── Section creation ───────────────────────────────────────
    def create_section(self, parent, section_num):
        default_side = "BACK" if section_num % 2 == 1 else "LAY"
        section_frame = tk.LabelFrame(parent, text=f"Section {section_num}",
                                      font=('Arial', 10, 'bold'), padx=8, pady=6)

        tk.Label(section_frame, text="Paste Request:",
                 font=('Arial', 8, 'bold')).pack(anchor='w', pady=(0, 3))
        request_text = scrolledtext.ScrolledText(section_frame, height=4, width=30)
        request_text.pack(fill='both', expand=True, padx=3, pady=3)

        tk.Button(section_frame, text="Load Request",
                  command=lambda sn=section_num: self.load_request(sn),
                  bg='#4CAF50', fg='white', font=('Arial', 8)).pack(pady=3)

        params_frame = tk.Frame(section_frame)
        params_frame.pack(fill='x', padx=3, pady=6)

        row1 = tk.Frame(params_frame)
        row1.pack(fill='x', pady=2)
        tk.Label(row1, text="Price:", width=6, anchor='w', font=('Arial', 8)).pack(side='left')
        price_var = tk.StringVar()
        tk.Entry(row1, textvariable=price_var, width=12, font=('Arial', 8)).pack(side='left', padx=(0, 10))
        tk.Label(row1, text="Size:", width=5, anchor='w', font=('Arial', 8)).pack(side='left')
        size_var = tk.StringVar()
        tk.Entry(row1, textvariable=size_var, width=12, font=('Arial', 8)).pack(side='left')

        row2 = tk.Frame(params_frame)
        row2.pack(fill='x', pady=5)
        tk.Label(row2, text="Side:", width=6, anchor='w', font=('Arial', 8)).pack(side='left')
        side_var = tk.StringVar(value=default_side)

        back_indicator = tk.Label(row2, text="  ", bg='#2196F3', width=6, height=1,
                                  relief='sunken' if default_side == "BACK" else 'raised', bd=2)
        back_indicator.pack(side='left', padx=(5, 2))
        lay_indicator  = tk.Label(row2, text="  ", bg='#F44336', width=6, height=1,
                                  relief='sunken' if default_side == "LAY"  else 'raised', bd=2)
        lay_indicator.pack(side='left', padx=(2, 0))

        back_indicator.bind('<Button-1>', lambda e, sv=side_var, bi=back_indicator, li=lay_indicator:
                            self.set_side(sv, "BACK", bi, li))
        lay_indicator.bind('<Button-1>',  lambda e, sv=side_var, bi=back_indicator, li=lay_indicator:
                            self.set_side(sv, "LAY",  bi, li))

        row3 = tk.Frame(params_frame)
        row3.pack(fill='x', pady=2)
        tk.Label(row3, text="UUID:", width=6, anchor='w', font=('Arial', 8)).pack(side='left')
        uuid_var = tk.StringVar()
        tk.Entry(row3, textvariable=uuid_var, width=28, font=('Arial', 8)).pack(side='left', fill='x', expand=True)

        tk.Button(section_frame, text="Send",
                  command=lambda sn=section_num: self.send_single_request_async(sn),
                  bg='#2196F3', fg='white', font=('Arial', 9, 'bold'), height=1).pack(fill='x', pady=3)

        status_label = tk.Label(section_frame, text="Ready", fg='gray', font=('Arial', 8))
        status_label.pack(pady=2)

        section_frame.section_data = {
            'section_num': section_num,
            'request_text': request_text,
            'price_var': price_var,
            'size_var': size_var,
            'side_var': side_var,
            'side_indicators': {'back': back_indicator, 'lay': lay_indicator},
            'uuid_var': uuid_var,
            'status_label': status_label,
            'url': None, 'headers': None, 'json_data': None
        }
        return section_frame

    def set_side(self, side_var, side, back_indicator, lay_indicator):
        side_var.set(side)
        if side == "BACK":
            back_indicator.config(relief='sunken')
            lay_indicator.config(relief='raised')
        else:
            back_indicator.config(relief='raised')
            lay_indicator.config(relief='sunken')

    # ── JSON helpers ───────────────────────────────────────────
    def extract_json_from_text(self, text):
        start_idx = text.find('{')
        if start_idx == -1:
            return None
        json_text = text[start_idx:].rstrip()
        while json_text and json_text[-1] not in '}]':
            json_text = json_text[:-1]
        brace_count = bracket_count = 0
        in_string = escape_next = False
        end_idx = 0
        for i, char in enumerate(json_text):
            if escape_next:        escape_next = False; continue
            if char == '\\':       escape_next = True;  continue
            if char == '"':        in_string = not in_string; continue
            if in_string:          continue
            if   char == '{':      brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0: end_idx = i + 1; break
            elif char == '[':      bracket_count += 1
            elif char == ']':      bracket_count -= 1
        return json_text[:end_idx] if end_idx else json_text

    # ── Load request ───────────────────────────────────────────
    def load_request(self, section_num):
        try:
            section_data = self.sections[section_num - 1].section_data
            request_text = section_data['request_text'].get("1.0", tk.END).strip()
            if not request_text:
                messagebox.showwarning("Warning", f"Please paste a request in Section {section_num} first!")
                return

            json_text = self.extract_json_from_text(request_text)
            if not json_text:
                messagebox.showerror("Error", f"Section {section_num}: No JSON data found!")
                return

            json_data = None
            try:
                json_data = json.loads(json_text)
            except json.JSONDecodeError as e:
                self.log(f"Section {section_num}: JSON parse error, attempting fix...")
                if 'Extra data' in str(e):
                    for trim in [')', '})', '}}', '];', '])', '']:
                        try:
                            t = json_text[:-len(trim)] if trim else json_text
                            json_data = json.loads(t); break
                        except: continue
                if json_data is None:
                    lines = json_text.split('\n')
                    for i in range(len(lines), 0, -1):
                        try:
                            json_data = json.loads('\n'.join(lines[:i])); break
                        except: continue
                if json_data is None:
                    raise Exception(f"Could not parse JSON: {e}")

            headers = {}
            for line in request_text.split('\n'):
                line = line.strip()
                if line and ':' in line and not line.startswith('{'):
                    idx = line.index(':')
                    key, val = line[:idx].strip(), line[idx+1:].strip()
                    if key and key not in ['Content-Length', 'Accept-Encoding'] and not key.startswith('"'):
                        headers[key] = val

            host = headers.get('Host', 'ex.pb77.co')
            path = "/customer/api/placeBets"
            first = request_text.split('\n')[0].strip()
            if any(m in first for m in ['POST', 'GET', 'PUT', 'DELETE']):
                parts = first.split()
                if len(parts) >= 2 and parts[1].startswith('/'):
                    path = parts[1]

            section_data['url']       = f"https://{host}{path}"
            section_data['headers']   = headers
            section_data['json_data'] = json_data

            if isinstance(json_data, dict):
                market_key = list(json_data.keys())[0]
                if isinstance(json_data[market_key], list) and json_data[market_key]:
                    bet = json_data[market_key][0]
                    section_data['price_var'].set(str(bet.get('price', '')))
                    section_data['size_var'].set(str(bet.get('size', '')))
                    section_data['uuid_var'].set(str(bet.get('betUuid', '')))
                    section_data['status_label'].config(text="Loaded", fg='green')
                    self.log(f"Section {section_num}: Loaded — Price:{bet.get('price')} Size:{bet.get('size')}")
                else:
                    messagebox.showerror("Error", f"Section {section_num}: Invalid bet data structure!")
            else:
                messagebox.showerror("Error", f"Section {section_num}: JSON not in expected format!")
        except Exception as e:
            messagebox.showerror("Error", f"Section {section_num}: {str(e)}")
            self.log(f"Section {section_num}: Parse error — {e}")
            self.sections[section_num-1].section_data['status_label'].config(text="Parse Error", fg='red')

    # ── Send request ───────────────────────────────────────────
    def send_request(self, section_num):
        try:
            section_data = self.sections[section_num - 1].section_data
            price    = section_data['price_var'].get()
            size     = section_data['size_var'].get()
            side     = section_data['side_var'].get()
            bet_uuid = section_data['uuid_var'].get()

            if not all([price, size, side, bet_uuid]):
                messagebox.showwarning("Warning", f"Section {section_num}: All fields must be filled!")
                return None
            if not section_data['json_data']:
                messagebox.showwarning("Warning", f"Section {section_num}: Please load a request first!")
                return None

            json_data_copy = copy.deepcopy(section_data['json_data'])
            market_key = list(json_data_copy.keys())[0]
            bet = json_data_copy[market_key][0]

            try:    bet['price'] = float(price)
            except: bet['price'] = price
            bet['size'] = size
            bet['side'] = side

            ts = int(datetime.now().timestamp() + 2)
            bet['betUuid'] = f"{market_key}_{bet.get('selectionId', '')}_0__{ts}_INLINE"
            section_data['uuid_var'].set(bet['betUuid'])
            self.log(f"Section {section_num}: New UUID ts: {ts}")

            headers = dict(section_data['headers'])
            if 'X-Csrf-Token' in headers:
                cookie = headers.get('Cookie', '')
                if 'CSRF-TOKEN=' in cookie:
                    csrf = cookie.split('CSRF-TOKEN=')[-1].split(';')[0]
                    if csrf: headers['X-Csrf-Token'] = csrf

            section_data['status_label'].config(text="Sending...", fg='blue')
            self.log(f"Section {section_num}: Sending {side} — Price={price}, Size={size}")

            return {
                'section_num': section_num,
                'url':         section_data['url'],
                'json_data':   json_data_copy,
                'headers':     headers,
                'status_label': section_data['status_label']
            }
        except Exception as e:
            self.sections[section_num-1].section_data['status_label'].config(text="Error", fg='red')
            self.log(f"Section {section_num}: ✗ ERROR — {e}")
            return None

    def _do_http_request(self, request_data):
        sn = request_data['section_num']
        try:
            r = http_requests.post(request_data['url'], json=request_data['json_data'],
                                   headers=request_data['headers'], verify=True, timeout=30)
            return {'section_num': sn, 'status_code': r.status_code, 'response': r, 'error': None}
        except http_requests.exceptions.RequestException as e:
            return {'section_num': sn, 'status_code': None, 'response': None, 'error': f"NETWORK ERROR — {e}"}
        except Exception as e:
            return {'section_num': sn, 'status_code': None, 'response': None, 'error': str(e)}

    def _handle_response(self, result):
        sn = result['section_num']
        sd = self.sections[sn - 1].section_data
        if result['error']:
            sd['status_label'].config(text="Network Error", fg='red')
            self.log(f"Section {sn}: ✗ {result['error']}"); return

        r = result['response']
        if r.status_code == 200:
            try:
                rj = r.json()
                has_error, error_msg, success_msg = False, "", ""
                for _, md in rj.items():
                    if isinstance(md, dict):
                        st = md.get('status', '')
                        if st == 'FAIL':
                            has_error = True
                            ec = md.get('error', 'Unknown')
                            ex = md.get('exception', {})
                            error_msg = f"{ec} ({ex.get('id','')})"
                            if ex.get('message'): error_msg += f": {ex['message'][:80]}..."
                        elif st == 'SUCCESS':
                            oi = md.get('offerIds', {})
                            if oi: success_msg = f"Offer IDs: {oi}"
                if has_error:
                    sd['status_label'].config(text="FAILED", fg='red')
                    self.log(f"Section {sn}: ✗ BET FAILED — {error_msg}")
                else:
                    sd['status_label'].config(text="✓ SUCCESS", fg='green')
                    self.log(f"Section {sn}: ✓ BET SUCCESS" + (f" — {success_msg}" if success_msg else ""))
            except:
                sd['status_label'].config(text="Success", fg='green')
                self.log(f"Section {sn}: ✓ 200 OK")
        else:
            sd['status_label'].config(text=f"HTTP {r.status_code}", fg='red')
            self.log(f"Section {sn}: ✗ HTTP {r.status_code}")
            try:    self.log(f"Section {sn}: {json.dumps(r.json(), indent=2)[:300]}")
            except: self.log(f"Section {sn}: {r.text[:200]}")

    def send_single_request_async(self, section_num):
        rd = self.send_request(section_num)
        if rd:
            future = self.executor.submit(self._do_http_request, rd)
            self._check_single_future(future)

    def _check_single_future(self, future):
        if future.done():
            try:    self._handle_response(future.result())
            except Exception as e: self.log(f"Error: {e}")
        else:
            self.root.after(10, lambda: self._check_single_future(future))

    def log(self, message):
        ts = datetime.now().strftime("%H:%M:%S")
        self.root.after(0, lambda: self._append_log(f"[{ts}] {message}\n"))

    def _append_log(self, message):
        self.log_text.insert(tk.END, message)
        self.log_text.see(tk.END)

    def clear_log(self):
        self.log_text.delete("1.0", tk.END)

    def apply_global_values(self):
        gp, gs = self.global_price_var.get().strip(), self.global_size_var.get().strip()
        if not gp and not gs:
            messagebox.showwarning("Warning", "Enter at least Price or Size!"); return
        for i, sf in enumerate(self.sections):
            sd = sf.section_data
            if gp: sd['price_var'].set(gp)
            if gs:  sd['size_var'].set(gs)
        msg = f"Applied to all sections:"
        if gp: msg += f" Price={gp}"
        if gs:  msg += f" Size={gs}"
        self.log(msg)

    def on_closing(self):
        self.is_running = False
        if self.pending_task_id:
            self.root.after_cancel(self.pending_task_id)
        self.executor.shutdown(wait=False)
        self.root.destroy()

    def toggle_task(self):
        if self.is_running: self.stop_task()
        else:               self.start_task()

    def start_task(self):
        try:
            delay_ms = max(0, int(self.delay_var.get()))
        except ValueError:
            messagebox.showwarning("Warning", "Enter a valid delay in ms!"); return
        self.is_running = True
        self.start_stop_button.config(text="■ STOP", bg='#f44336')
        self.global_status.config(text="Running...", fg='blue')
        self.log("=== Global Task Started (Loop Mode) ===")
        self.run_cycle_part1()

    def run_cycle_part1(self):
        if not self.is_running: return
        try:    delay_ms = max(0, int(self.delay_var.get()))
        except: delay_ms = 500
        self.log("Sending Section 1 & Section 4...")
        futures = [self.executor.submit(self._do_http_request, rd)
                   for rd in [self.send_request(1), self.send_request(4)] if rd]
        if futures:
            self._wait_for_futures(futures, delay_ms, self.run_cycle_part2)
        else:
            self.pending_task_id = self.root.after(delay_ms, self.run_cycle_part2)

    def run_cycle_part2(self):
        if not self.is_running: return
        try:    delay_ms = max(0, int(self.delay_var.get()))
        except: delay_ms = 500
        self.log("Sending Section 2 & Section 3...")
        futures = [self.executor.submit(self._do_http_request, rd)
                   for rd in [self.send_request(2), self.send_request(3)] if rd]
        if futures:
            self._wait_for_futures(futures, delay_ms, self.run_cycle_part1)
        else:
            self.pending_task_id = self.root.after(delay_ms, self.run_cycle_part1)

    def _wait_for_futures(self, futures, delay_ms, next_cb):
        if all(f.done() for f in futures):
            for f in futures:
                try:    self._handle_response(f.result())
                except Exception as e: self.log(f"Error: {e}")
            if self.is_running:
                self.log(f"Waiting {delay_ms}ms...")
                self.pending_task_id = self.root.after(delay_ms, next_cb)
        else:
            self.pending_task_id = self.root.after(10, lambda: self._wait_for_futures(futures, delay_ms, next_cb))

    def stop_task(self):
        if self.pending_task_id:
            self.root.after_cancel(self.pending_task_id)
            self.pending_task_id = None
        self.is_running = False
        self.start_stop_button.config(text="▶ START", bg='#4CAF50')
        self.global_status.config(text="Stopped", fg='orange')
        self.log("=== Global Task Stopped ===")


# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    root = tk.Tk()
    app = RequestSenderApp(root)
    root.mainloop()