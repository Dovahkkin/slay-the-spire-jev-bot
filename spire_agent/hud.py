import queue
import threading
import tkinter as tk
from typing import Optional


class SpireHud:
    """
    杀戮尖塔 Jev AI 桌面置顶透明悬浮窗 (In-Game HUD Overlay)
    无需修改游戏本体 Java 代码，实时显示 Jev 的战术推演、敌我威胁计算与当前操作。
    """

    def __init__(self, title: str = "JEV AI ASSISTANT", width: int = 420, height: int = 220):
        self.width = width
        self.height = height
        self.title_text = title
        self.msg_queue = queue.Queue()
        self.root: Optional[tk.Tk] = None
        self._drag_start_x = 0
        self._drag_start_y = 0

        self.thread = threading.Thread(target=self._run_gui, daemon=True)
        self.thread.start()

    def _run_gui(self):
        try:
            self.root = tk.Tk()
            self.root.title(self.title_text)
            self.root.overrideredirect(True)  # 无边框
            self.root.attributes("-topmost", True)  # 永远置顶
            self.root.attributes("-alpha", 0.92)  # 半透明玻璃质感

            # 默认停靠在屏幕右上角 (距离右边 40px，上边 40px)
            screen_w = self.root.winfo_screenwidth()
            start_x = max(10, screen_w - self.width - 40)
            start_y = 40
            self.root.geometry(f"{self.width}x{self.height}+{start_x}+{start_y}")

            # 主题色彩
            bg_color = "#13151b"
            card_bg = "#1b1e27"
            border_color = "#2c3140"
            accent_cyan = "#00f0ff"
            accent_gold = "#ffc83b"
            text_white = "#f0f2f5"
            text_gray = "#8a92a5"

            self.root.configure(bg=border_color)

            # 内部卡片容器 (实现 1px 细边框)
            container = tk.Frame(self.root, bg=bg_color)
            container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

            # 1. 顶部标题栏 (支持拖动)
            header = tk.Frame(container, bg=card_bg, height=32)
            header.pack(fill=tk.X)

            title_label = tk.Label(
                header,
                text="🤖 JEV SPIRE HUD",
                bg=card_bg,
                fg=accent_cyan,
                font=("Consolas", 10, "bold"),
            )
            title_label.pack(side=tk.LEFT, padx=10, pady=5)

            # 状态徽章 (如 🟢 思考中 / ⚡ 出牌)
            self.badge_label = tk.Label(
                header,
                text="● READY",
                bg="#262b3a",
                fg="#2ed573",
                font=("Segoe UI", 9, "bold"),
                padx=8,
                pady=1,
            )
            self.badge_label.pack(side=tk.LEFT, padx=6)

            # 关闭与最小化小按钮
            close_btn = tk.Label(
                header,
                text="✕",
                bg=card_bg,
                fg=text_gray,
                font=("Segoe UI", 10, "bold"),
                cursor="hand2",
            )
            close_btn.pack(side=tk.RIGHT, padx=10)
            close_btn.bind("<Button-1>", lambda e: self.root.destroy())

            # 拖动事件绑定
            for w in [header, title_label]:
                w.bind("<Button-1>", self._start_drag)
                w.bind("<B1-Motion>", self._do_drag)

            # 2. 状态信息栏 (血量/能量/怪物信息)
            self.status_label = tk.Label(
                container,
                text="等待进入游戏画面...",
                bg=bg_color,
                fg=accent_gold,
                font=("Segoe UI", 9, "bold"),
                anchor="w",
                justify="left",
            )
            self.status_label.pack(fill=tk.X, padx=12, pady=(8, 4))

            # 3. 核心思考对话框 (Jev 心理想法)
            thought_frame = tk.Frame(container, bg=card_bg, padx=10, pady=8)
            thought_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

            self.thought_label = tk.Label(
                thought_frame,
                text="「Jev 智能决策系统已就绪，正在实时解析战斗数据...」",
                bg=card_bg,
                fg=text_white,
                font=("Microsoft YaHei", 9),
                wraplength=self.width - 45,
                justify="left",
                anchor="nw",
            )
            self.thought_label.pack(fill=tk.BOTH, expand=True)

            # 4. 当前操作指示栏 (底部)
            self.action_label = tk.Label(
                container,
                text="▶ 等待操作",
                bg=bg_color,
                fg=accent_cyan,
                font=("Consolas", 10, "bold"),
                anchor="w",
            )
            self.action_label.pack(fill=tk.X, padx=12, pady=(4, 8))

            # 启动事件轮询
            self._poll_queue()
            self.root.mainloop()
        except Exception as e:
            # 容错：若 GUI 初始化异常不影响无头运行
            pass

    def _start_drag(self, event):
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def _do_drag(self, event):
        if self.root:
            deltax = event.x - self._drag_start_x
            deltay = event.y - self._drag_start_y
            x = self.root.winfo_x() + deltax
            y = self.root.winfo_y() + deltay
            self.root.geometry(f"+{x}+{y}")

    def _poll_queue(self):
        if not self.root:
            return
        try:
            while True:
                data = self.msg_queue.get_nowait()
                badge = data.get("badge")
                status = data.get("status")
                thought = data.get("thought")
                action = data.get("action")

                if badge:
                    text, color = badge
                    self.badge_label.config(text=text, fg=color)
                if status is not None:
                    self.status_label.config(text=status)
                if thought is not None:
                    self.thought_label.config(text=thought)
                if action is not None:
                    self.action_label.config(text=action)
        except queue.Empty:
            pass
        except Exception:
            pass

        self.root.after(60, self._poll_queue)

    def say(
        self,
        thought: str,
        action: str = "",
        status: str = "",
        badge: str = "● 思考中",
        badge_color: str = "#00f0ff",
    ):
        """
        向悬浮窗推送消息
        """
        self.msg_queue.put(
            {
                "thought": thought,
                "action": action,
                "status": status,
                "badge": (badge, badge_color),
            }
        )


class DummyHud:
    """无头模式/测试模式下的空操作 HUD 代理"""

    def say(self, *args, **kwargs):
        pass
