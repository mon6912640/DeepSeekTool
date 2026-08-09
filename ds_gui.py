# -*- coding: utf-8 -*-
"""DeepSeek 用量桌面小工具 (tkinter)
用法: python ds_gui.py
"""
import json
import time
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk, messagebox, simpledialog
from pathlib import Path
import ds_api

HISTORY_FILE = Path(__file__).parent / "usage_history.json"
CONFIG_FILE = Path(__file__).parent / "ds_gui_config.json"
MINI_BG = "#1a1a2e"


def _load_gui_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_gui_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def _fmt_rate(rate):
    """缓存命中率: rate=None(无数据) 显示 --"""
    if rate is None:
        return "--"
    return f"{rate*100:.1f}%"


class UsageApp:
    def __init__(self, root):
        self.root = root
        root.title("DeepSeek 用量监控")
        root.geometry("1020x600")
        root.minsize(860, 500)
        # 窗口/任务栏图标 (DeepSeek 官网 favicon)
        try:
            root.iconbitmap(str(Path(__file__).parent / "deepseek.ico"))
        except Exception:
            pass

        # --- 迷你模式 (单行无边框条) ---
        self.mini_mode = False
        self._drag_offset = None
        self.mini_frame = tk.Frame(root, bg=MINI_BG)
        self.mini_today = tk.Label(self.mini_frame, text="--", font=("Microsoft YaHei", 11, "bold"),
                                   fg="#f39c12", bg=MINI_BG)
        self.mini_balance = tk.Label(self.mini_frame, text="--", font=("Microsoft YaHei", 11, "bold"),
                                     fg="#2ecc71", bg=MINI_BG)
        self.mini_cache = tk.Label(self.mini_frame, text="--", font=("Microsoft YaHei", 11, "bold"),
                                   fg="#26c6da", bg=MINI_BG)
        self.mini_time = tk.Label(self.mini_frame, text="", font=("Microsoft YaHei", 8),
                                  fg="#555", bg=MINI_BG)
        self.mini_btn = tk.Label(self.mini_frame, text="🔼", font=("Microsoft YaHei", 10),
                                 fg="#aaa", bg=MINI_BG, cursor="hand2")
        # 迷你条左侧 DeepSeek 图标
        try:
            self._mini_icon_img = tk.PhotoImage(file=str(Path(__file__).parent / "deepseek_mini.png"))
            self.mini_icon = tk.Label(self.mini_frame, image=self._mini_icon_img, bg=MINI_BG)
        except Exception:
            self.mini_icon = None
        if self.mini_icon:
            self.mini_icon.pack(side="left", padx=(6, 0), pady=2)
        tk.Label(self.mini_frame, text="今日", font=("Microsoft YaHei", 9), fg="#888",
                 bg=MINI_BG).pack(side="left")
        self.mini_today.pack(side="left", padx=(4, 0))
        tk.Label(self.mini_frame, text="·", font=("Microsoft YaHei", 9), fg="#444",
                 bg=MINI_BG).pack(side="left", padx=8)
        tk.Label(self.mini_frame, text="余额", font=("Microsoft YaHei", 9), fg="#888",
                 bg=MINI_BG).pack(side="left")
        self.mini_balance.pack(side="left", padx=(4, 0))
        tk.Label(self.mini_frame, text="缓存", font=("Microsoft YaHei", 9), fg="#888",
                 bg=MINI_BG).pack(side="left", padx=(10, 0))
        self.mini_cache.pack(side="left", padx=(4, 0))
        self.mini_time.pack(side="left", padx=(8, 0), pady=(2, 0))
        self.mini_btn.pack(side="right", padx=4)
        self.mini_btn.bind("<Button-1>", lambda e: self.toggle_mode())
        # 拖动
        for w in (self.mini_frame, self.mini_today, self.mini_balance, self.mini_cache, self.mini_time):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_motion)
            w.bind("<ButtonRelease-1>", self._drag_end)
        if self.mini_icon:
            for ev in ("<Button-1>", "<B1-Motion>", "<ButtonRelease-1>"):
                self.mini_icon.bind(ev, getattr(self, {"<Button-1>": "_drag_start",
                                                       "<B1-Motion>": "_drag_motion",
                                                       "<ButtonRelease-1>": "_drag_end"}[ev]))
        # 右键菜单 + Esc 关闭
        self.context_menu = tk.Menu(root, tearoff=0)
        self.context_menu.add_command(label="立即刷新", command=self.refresh)
        self.context_menu.add_command(label="完整 / 迷你模式", command=self.toggle_mode)
        self.context_menu.add_command(label="置顶", command=self.toggle_topmost)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="退出", command=self._on_close)
        root.bind("<Button-3>", self._show_menu)
        root.bind("<Escape>", lambda e: self._on_close())
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        # --- 完整模式 UI ---
        self.full_frame = tk.Frame(root)
        self.full_frame.pack(fill="both", expand=True)
        top = ttk.Frame(self.full_frame, padding=10)
        top.pack(fill="x")
        self.var_balance = tk.StringVar(value="--")
        self.var_cost = tk.StringVar(value="--")
        self.var_todaycost = tk.StringVar(value="--")
        self.var_30cost = tk.StringVar(value="--")
        self.var_30req = tk.StringVar(value="--")
        self.var_30tok = tk.StringVar(value="--")
        self.var_todaycache = tk.StringVar(value="--")
        self.var_status = tk.StringVar(value="就绪")
        cards = [
            ("充值余额", self.var_balance, "#2e7d32"),
            ("累计消费", self.var_cost, "#c62828"),
            ("今日消费", self.var_todaycost, "#d84315"),
            ("今日缓存率", self.var_todaycache, "#00838f"),
            ("近30天消费", self.var_30cost, "#1565c0"),
            ("近30天请求", self.var_30req, "#6a1b9a"),
            ("近30天Tokens", self.var_30tok, "#e65100"),
        ]
        for i, (label, var, color) in enumerate(cards):
            f = ttk.Frame(top)
            f.grid(row=0, column=i, padx=8)
            ttk.Label(f, text=label, foreground="#666").pack()
            ttk.Label(f, textvariable=var, font=("Segoe UI", 15, "bold"), foreground=color).pack()

        # 表格
        mid = ttk.Frame(self.full_frame, padding=(10, 0, 10, 5))
        mid.pack(fill="both", expand=True)
        cols = ("api", "model", "cost", "requests", "tokens", "cache_rate")
        self._sort_col = None
        self._sort_rev = False
        self._rows = []
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=12)
        self._heads = {"api": ("API Key", 180), "model": ("模型", 140), "cost": ("消费(¥)", 80),
                       "requests": ("请求次数", 80), "tokens": ("Tokens", 100), "cache_rate": ("缓存率", 75)}
        for c, (t, w) in self._heads.items():
            self.tree.heading(c, text=t, command=lambda c=c: self._sort_by(c))
            self.tree.column(c, width=w, anchor="e" if c in ("cost", "requests", "tokens", "cache_rate") else "w")
        self.tree.pack(fill="both", expand=True)
        self.tree.tag_configure("zero", foreground="#bbb")

        # 底部
        bottom = ttk.Frame(self.full_frame, padding=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="立即刷新", command=self.refresh).pack(side="left")
        ttk.Button(bottom, text="更新Token", command=self.update_token).pack(side="left", padx=8)
        ttk.Button(bottom, text="今日快照", command=self.snapshot).pack(side="left")
        ttk.Button(bottom, text="迷你模式", command=self.toggle_mode).pack(side="left", padx=8)
        ttk.Label(bottom, textvariable=self.var_status, foreground="#888").pack(side="right")

        # 恢复上次模式 + 偏好
        cfg = _load_gui_config()
        self._topmost = bool(cfg.get("topmost", True))  # 默认置顶，用户可手动关
        self.root.attributes("-topmost", self._topmost)
        if cfg.get("mini_mode"):
            self.mini_mode = True
            self.full_frame.pack_forget()
            self.mini_frame.pack(fill="both", expand=True)
            self._apply_mini_window()
        self.root.update_idletasks()
        self.restore_position()
        self._keep_topmost()  # 置顶看门狗
        self.refresh()
        # 自动刷新: 每 10 分钟
        self._auto_refresh()

    # ---------- 迷你模式 ----------
    def _apply_mini_window(self):
        self.root.overrideredirect(True)
        self.root.minsize(300, 40)
        self.root.update_idletasks()
        w = self.mini_frame.winfo_reqwidth() + 30
        self.root.geometry(f"{max(w, 320)}x40")
        self.root.attributes("-topmost", self._topmost)

    def _apply_full_window(self):
        self.root.overrideredirect(False)
        self.root.geometry("1020x600")
        self.root.minsize(860, 500)
        self.root.attributes("-topmost", self._topmost)

    def _on_close(self):
        """退出前保存当前模式位置（完整模式拖标题栏不触发Python事件，需在退出时补存）"""
        self.save_position()
        self.root.destroy()

    def toggle_mode(self):
        prev = (self.root.winfo_x(), self.root.winfo_y(),
                self.root.winfo_width(), self.root.winfo_height())
        self.save_position()  # 切换前保存当前模式自己的位置，避免互相覆盖
        self.mini_mode = not self.mini_mode
        if self.mini_mode:
            self.full_frame.pack_forget()
            self.mini_frame.pack(fill="both", expand=True)
            self._apply_mini_window()
        else:
            self.mini_frame.pack_forget()
            self.full_frame.pack(fill="both", expand=True)
            self._apply_full_window()
        if not self.restore_position():
            # 该模式还没记录过位置 → 按就近边缘锚定一个默认位置（防越屏）
            self._snap_to_nearest_edge(prev)
        self._save_cfg_field("mini_mode", self.mini_mode)

    def toggle_topmost(self):
        self._topmost = not self._topmost
        self.root.attributes("-topmost", self._topmost)
        self._save_cfg_field("topmost", self._topmost)
        if hasattr(self, "var_status"):
            self.var_status.set(f"置顶: {'开' if self._topmost else '关'}")

    def _keep_topmost(self):
        """置顶看门狗：桌面/锁屏等 shell 事件偶尔丢置顶标志，5 秒补一次；
        用户手动关闭（self._topmost=False）后不抢回"""
        if self._topmost and not self.root.attributes("-topmost"):
            self.root.attributes("-topmost", True)
        self.root.after(5000, self._keep_topmost)

    def _save_cfg_field(self, key, value):
        cfg = _load_gui_config()
        cfg[key] = value
        _save_gui_config(cfg)

    def save_position(self):
        """拖动结束按当前模式分别记录位置，供下次启动/切换时恢复"""
        key = "mini_window_pos" if self.mini_mode else "full_window_pos"
        self._save_cfg_field(key, [self.root.winfo_x(), self.root.winfo_y()])

    def restore_position(self):
        """恢复当前模式记录的位置（迷你/完整分开记忆）；位置超出可见工作区
        （显示器拔掉/任务栏遮挡）时放弃。返回 True 表示已恢复。"""
        key = "mini_window_pos" if self.mini_mode else "full_window_pos"
        pos = _load_gui_config().get(key)
        if not isinstance(pos, (list, tuple)) or len(pos) != 2:
            # 兼容旧版本单一 window_pos
            pos = _load_gui_config().get("window_pos")
        if not isinstance(pos, (list, tuple)) or len(pos) != 2:
            return False
        try:
            x, y = int(pos[0]), int(pos[1])
        except (TypeError, ValueError):
            return False
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        area = self._get_work_area(x + w // 2, y + h // 2)
        if area is None:
            return False
        r_left, r_top, r_right, r_bottom = area
        overlap_x = min(x + w, r_right) - max(x, r_left)
        overlap_y = min(y + h, r_bottom) - max(y, r_top)
        if overlap_x < 60 or overlap_y < 30:
            return False  # 可能在已断开显示器上或被任务栏遮挡
        self.root.geometry(f"+{x}+{y}")
        return True

    def _get_work_area(self, x, y):
        """取 (x, y) 所在显示器工作区（不含任务栏）"""
        try:
            import ctypes
            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT),
                            ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]
            user32 = ctypes.windll.user32
            hmon = user32.MonitorFromPoint(POINT(x, y), 2)
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                return None
            r = mi.rcWork
            return (r.left, r.top, r.right, r.bottom)
        except Exception:
            return None

    def _snap_to_nearest_edge(self, prev):
        """切换模式后按就近纵向边缘重排：切换前位于下半屏锚底边、上半屏锚顶边，
        再整体钳入工作区。保证贴边迷你条往返切换位置可逆、展开不越出屏幕。"""
        px, py, pw, ph = prev
        area = self._get_work_area(px + pw // 2, py + ph // 2)
        if area is None:
            return
        left, top, right, bottom = area
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        if py + ph // 2 > (top + bottom) // 2:
            y = py + ph - h
        else:
            y = py
        x = min(max(px, left), max(left, right - w))
        y = min(max(y, top), max(top, bottom - h))
        self.root.geometry(f"+{x}+{y}")

    def _show_menu(self, event):
        # 置顶项动态显示勾选状态
        self.context_menu.entryconfig(2, label=("✓ 置顶" if self._topmost else "置顶"))
        self.context_menu.post(event.x_root, event.y_root)

    def _drag_start(self, event):
        if str(event.widget.cget("cursor")) == "hand2":
            self._drag_offset = None
            return
        self._drag_offset = (event.x_root - self.root.winfo_x(),
                             event.y_root - self.root.winfo_y())

    def _drag_motion(self, event):
        if self._drag_offset is None:
            return
        x = event.x_root - self._drag_offset[0]
        y = event.y_root - self._drag_offset[1]
        self.root.geometry(f"+{x}+{y}")

    def _drag_end(self, event):
        if self._drag_offset is None:
            return
        self._drag_offset = None
        self.save_position()

    def _auto_refresh(self):
        self.refresh()
        self.root.after(600_000, self._auto_refresh)

    def refresh(self):
        def worker():
            try:
                tok = ds_api.get_valid_token()
                if not tok:
                    self.var_status.set("未检测到登录态，点击 更新Token 引导登录")
                    self.root.after(0, self._maybe_guide)
                    return
                s = ds_api.get_summary(tok)
                u = ds_api.get_usage(tok, 30)
                t_start, t_end = ds_api._today_range()
                today = ds_api.get_usage(tok, start=t_start, end=t_end)
                self.var_balance.set(f"¥{s['balance']:.2f}")
                self.var_cost.set(f"¥{s['total_cost']:.2f}")
                self.var_todaycost.set(f"¥{today['total_cost']:.2f}")
                self.var_todaycache.set(_fmt_rate(today.get("cache_rate")))
                self.var_30cost.set(f"¥{u['total_cost']:.2f}")
                self.var_30req.set(f"{u['total_requests']:,}")
                self.var_30tok.set(_fmt_tokens(u['total_tokens']))
                self._fill_table(u['rows'])
                self.mini_today.config(text=f"¥{today['total_cost']:.2f}", fg="#f39c12")
                self.mini_balance.config(text=f"¥{s['balance']:.2f}", fg="#2ecc71")
                self.mini_cache.config(text=_fmt_rate(today.get("cache_rate")), fg="#26c6da")
                self.mini_time.config(text=time.strftime("%H:%M"))
                self.var_status.set("更新于 " + time.strftime("%H:%M:%S"))
                if self.mini_mode:
                    self.root.update_idletasks()
                    w = self.mini_frame.winfo_reqwidth() + 30
                    self.root.geometry(f"{max(w, 320)}x40")  # 数字变长时自适应宽度
            except ds_api.ApiError as e:
                self.var_status.set("错误: " + str(e)[:60])
                self.mini_today.config(fg="#777")   # 数据过期置灰
                self.mini_balance.config(fg="#777")
                self.mini_cache.config(fg="#777")
                messagebox.showerror("获取失败", str(e))
        threading.Thread(target=worker, daemon=True).start()

    def _fill_table(self, rows):
        self._rows = list(rows)
        if self._sort_col:
            self._sort_rows()
        for i in self.tree.get_children():
            self.tree.delete(i)
        for r in self._rows:
            zero = r["cost"] == 0 and r["requests"] == 0
            hit, miss = r.get("cache_hit_tokens", 0), r.get("cache_miss_tokens", 0)
            rate = (hit / (hit + miss)) if (hit + miss) else None
            self.tree.insert("", "end", values=(
                r["api_name"], r["model"], f"{r['cost']:.4f}",
                r["requests"], _fmt_tokens(r["tokens"]), _fmt_rate(rate)),
                tags=("zero",) if zero else ())
        self._draw_headings()

    # --- 表头排序 ---
    def _sort_key(self, col, r):
        if col == "api":
            return (False, r["api_name"].lower())
        if col == "model":
            return (False, r["model"].lower())
        if col == "cost":
            return (False, r["cost"])
        if col == "requests":
            return (False, r["requests"])
        if col == "tokens":
            return (False, r["tokens"])
        if col == "cache_rate":
            h, m = r.get("cache_hit_tokens", 0), r.get("cache_miss_tokens", 0)
            return (True, 0) if not (h + m) else (False, h / (h + m))  # 无数据恒排最后
        return (False, 0)

    def _sort_rows(self):
        keyf = lambda r: self._sort_key(self._sort_col, r)
        with_data = [r for r in self._rows if not keyf(r)[0]]
        without = [r for r in self._rows if keyf(r)[0]]
        with_data.sort(key=keyf, reverse=self._sort_rev)
        self._rows = with_data + without  # 无数据行恒沉底

    def _sort_by(self, col):
        if self._sort_col == col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col, self._sort_rev = col, False
        self._sort_rows()
        self._fill_table(self._rows)

    def _draw_headings(self):
        for c, (t, w) in self._heads.items():
            arrow = " ▼" if c == self._sort_col and self._sort_rev else (" ▲" if c == self._sort_col else "")
            self.tree.heading(c, text=t + arrow)

    def _find_valid_from_chrome(self):
        """扫描 Chrome 并验证, 返回第一个有效 token, 无则空串"""
        for cand in ds_api.extract_token_from_chrome():
            try:
                ds_api.get_summary(cand)
                return cand
            except ds_api.ApiError:
                continue
        return ""

    def _maybe_guide(self):
        """检测不到登录态: 仅首次自动弹引导, 避免自动刷新反复打扰"""
        if getattr(self, "_guided", False):
            self.var_status.set("未检测到登录态，点击 更新Token 手动处理")
            return
        self._guided = True
        if messagebox.askyesno("引导登录", "未检测到 DeepSeek 登录态。\n将打开官网引导登录，是否继续？\n\n点『是』自动打开并检测；点『否』稍后手动处理。"):
            self._guide_login()
        else:
            self._manual_token()

    def _guide_login(self):
        """引导登录: 打开官网 → 自动轮询检测 → 手动粘贴兜底"""
        webbrowser.open("https://platform.deepseek.com")
        self.var_status.set("已打开登录页，请在浏览器中登录...")
        self._poll_attempt = 0
        self.root.after(3000, self._poll_token)

    def _poll_token(self):
        """轮询 Chrome, 检测到有效 token 即保存刷新; 超时给出手动粘贴提示"""
        self._poll_attempt += 1
        tok = self._find_valid_from_chrome()
        if tok:
            ds_api.save_token(tok)
            self.var_status.set("已自动从 Chrome 读取 Token")
            self.refresh()
            messagebox.showinfo("登录成功", "已自动获取登录态，开始显示用量数据")
            return
        if self._poll_attempt < 15:  # 最多 15 次 * 2s = 30s
            self.var_status.set(f"等待登录完成... ({self._poll_attempt}/15)")
            self.root.after(2000, self._poll_token)
        else:
            self.var_status.set("仍未检测到登录态，点击 更新Token 手动处理")
            self._manual_token()

    def _manual_token(self):
        tok = simpledialog.askstring("更新Token", "未能从 Chrome 自动获取。\n请粘贴 userToken（浏览器 F12 → 控制台执行 localStorage.getItem('userToken') 取 value）：", show="*")
        if tok:
            ds_api.save_token(tok.strip())
            self.var_status.set("Token 已更新")
            self.refresh()

    def update_token(self):
        auto = self._find_valid_from_chrome()
        if auto:
            ds_api.save_token(auto)
            self.var_status.set("已自动从 Chrome 读取 Token")
            self.refresh()
            return
        if messagebox.askyesno("引导登录", "未在 Chrome 中找到有效登录态。\n将打开 DeepSeek 官网，请在浏览器中登录。\n\n点『是』自动打开并检测；点『否』手动粘贴 Token。"):
            self._guide_login()
        else:
            self._manual_token()

    def snapshot(self):
        """记录当前余额/累计消费到本地 JSON, 供趋势参考"""
        try:
            s = ds_api.get_summary(ds_api.load_token())
            rec = {"time": int(time.time()), "date": time.strftime("%Y-%m-%d %H:%M"),
                   "balance": round(s["balance"], 4), "total_cost": round(s["total_cost"], 4)}
            hist = []
            if HISTORY_FILE.exists():
                hist = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            hist.append(rec)
            HISTORY_FILE.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
            messagebox.showinfo("今日快照", f"已记录 {rec['date']}\n余额 ¥{rec['balance']:.2f} / 累计消费 ¥{rec['total_cost']:.2f}\n历史共 {len(hist)} 条")
        except Exception as e:
            messagebox.showerror("快照失败", str(e))


def main():
    # 单实例：已有实例在跑时直接退出（防止重复开启多个迷你条）
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW(None, False, "Local\\DeepSeekUsage_SingleInstance")
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return
    except Exception:
        pass
    root = tk.Tk()
    # Windows 下设置 DPI 感知, 字体更清晰
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    UsageApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
