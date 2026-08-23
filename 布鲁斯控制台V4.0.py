#====================== Mod by Maco =====================
import sys
import os
import time
import json
import random
import logging
import threading
import queue
import ctypes
import winreg
from ctypes import wintypes

# ===================== 依赖库预检查 =====================
REQUIRED_LIBS = {
    'pynput': 'pynput',
    'serial': 'pyserial',
    'psutil': 'psutil',
    'pystray': 'pystray',
    'PIL': 'Pillow'
}

def check_dependencies():
    missing = []
    for module_name, install_name in REQUIRED_LIBS.items():
        try:
            __import__(module_name)
        except ImportError:
            missing.append(install_name)
    if missing:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"{__import__('datetime').datetime.now()} - ERROR - [启动] 缺少必要的运行库: {', '.join(missing)}\n")
        except Exception:
            pass
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("环境缺失", f"缺少必要的运行库: {', '.join(missing)}\n\n请运行:\npip install {' '.join(missing)}")
        except:
            print(f"Missing: {missing}")
        sys.exit(1)

check_dependencies()

# ===================== 高 DPI =====================
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# ===================== EcoQoS 效率模式 =====================
# Windows 10 20H2+ (Build >= 19041) / Windows 11 支持
# 开启后进程以节能模式运行，降低电量消耗和CPU温度
# 任务管理器中会显示叶子图标 🍃

_PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
_PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
_ProcessPowerThrottling = 4  # PROCESS_INFORMATION_CLASS
_PROCESS_QUERY_INFORMATION = 0x0400
_PROCESS_SET_INFORMATION = 0x0200
_IDLE_PRIORITY_CLASS = 0x00000040
_NORMAL_PRIORITY_CLASS = 0x00000020

class _PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [
        ("Version", wintypes.ULONG),
        ("ControlMask", wintypes.ULONG),
        ("StateMask", wintypes.ULONG),
    ]

_eco_qos_checked = False
_eco_qos_supported = False
_eco_qos_active = False
_eco_qos_original_priority = _NORMAL_PRIORITY_CLASS
_eco_qos_kernel32 = None

def _open_process_handle():
    kernel32 = _eco_qos_kernel32 or ctypes.windll.kernel32
    pid = kernel32.GetCurrentProcessId()
    return kernel32.OpenProcess(
        _PROCESS_QUERY_INFORMATION | _PROCESS_SET_INFORMATION,
        False, pid
    )

def _detect_eco_qos():
    global _eco_qos_checked, _eco_qos_supported, _eco_qos_kernel32
    if _eco_qos_checked:
        return _eco_qos_supported
    _eco_qos_checked = True
    try:
        kernel32 = ctypes.windll.kernel32
        if not hasattr(kernel32, "SetProcessInformation"):
            _eco_qos_supported = False
            return False
        _eco_qos_kernel32 = kernel32
        # 必须使用 OpenProcess 获取真实句柄，GetCurrentProcess() 伪句柄不适用
        h_proc = _open_process_handle()
        if not h_proc:
            _eco_qos_supported = False
            return False
        try:
            # 尝试实际设置来验证
            state = _PROCESS_POWER_THROTTLING_STATE()
            state.Version = _PROCESS_POWER_THROTTLING_CURRENT_VERSION
            state.ControlMask = _PROCESS_POWER_THROTTLING_EXECUTION_SPEED
            state.StateMask = _PROCESS_POWER_THROTTLING_EXECUTION_SPEED
            result = kernel32.SetProcessInformation(
                h_proc, _ProcessPowerThrottling,
                ctypes.byref(state), ctypes.sizeof(state)
            )
            if result:
                # 验证成功，先关闭 EcoQoS，等待正式配置
                state.StateMask = 0
                kernel32.SetProcessInformation(
                    h_proc, _ProcessPowerThrottling,
                    ctypes.byref(state), ctypes.sizeof(state)
                )
                _eco_qos_supported = True
                return True
            else:
                _eco_qos_supported = False
                return False
        finally:
            kernel32.CloseHandle(h_proc)
    except Exception:
        _eco_qos_supported = False
        return False

def is_eco_qos_supported() -> bool:
    return _detect_eco_qos()

def is_eco_qos_active() -> bool:
    return _eco_qos_active

def set_eco_qos(enable: bool) -> bool:
    global _eco_qos_active, _eco_qos_original_priority
    if not _detect_eco_qos():
        return False
    try:
        h_proc = _open_process_handle()
        if not h_proc:
            return False
        try:
            kernel32 = _eco_qos_kernel32
            state = _PROCESS_POWER_THROTTLING_STATE()
            state.Version = _PROCESS_POWER_THROTTLING_CURRENT_VERSION
            state.ControlMask = _PROCESS_POWER_THROTTLING_EXECUTION_SPEED
            if enable:
                state.StateMask = _PROCESS_POWER_THROTTLING_EXECUTION_SPEED
            else:
                state.StateMask = 0
            
            result = kernel32.SetProcessInformation(
                h_proc, _ProcessPowerThrottling,
                ctypes.byref(state), ctypes.sizeof(state)
            )
            if not result:
                return False
            
            # 同时调整进程优先级（叶子图标的必要条件）
            if enable:
                # 记录当前优先级以便恢复
                _eco_qos_original_priority = kernel32.GetPriorityClass(h_proc) or _NORMAL_PRIORITY_CLASS
                kernel32.SetPriorityClass(h_proc, _IDLE_PRIORITY_CLASS)
            else:
                kernel32.SetPriorityClass(h_proc, _eco_qos_original_priority)
            
            _eco_qos_active = enable
            return True
        finally:
            kernel32.CloseHandle(h_proc)
    except Exception as e:
        try:
            logger.warning(f"EcoQoS 设置失败: {e}")
        except Exception:
            pass
        return False

# ===================== 正式导入 =====================
import tkinter as tk
from tkinter import ttk, messagebox
import serial
import serial.tools.list_ports
import psutil
from pynput.mouse import Listener, Button
from pynput.keyboard import Listener as KeyListener, Key, KeyCode

try:
    import pystray
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    pystray = None
    Image = None
    ImageDraw = None
    ImageTk = None

try:
    _LANCZOS = Image.Resampling.LANCZOS
except AttributeError:
    _LANCZOS = getattr(Image, "LANCZOS", None) if Image else None

# ===================== 路径 =====================
def get_base_dir():
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            return sys._MEIPASS
        else:
            return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

def get_data_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
DATA_DIR = get_data_dir()
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
ICON_FILE = os.path.join(BASE_DIR, "BLS.ico")
LOGO_FILE = os.path.join(BASE_DIR, "BLS.png")
LOG_FILE = os.path.join(DATA_DIR, "bruce_log.txt")
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5MB
CONFIG_VERSION = "4.0"

# 确保数据目录存在
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    pass


class ErrorPreservingRotatingFileHandler(logging.FileHandler):

    def __init__(self, filename, max_bytes=LOG_MAX_BYTES, encoding="utf-8"):
        self.max_bytes = max_bytes
        super().__init__(filename, mode="a", encoding=encoding, delay=False)

    def emit(self, record):
        try:
            if self.should_rollover():
                self.do_rollover()
            super().emit(record)
        except Exception:
            self.handleError(record)

    def should_rollover(self):
        if self.max_bytes <= 0:
            return False
        try:
            if self.stream is None:
                self.stream = self._open()
            self.stream.seek(0, os.SEEK_END)
            return self.stream.tell() >= self.max_bytes
        except Exception:
            return False

    def do_rollover(self):
        try:
            if self.stream:
                self.stream.close()
                self.stream = None
        except Exception:
            self.stream = None

        try:
            with open(self.baseFilename, "w", encoding="utf-8") as f:
                f.write("========== 日志已超过5MB，已清空重写 ==========\n")
        except Exception:
            pass

        self.stream = self._open()


def _setup_logging():
    log_fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.ERROR)
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)
    file_handler = ErrorPreservingRotatingFileHandler(LOG_FILE, max_bytes=LOG_MAX_BYTES)
    file_handler.setLevel(logging.ERROR)
    file_handler.setFormatter(log_fmt)
    root_logger.addHandler(file_handler)
    return logging.getLogger(__name__)


logger = _setup_logging()


def log_error(msg):
    logger.error(msg)
    try:
        if "root" in globals() and root.winfo_exists():
            root.after(0, lambda: messagebox.showerror("系统错误", msg))
    except Exception:
        pass

# ===================== 现代化配色 =====================
COLORS = {
    "bg":            "#0A0E1A",
    "bg_secondary":  "#0F1320",
    "card":          "#141B2D",
    "card_hover":    "#1B2440",
    "border":        "#1E293B",
    "border_light":  "#2A3650",
    "accent":        "#00D4FF",
    "accent_dim":    "#0891B2",
    "accent_glow":   "#00D4FF",
    "text":          "#E2E8F0",
    "text_dim":      "#94A3B8",
    "text_muted":    "#64748B",
    "success":       "#10B981",
    "warning":       "#FBBF24",
    "danger":        "#EF4444",
    "btn":           "#1E293B",
    "btn_hover":     "#334155",
    "toggle_on":     "#10B981",
    "toggle_off":    "#334155",
    "toggle_knob":   "#FFFFFF",
    "toggle_knob_off":"#94A3B8",
}

# ===================== 字体常量（预定义避免重复创建） =====================
FONT_TITLE = ("思源真黑体", 15, "bold")
FONT_SUBTITLE = ("思源真黑体", 12, "bold")
FONT_NORMAL = ("思源真黑体", 10)
FONT_SMALL = ("思源真黑体", 8)
FONT_BTN = ("思源真黑体", 10)
FONT_BTN_BOLD = ("思源真黑体", 12, "bold")
FONT_CODE = ("Consolas", 9, "bold")
FONT_CODE_NORMAL = ("Consolas", 10)
FONT_STATUS_DOT = ("思源真黑体", 7)

# ===================== 默认按键 =====================
DEFAULT_KEYBINDS = {
    "expression": "tab",
    "neck_left": "left",
    "neck_right": "right",
    "mouth_up": "up",
    "mouth_down": "down",
    "heart": "`",
    "space": "space",
    "backspace": "backspace",
    "enter": "enter",
    "blink": "mouse_left",    # a - 眨眼（默认鼠标左键）
    "toggle_mouth": "f2",
    "toggle_keyboard_mouth": "f3",
    "toggle_neck": "f4",
    "toggle_eye_input": "f5",
    "toggle_service": "f6",
    # ---- 新增表情快捷键（默认不绑定，用户可在自定义中设置） ----
    "expr_sleepy": "",        # d - 昏睡
    "expr_question": "",      # e - 问号
    "expr_heart_beat": "",    # g - 跳动爱心
    "expr_squint": "",        # h - 眯眼
    "expr_exclamation": "",   # i - 感叹号
    "expr_dizziness": "",     # j - 普通眩晕
    "expr_mosquito": "",      # m - 蚊香眩晕
    "neck_reset": "",         # n - 脖子回正
}

KEY_DISPLAY_NAMES = {
    "tab": "Tab", "left": "← 左", "right": "→ 右", "up": "↑ 上", "down": "↓ 下",
    "space": "空格", "backspace": "退格", "enter": "回车", "`": "` 波浪",
    "shift": "Shift", "ctrl": "Ctrl", "alt": "Alt", "esc": "Esc",
    "f1": "F1", "f2": "F2", "f3": "F3", "f4": "F4", "f5": "F5", "f6": "F6",
    "f7": "F7", "f8": "F8", "f9": "F9", "f10": "F10", "f11": "F11", "f12": "F12",
    "home": "Home", "end": "End", "delete": "Delete", "page_up": "PageUp", "page_down": "PageDown",
    "caps_lock": "CapsLock", "insert": "Insert", "print_screen": "PrtSc",
}

MODIFIER_KEYS = {"shift", "ctrl", "alt"}
# 组合键中修饰键的固定顺序，保证 "ctrl+shift+up" 与按下顺序无关
MODIFIER_ORDER = ("ctrl", "alt", "shift")

# ===================== Raw Input 键盘监听 =====================
WM_INPUT = 0x00FF
RIM_TYPEKEYBOARD = 1
RIDEV_INPUTSINK = 0x00000100
RID_INPUT = 0x10000003
HID_USAGE_PAGE_GENERIC = 0x0001
HID_USAGE_GENERIC_KEYBOARD = 0x0006
WM_RAW_KEYDOWN = 0x0100
WM_RAW_SYSKEYDOWN = 0x0104
WM_RAW_KEYUP = 0x0101
WM_RAW_SYSKEYUP = 0x0105

_VK_TO_KEYNAME = {
    0x08: "backspace", 0x09: "tab", 0x0D: "enter", 0x1B: "esc", 0x20: "space",
    0x21: "page_up", 0x22: "page_down", 0x23: "end", 0x24: "home",
    0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down",
    0x2C: "print_screen", 0x2D: "insert", 0x2E: "delete", 0x14: "caps_lock",
    0x70: "f1", 0x71: "f2", 0x72: "f3", 0x73: "f4", 0x74: "f5",
    0x75: "f6", 0x76: "f7", 0x77: "f8", 0x78: "f9", 0x79: "f10",
    0x7A: "f11", 0x7B: "f12",
}

class _RawKey:
    """Raw Input 按键对象，兼容 key_to_str() 和 on_press() 逻辑。"""
    __slots__ = ('char', 'name', 'vk')
    def __init__(self, char=None, name=None, vk=None):
        self.char = char
        self.name = name
        self.vk = vk

_kb_layout_cache = None

def _vk_to_rawkey(vk, scan_code=0):
    """将虚拟键码转换为 _RawKey 对象。"""
    if vk in (0x10, 0xA0, 0xA1):
        return _RawKey(name="shift", vk=vk)
    if vk in (0x11, 0xA2, 0xA3):
        return _RawKey(name="ctrl", vk=vk)
    if vk in (0x12, 0xA4, 0xA5):
        return _RawKey(name="alt", vk=vk)
    if vk in _VK_TO_KEYNAME:
        return _RawKey(name=_VK_TO_KEYNAME[vk], vk=vk)
    if vk in _NUMPAD_VK:
        numlock = user32.GetKeyState(0x90)
        if numlock & 1:
            return _RawKey(char=_NUMPAD_VK[vk], vk=vk)
    if 0x41 <= vk <= 0x5A:
        shift = bool(user32.GetAsyncKeyState(0x10) & 0x8000)
        caps = bool(user32.GetKeyState(0x14) & 1)
        if shift != caps:
            return _RawKey(char=chr(vk), vk=vk)
        return _RawKey(char=chr(vk + 32), vk=vk)
    if 0x30 <= vk <= 0x39:
        shift = bool(user32.GetAsyncKeyState(0x10) & 0x8000)
        if not shift:
            return _RawKey(char=chr(vk), vk=vk)
        # Shift 按下时交给 ToUnicodeEx 处理以获取符号（!@#$%^&*()）
    global _kb_layout_cache
    if _kb_layout_cache is None:
        _kb_layout_cache = user32.GetKeyboardLayout(0)
    user32.ToUnicodeEx.argtypes = [
        ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_ubyte),
        ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p,
    ]
    user32.ToUnicodeEx.restype = ctypes.c_int
    kb_state = (ctypes.c_ubyte * 256)()
    user32.GetKeyboardState(kb_state)
    buf = (ctypes.c_wchar * 8)()
    result = user32.ToUnicodeEx(vk, scan_code, kb_state, buf, 8, 0, _kb_layout_cache)
    if result > 0:
        return _RawKey(char=buf[0], vk=vk)
    return _RawKey(vk=vk)

# 鼠标按键显示名称
MOUSE_DISPLAY_NAMES = {
    "mouse_left": "鼠标左键",
    "mouse_right": "鼠标右键",
    "mouse_middle": "鼠标中键",
    "mouse_wheel_up": "滚轮 ↑",
    "mouse_wheel_down": "滚轮 ↓",
    "mouse_x1": "侧键1",
    "mouse_x2": "侧键2",
}

# 新增表情按键的可绑定动作集合
EXPR_KEYBIND_ACTIONS = {
    "expr_sleepy", "expr_question", "expr_heart_beat", "expr_squint",
    "expr_exclamation", "expr_dizziness", "expr_mosquito", "neck_reset",
}

# 表情动作 → 串口指令映射
EXPR_ACTION_COMMANDS = {
    "expr_sleepy": b"d\n",
    "expr_question": b"e\n",
    "expr_heart_beat": b"g\n",
    "expr_squint": b"h\n",
    "expr_exclamation": b"i\n",
    "expr_dizziness": b"j\n",
    "expr_mosquito": b"m\n",
    "neck_reset": b"n\n",
}

# 需要触发后3秒自动恢复的表情动作（脖子回正除外）
EXPR_RESTORE_ACTIONS = {
    "expr_sleepy", "expr_question", "expr_heart_beat", "expr_squint",
    "expr_exclamation", "expr_dizziness", "expr_mosquito",
}

def mouse_button_to_str(button):
    """将 pynput 鼠标 Button 枚举转为字符串标识"""
    try:
        name = button.name.lower()
        if name == "left":
            return "mouse_left"
        elif name == "right":
            return "mouse_right"
        elif name == "middle":
            return "mouse_middle"
        elif name in ("x1", "button4"):
            return "mouse_x1"
        elif name in ("x2", "button5"):
            return "mouse_x2"
        else:
            return f"mouse_{name}"
    except Exception:
        return None

def get_action_command(action, neck_active=False, mouth_active=False):
    if action in EXPR_ACTION_COMMANDS:
        return EXPR_ACTION_COMMANDS[action]
    if action == "heart":
        return b"z\n"
    if action == "expression":
        return b"b\n"
    if action == "blink":
        return b"a\n"
    if action == "neck_left" and neck_active:
        return b"k\n"
    if action == "neck_right" and neck_active:
        return b"l\n"
    if action == "mouth_up" and mouth_active:
        return b"c\n"
    if action == "mouth_down" and mouth_active:
        return b"f\n"
    if action == "space":
        return b"y\n"
    if action == "backspace":
        return b"w\n"
    if action == "enter":
        return b"x\n"
    return None

def get_key_display(key_str):
    if not key_str:
        return ""
    if key_str.startswith("mouse_"):
        return MOUSE_DISPLAY_NAMES.get(key_str, key_str)
    if "+" in key_str:
        parts = key_str.split("+")
        return " + ".join(get_key_display(p) for p in parts)
    if key_str.startswith("f") and key_str[1:].isdigit():
        return key_str.upper()
    return KEY_DISPLAY_NAMES.get(key_str, key_str.upper() if len(key_str) == 1 else key_str)

# Windows 小键盘虚拟键码 → 数字字符
_NUMPAD_VK = {
    0x60: "0", 0x61: "1", 0x62: "2", 0x63: "3", 0x64: "4",
    0x65: "5", 0x66: "6", 0x67: "7", 0x68: "8", 0x69: "9",
}
_NUMPAD_NAME_MAP = {
    "num_0": "0", "num_1": "1", "num_2": "2", "num_3": "3", "num_4": "4",
    "num_5": "5", "num_6": "6", "num_7": "7", "num_8": "8", "num_9": "9",
    "num0": "0", "num1": "1", "num2": "2", "num3": "3", "num4": "4",
    "num5": "5", "num6": "6", "num7": "7", "num8": "8", "num9": "9",
    "vk_numpad0": "0", "vk_numpad1": "1", "vk_numpad2": "2", "vk_numpad3": "3",
    "vk_numpad4": "4", "vk_numpad5": "5", "vk_numpad6": "6", "vk_numpad7": "7",
    "vk_numpad8": "8", "vk_numpad9": "9",
}

_KEY_ENUM_MAP = {
    Key.tab: "tab", Key.left: "left", Key.right: "right", Key.up: "up",
    Key.down: "down", Key.space: "space", Key.backspace: "backspace",
    Key.enter: "enter", Key.esc: "esc",
    Key.shift: "shift", Key.shift_l: "shift", Key.shift_r: "shift",
    Key.ctrl: "ctrl", Key.ctrl_l: "ctrl", Key.ctrl_r: "ctrl",
    Key.alt: "alt", Key.alt_l: "alt", Key.alt_r: "alt",
}

def key_to_str(key):
    try:
        # Raw Input 按键对象
        if isinstance(key, _RawKey):
            if key.name:
                return key.name
            if key.vk and key.vk in _NUMPAD_VK:
                return _NUMPAD_VK[key.vk]
            if key.char:
                ch = key.char
                if ch.isalpha():
                    return ch.lower()
                if ch in "0123456789":
                    return ch
                return ch.lower() if ch else None
            return None

        mapped = _KEY_ENUM_MAP.get(key)
        if mapped:
            return mapped

        # 小键盘数字：优先用虚拟键码识别（NumLock 开/关都尽量能识别数字键）
        if isinstance(key, KeyCode):
            vk = getattr(key, "vk", None)
            if vk is not None and vk in _NUMPAD_VK:
                return _NUMPAD_VK[vk]
            if key.char:
                ch = key.char
                if ch.isalpha():
                    return ch.lower()
                if ch in "0123456789":
                    return ch
                return ch.lower() if ch else None

        if hasattr(key, "name") and key.name:
            name = key.name.lower()
            if name in ("shift_l", "shift_r"): return "shift"
            if name in ("ctrl_l", "ctrl_r"): return "ctrl"
            if name in ("alt_l", "alt_r", "alt_gr"): return "alt"
            if name in _NUMPAD_NAME_MAP:
                return _NUMPAD_NAME_MAP[name]
            return name
    except Exception:
        pass
    return None

def is_alnum_interact_key(key_str):
    return bool(key_str) and len(key_str) == 1 and key_str in "abcdefghijklmnopqrstuvwxyz0123456789"

def build_combo_str(main_key, modifiers=None):
    if modifiers is None:
        with state.lock:
            modifiers = set(state.pressed_modifiers)
    mods = [m for m in MODIFIER_ORDER if m in modifiers]
    if main_key in MODIFIER_KEYS:
        others = [m for m in mods if m != main_key]
        if others:
            return "+".join(others + [main_key])
        return main_key
    if mods:
        return "+".join(mods + [main_key])
    return main_key

# ===================== 默认参数 =====================
DEFAULT_PORT = ""
DEFAULT_RESOLUTION = ""
DEFAULT_MOUTH_ACTIVE = False
DEFAULT_KEYBOARD_MOUTH_ACTIVE = False  # 字母/数字键触发嘴巴开合
DEFAULT_NECK_ACTIVE = False
DEFAULT_AUTO_START = False
DEFAULT_AUTO_INTERACT = True
DEFAULT_AUTO_CENTER_EYES = True
DEFAULT_EYE_INPUT_DISPLAY = True
TARGET_X_START, TARGET_X_END = 6, 0
TARGET_Y_MIN, TARGET_Y_MAX = 0, 4
BAUDRATE = 115200
MOUSE_MOVE_INTERVAL = 0.02
KEY_THROTTLE_MS = 30
RANDOM_MOUTH_DECAY = 0.15
HARDWARE_POLL_INTERVAL = 3.0
HARDWARE_THRESHOLD = 90
KEY_BUFFER_TIMEOUT = 1.0

# ===================== 多屏幕检测（Win10 兼容加强） =====================
user32 = ctypes.windll.user32
try:
    user32.SetProcessDPIAware()
except Exception:
    pass

#WIN10
_HMONITOR = getattr(wintypes, "HMONITOR", ctypes.c_void_p)
_HDC = getattr(wintypes, "HDC", ctypes.c_void_p)

class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]

class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]

class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]

# in10
_MonitorEnumProcType = ctypes.WINFUNCTYPE(
    ctypes.c_int,       # BOOL return
    _HMONITOR,          # hMonitor
    _HDC,               # hdcMonitor
    ctypes.POINTER(wintypes.RECT),  # lprcMonitor
    wintypes.LPARAM,    # dwData
)

def _monitors_via_enum_display_monitors():
    monitors = []

    def _callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
        try:
            # WIN10
            if lprcMonitor:
                r = lprcMonitor.contents
                x, y = int(r.left), int(r.top)
                w, h = int(r.right - r.left), int(r.bottom - r.top)
            else:
                x = y = w = h = 0

            is_primary = False
            try:
                mi = MONITORINFO()
                mi.cbSize = ctypes.sizeof(MONITORINFO)
                if user32.GetMonitorInfoW(hMonitor, ctypes.byref(mi)):
                    is_primary = bool(mi.dwFlags & 1)
                    if w <= 0 or h <= 0:
                        x = int(mi.rcMonitor.left)
                        y = int(mi.rcMonitor.top)
                        w = int(mi.rcMonitor.right - mi.rcMonitor.left)
                        h = int(mi.rcMonitor.bottom - mi.rcMonitor.top)
            except Exception:
                pass

            if w > 0 and h > 0:
                monitors.append({
                    "x": x, "y": y, "width": w, "height": h,
                    "is_primary": is_primary,
                })
        except Exception as e:
            try:
                logger.warning(f"EnumDisplayMonitors 回调异常: {e}")
            except Exception:
                pass
        return 1  # TRUE，继续枚举

    try:
        cfunc = _MonitorEnumProcType(_callback)
        user32.EnumDisplayMonitors(None, None, cfunc, 0)
    except Exception as e:
        try:
            logger.warning(f"EnumDisplayMonitors 失败: {e}")
        except Exception:
            pass
    return monitors

def _monitors_via_enum_display_devices():
    monitors = []
    try:
        i = 0
        while True:
            dd = DISPLAY_DEVICEW()
            dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
            if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
                break
            if dd.StateFlags & 0x1:
                mode = wintypes.DEVMODEW() if hasattr(wintypes, "DEVMODEW") else None
                # 使用简化 DEVMODE
                class DEVMODEW(ctypes.Structure):
                    _fields_ = [
                        ("dmDeviceName", wintypes.WCHAR * 32),
                        ("dmSpecVersion", wintypes.WORD),
                        ("dmDriverVersion", wintypes.WORD),
                        ("dmSize", wintypes.WORD),
                        ("dmDriverExtra", wintypes.WORD),
                        ("dmFields", wintypes.DWORD),
                        ("dmPosition_x", ctypes.c_long),
                        ("dmPosition_y", ctypes.c_long),
                        ("dmDisplayOrientation", wintypes.DWORD),
                        ("dmDisplayFixedOutput", wintypes.DWORD),
                        ("dmColor", wintypes.SHORT),
                        ("dmDuplex", wintypes.SHORT),
                        ("dmYResolution", wintypes.SHORT),
                        ("dmTTOption", wintypes.SHORT),
                        ("dmCollate", wintypes.SHORT),
                        ("dmFormName", wintypes.WCHAR * 32),
                        ("dmLogPixels", wintypes.WORD),
                        ("dmBitsPerPel", wintypes.DWORD),
                        ("dmPelsWidth", wintypes.DWORD),
                        ("dmPelsHeight", wintypes.DWORD),
                        ("dmDisplayFlags", wintypes.DWORD),
                        ("dmDisplayFrequency", wintypes.DWORD),
                    ]
                dm = DEVMODEW()
                dm.dmSize = ctypes.sizeof(DEVMODEW)
                # ENUM_CURRENT_SETTINGS = -1
                if user32.EnumDisplaySettingsW(dd.DeviceName, -1, ctypes.byref(dm)):
                    is_primary = bool(dd.StateFlags & 0x4)  # DISPLAY_DEVICE_PRIMARY_DEVICE
                    monitors.append({
                        "x": int(dm.dmPosition_x),
                        "y": int(dm.dmPosition_y),
                        "width": int(dm.dmPelsWidth),
                        "height": int(dm.dmPelsHeight),
                        "is_primary": is_primary,
                    })
            i += 1
            if i > 16:
                break
    except Exception as e:
        try:
            logger.warning(f"EnumDisplayDevices 失败: {e}")
        except Exception:
            pass
    return monitors

def _monitors_via_system_metrics():
    try:
        # SM_CMONITORS = 80
        count = user32.GetSystemMetrics(80)
        ox = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
        oy = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
        vw = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
        vh = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
        pw = user32.GetSystemMetrics(0)
        ph = user32.GetSystemMetrics(1)
        monitors = [{
            "x": 0, "y": 0, "width": pw, "height": ph, "is_primary": True
        }]
        if count > 1 or vw > pw or vh > ph:
            if vw > 0 and vh > 0 and (vw != pw or vh != ph or ox != 0 or oy != 0):
                return [{
                    "x": ox, "y": oy, "width": vw, "height": vh, "is_primary": True
                }]
        return monitors
    except Exception:
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        return [{"x": 0, "y": 0, "width": w, "height": h, "is_primary": True}]

def _dedupe_monitors(monitors):
    seen = set()
    result = []
    for m in monitors:
        key = (m["x"], m["y"], m["width"], m["height"])
        if key in seen:
            continue
        seen.add(key)
        result.append(m)
    if result and not any(m.get("is_primary") for m in result):
        for m in result:
            if m["x"] == 0 and m["y"] == 0:
                m["is_primary"] = True
                break
        else:
            result[0]["is_primary"] = True
    return result

def get_all_monitors():
    monitors = _monitors_via_enum_display_monitors()
    if len(monitors) <= 1:
        alt = _monitors_via_enum_display_devices()
        if len(alt) > len(monitors):
            monitors = alt
    if not monitors:
        monitors = _monitors_via_system_metrics()
    monitors = _dedupe_monitors(monitors)

    try:
        ox = user32.GetSystemMetrics(76)
        oy = user32.GetSystemMetrics(77)
        vw = user32.GetSystemMetrics(78)
        vh = user32.GetSystemMetrics(79)
        if monitors and vw > 0 and vh > 0:
            min_x = min(m["x"] for m in monitors)
            min_y = min(m["y"] for m in monitors)
            max_x = max(m["x"] + m["width"] for m in monitors)
            max_y = max(m["y"] + m["height"] for m in monitors)
            if vw > (max_x - min_x) + 50 or vh > (max_y - min_y) + 50:
                pass
    except Exception:
        pass
    return monitors

def get_virtual_screen_bounds(monitors=None):
    if monitors is None:
        monitors = get_all_monitors()

    # SystemMetrics 虚拟桌面
    try:
        sx = user32.GetSystemMetrics(76)
        sy = user32.GetSystemMetrics(77)
        sw = user32.GetSystemMetrics(78)
        sh = user32.GetSystemMetrics(79)
    except Exception:
        sx = sy = 0
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)

    if not monitors:
        return sx, sy, sw, sh

    min_x = min(m["x"] for m in monitors)
    min_y = min(m["y"] for m in monitors)
    max_x = max(m["x"] + m["width"] for m in monitors)
    max_y = max(m["y"] + m["height"] for m in monitors)
    ew, eh = max_x - min_x, max_y - min_y

    if sw >= ew and sh >= eh:
        return sx, sy, sw, sh
    return min_x, min_y, ew, eh

def get_virtual_screen_size():
    _, _, w, h = get_virtual_screen_bounds()
    return w, h

def get_virtual_screen_origin():
    ox, oy, _, _ = get_virtual_screen_bounds()
    return ox, oy

def get_primary_resolution():
    monitors = get_all_monitors()
    for m in monitors:
        if m["is_primary"]:
            return m["width"], m["height"]
    if monitors:
        return monitors[0]["width"], monitors[0]["height"]
    width = user32.GetSystemMetrics(0)
    height = user32.GetSystemMetrics(1)
    return width, height

def log_monitors_info():
    # SM_CMONITORS
    try:
        sm_count = user32.GetSystemMetrics(80)
        sx = user32.GetSystemMetrics(76)
        sy = user32.GetSystemMetrics(77)
        sw = user32.GetSystemMetrics(78)
        sh = user32.GetSystemMetrics(79)
        logger.error(f"[分辨率] SystemMetrics: CMONITORS={sm_count}, 虚拟桌面 origin=({sx},{sy}) size={sw}x{sh}")
    except Exception as e:
        logger.error(f"[分辨率] 读取 SystemMetrics 失败: {e}")

    monitors = get_all_monitors()
    logger.error(f"[分辨率] 枚举到 {len(monitors)} 块屏幕:")
    for i, m in enumerate(monitors):
        tag = " [主]" if m["is_primary"] else ""
        logger.error(f"[分辨率]   屏幕{i+1}{tag}: pos=({m['x']},{m['y']}) size={m['width']}x{m['height']}")
    ox, oy, vw, vh = get_virtual_screen_bounds(monitors)
    logger.error(f"[分辨率]   最终虚拟桌面: origin=({ox},{oy}) size={vw}x{vh}")
    return monitors

def is_multi_monitor(monitors=None):
    if monitors is None:
        monitors = get_all_monitors()
    if len(monitors) > 1:
        return True
    try:
        if user32.GetSystemMetrics(80) > 1:  # SM_CMONITORS
            return True
        pw = user32.GetSystemMetrics(0)
        ph = user32.GetSystemMetrics(1)
        vw = user32.GetSystemMetrics(78)
        vh = user32.GetSystemMetrics(79)
        if vw > pw + 16 or vh > ph + 16:
            return True
    except Exception:
        pass
    if monitors:
        primary = next((m for m in monitors if m.get("is_primary")), monitors[0])
        ox, oy, vw, vh = get_virtual_screen_bounds(monitors)
        if vw > primary["width"] + 16 or vh > primary["height"] + 16:
            return True
    return False

# ===================== 配置管理 =====================
class ConfigManager:
    @staticmethod
    def load():
        defaults = {
            "port": DEFAULT_PORT, "resolution": DEFAULT_RESOLUTION,
            "origin_x": 0, "origin_y": 0,
            "mouth_active": DEFAULT_MOUTH_ACTIVE,
            "keyboard_mouth_active": DEFAULT_KEYBOARD_MOUTH_ACTIVE,
            "neck_active": DEFAULT_NECK_ACTIVE,
            "eye_input_display_active": DEFAULT_EYE_INPUT_DISPLAY,
            "auto_start": DEFAULT_AUTO_START, "auto_interact": DEFAULT_AUTO_INTERACT,
            "auto_center_eyes": DEFAULT_AUTO_CENTER_EYES,
            "dlc_enabled": False,
            "expr_auto_restore": True,
            "eco_qos_enabled": True,
            "close_action_remember": False,
            "close_action": "ask",
            "keybinds": DEFAULT_KEYBINDS.copy(),
            "custom_blocking_processes": [],
            "disabled_builtin_processes": [],
            "config_version": CONFIG_VERSION
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                stored_version = data.get("config_version", "")
                if stored_version != CONFIG_VERSION:
                    # 版本升级：保留用户已有设置，仅补充新增字段
                    for k in defaults:
                        if k not in data:
                            data[k] = defaults[k]
                    if "keybinds" not in data or not isinstance(data["keybinds"], dict):
                        data["keybinds"] = DEFAULT_KEYBINDS.copy()
                    else:
                        for k, v in DEFAULT_KEYBINDS.items():
                            if k not in data["keybinds"]:
                                data["keybinds"][k] = v
                    data["config_version"] = CONFIG_VERSION
                    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    logger.error(f"[启动] 配置文件从v{stored_version}升级到v{CONFIG_VERSION}，已保留原设置")
                    return data
                for k in defaults:
                    if k not in data:
                        data[k] = defaults[k]
                if "keybinds" not in data or not isinstance(data["keybinds"], dict):
                    data["keybinds"] = DEFAULT_KEYBINDS.copy()
                else:
                    for k, v in DEFAULT_KEYBINDS.items():
                        if k not in data["keybinds"]:
                            data["keybinds"][k] = v
                return data
            except Exception as e:
                log_error(f"加载配置失败: {e}")
                return defaults
        else:
            try:
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(defaults, f, ensure_ascii=False, indent=2)
            except Exception as e:
                log_error(f"创建配置文件失败: {e}")
            return defaults

    @staticmethod
    def save(config: dict):
        temp_file = CONFIG_FILE + ".tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())  # 确保写入磁盘
            os.replace(temp_file, CONFIG_FILE)  # 原子替换
        except Exception as e:
            log_error(f"保存配置失败: {e}")
            # 清理可能残留的临时文件
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass

    @staticmethod
    def set_auto_start(enabled: bool):
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "BruceConsole"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            if enabled:
                exe = sys.executable
                if getattr(sys, 'frozen', False):
                    cmd = f'"{exe}"'
                else:
                    script = os.path.abspath(__file__)
                    python_exe = sys.executable.replace('python.exe', 'pythonw.exe') if 'python.exe' in sys.executable else sys.executable
                    cmd = f'"{python_exe}" "{script}"'
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            log_error(f"设置开机自启失败: {e}")


# ===================== 配置保存防抖 =====================
# 避免用户快速点击开关导致频繁磁盘 I/O
_save_debounce_timer = None
_save_debounce_lock = threading.Lock()

def schedule_config_save(delay=0.5):
    global _save_debounce_timer
    with _save_debounce_lock:
        if _save_debounce_timer is not None:
            _save_debounce_timer.cancel()
        _save_debounce_timer = threading.Timer(delay, _do_debounced_save)
        _save_debounce_timer.daemon = True
        _save_debounce_timer.start()

def _do_debounced_save():
    global _save_debounce_timer
    with _save_debounce_lock:
        _save_debounce_timer = None
    try:
        ConfigManager.save(config_data)
    except Exception as e:
        log_error(f"防抖保存配置失败: {e}")

def flush_config_save():
    global _save_debounce_timer
    with _save_debounce_lock:
        if _save_debounce_timer is not None:
            _save_debounce_timer.cancel()
            _save_debounce_timer = None
    try:
        ConfigManager.save(config_data)
    except Exception as e:
        log_error(f"强制保存配置失败: {e}")

# ===================== 硬件 & 输入 =====================
class HardwareMonitor:
    def check_overload(self):
        try:
            return psutil.cpu_percent(interval=0.1) > HARDWARE_THRESHOLD
        except Exception:
            return False

class InputThrottler:
    def __init__(self, min_interval_ms=30):
        self.min_interval = min_interval_ms / 1000.0
        self.last_time = 0.0
        self._lock = threading.Lock()

    def allow(self):
        with self._lock:
            now = time.time()
            if now - self.last_time < self.min_interval:
                return False
            self.last_time = now
            return True

class MouthSimulator:
    def __init__(self, send_func):
        self._send = send_func
        self._lock = threading.Lock()
        self._last = 0.0

    def trigger(self):
        with self._lock:
            now = time.time()
            if now - self._last < RANDOM_MOUTH_DECAY:
                return
            self._last = now
            self._send(random.choice([b"c\n", b"f\n"]))

# ===================== 全局状态 =====================
class AppState:
    def __init__(self):
        self.lock = threading.RLock()
        self.ser = None
        self.service_active = False
        self.interaction_enabled = False
        self.hardware_overloaded = False
        self.last_map_x = self.last_map_y = -1
        self.last_move_time = 0.0
        self.last_input_signal_time = 0.0
        self.last_keyboard_event_time = 0.0
        self.is_centered_state = False
        self.last_cursor_x = None
        self.last_cursor_y = None
        self.CURSOR_MOVE_THRESHOLD = 3  
        self.last_sys_cursor_x = None   # 后台线程用：上次系统API返回的坐标
        self.last_sys_cursor_y = None   # 用于鼠标静止时跳过重复计算
        self.mouth_active = False
        self.keyboard_mouth_active = False
        self.neck_active = False
        self.eye_input_display_active = True
        self.auto_center_eyes = True
        self.dlc_enabled = False             # 附加DLC功能开关（默认关闭）
        self.expr_auto_restore = True        # DLC表情自动恢复开关（3秒后发送b恢复表情，默认开启）
        self.key_buffer = ""
        self.ORIGIN_X_MIN = self.ORIGIN_X_MAX = 0
        self.ORIGIN_Y_MIN = self.ORIGIN_Y_MAX = 0
        self.origin_x = 0
        self.origin_y = 0
        self.monitors = []  # 各屏幕信息列表，用于按鼠标所在屏幕动态切换映射范围
        self.keybinds = DEFAULT_KEYBINDS.copy()
        self.binding_mode = False
        self.binding_callback = None
        self.pressed_modifiers = set()
        # ---- 表情触发状态 ----
        self.expr_buffer = ""              # 表情模式检测缓冲区
        self.momo_step = 0                 # momo 链当前步骤: 0=空闲, 1=已触发眯眼, 2=已触发感叹号
        self.momo_flow_active = False      # momo 流程进行中（锁定其他键位互动）
        self.momo_last_time = 0.0          # momo 上次触发时间
        # ---- ZZ/momo 缓冲（延迟显示，0.5s内匹配则触发，超时则显示文字）----
        self.zz_pending = False            # True=第一个z已缓冲等待第二个z
        self.zz_flush_timer = None         # z 超时显示定时器
        self.momo_pending_buffer = ""      # 缓冲中的 m/o 字符
        self.momo_flush_timer = None       # m/o 超时显示定时器

state = AppState()
input_throttler = InputThrottler(KEY_THROTTLE_MS)
mouth_simulator = None
hw_monitor = HardwareMonitor()
tray_icon = None
config_data = {}
mouse_listener = None
key_listener = None

# ---- 表情触发定时器 ----
_momo_timer = None
_expr_restore_timers = {}
_expr_timer_lock = threading.Lock()

MONITOR_PROCESSES = [
    # FPS
    "valorant.exe", "valorant-win64-shipping.exe",
    "cs2.exe", "csgo.exe",
    "overwatch.exe", "overwatch2.exe",
    "r5apex.exe", "apex_legends.exe",
    "pubg.exe", "tslgame.exe",
    "cod.exe", "cod22.exe", "cod23.exe", "cod24.exe",
    "modernwarfare.exe", "modernwarfare2.exe", "modernwarfare3.exe",
    "bf2042.exe", "bf1.exe", "bfv.exe", "battlefield.exe",
    "rainbowsix.exe", "rainbowsix_vulkan.exe", "rainbowsix_dx11.exe",
    "fortniteclient-win64-shipping.exe", "fortniteclient-win64-shipping_be.exe",
    "huntgame.exe", "thefinals.exe", "deltaforceclient-win64-shipping.exe",
    # MOBA / 其它竞技
    "league of legends.exe", "leagueclient.exe", "leagueclientux.exe", "lolclient.exe",
    "dota2.exe", "hon.exe",
    "heroes of the storm.exe",
    # 射击 / 生存
    "destiny2.exe", "warframe.exe", "warthunder.exe",
    "escape from tarkov.exe", "eft.exe", "battlestategames.exe",
    "huntshowdown.exe", "deadbydaylight-win64-shipping.exe",
    "left4dead2.exe", "gmod.exe",
    # 主机级 / 3A
    "gta5.exe", "gtav.exe", "rdr2.exe", "playgtav.exe",
    "cyberpunk2077.exe", "eldenring.exe", "sekiro.exe",
    "ffxiv_dx11.exe", "ffxiv.exe",
    "wow.exe", "wowclassic.exe",
    "starrail.exe", "genshinimpact.exe", "yuanmeng.exe", "zenlesszonezero.exe",
    "lostark.exe", "blackdesert64.exe", "maplestory.exe",
    # 其它常见
    "rocketleague.exe", "sc2_x64.exe", "hearthstone.exe",
    "crossfire.exe", "crossfire_x64.exe",
    "narakabladepoint.exe", "naraka.exe",
    "worldoftanks.exe", "worldofwarships.exe", "wotblitz.exe",
    "osu!.exe", "robloxplayerbeta.exe",
    "minecraft.exe", "minecraftlauncher.exe",
]

# 反作弊 / 安全中心进程（出现即停止监听）
ANTI_CHEAT_PROCESSES = [
    # Riot Vanguard
    "vgtray.exe", "vgc.exe", "vanguard.exe",
    # Easy Anti-Cheat
    "easyanticheat.exe", "easyanticheat_eos.exe", "eac_launcher.exe",
    # BattlEye
    "beservice.exe", "beservices.exe", "beclient_x64.exe", "beclient.exe",
    "battleye.exe",
    # FACEIT / ESEA
    "faceit.exe", "faceitclient.exe", "faceitservice.exe", "faceitac.exe",
    "esea_client_anti_cheat.exe", "esea_driver.exe",
    # 其它常见
    "xigncode.exe", "xsc.exe", "xnina.v64.exe",
    "gameguard.exe", "npggnt.des", "nprotect.exe",
    "punkbuster.exe", "pbsvc.exe", "pbclient.exe",
    "ricochet.exe", "codricochet.exe",
    "mhyprot2.exe", "mhyprot3.exe", "ace-service.exe", "ace-tray.exe",
     "tenio_service.exe",
    "vac.exe",  # 少见独立进程名
    "sguard64.exe", "sguard.exe",  # 腾讯 ACE / 安全组件常见名
    "tphelper.exe", "tpclient.exe", "tpmaster.exe",  # 腾讯 TP
    "tenproxy.exe",
]

_BLOCKING_TARGETS = frozenset(
    p.lower() for p in MONITOR_PROCESSES + ANTI_CHEAT_PROCESSES
)

def get_blocking_targets():
    """返回当前所有拦截进程名集合（内置 - 已禁用 + 用户自定义）。"""
    disabled = config_data.get("disabled_builtin_processes", [])
    if not isinstance(disabled, list):
        disabled = []
    disabled_set = frozenset(p.lower().strip() for p in disabled if p.strip())
    custom = config_data.get("custom_blocking_processes", [])
    if not isinstance(custom, list):
        custom = []
    custom_set = frozenset(p.lower().strip() for p in custom if p.strip())
    return (_BLOCKING_TARGETS - disabled_set) | custom_set

# ===================== 串口异步发送队列 =====================
SERIAL_QUEUE_MAX = 512
serial_tx_queue = queue.Queue(maxsize=SERIAL_QUEUE_MAX)
_serial_worker_stop = threading.Event()
_serial_worker_thread = None
_hooks_lock = threading.Lock()

def _serial_worker_loop():
    while not _serial_worker_stop.is_set():
        try:
            data = serial_tx_queue.get(timeout=0.2)
        except queue.Empty:
            continue
        if data is None:  
            try:
                serial_tx_queue.task_done()
            except Exception:
                pass
            break
        try:
            with state.lock:
                ser = state.ser
                can_write = bool(ser and ser.is_open and state.service_active)
            if can_write:
                try:
                    ser.write(data)
                except Exception as e:
                    logger.warning(f"串口写入失败: {e}")
        finally:
            try:
                serial_tx_queue.task_done()
            except Exception:
                pass

def start_serial_worker():
    global _serial_worker_thread
    _serial_worker_stop.clear()
    while not serial_tx_queue.empty():
        try:
            serial_tx_queue.get_nowait()
            serial_tx_queue.task_done()
        except Exception:
            break
    if _serial_worker_thread is not None and _serial_worker_thread.is_alive():
        return
    _serial_worker_thread = threading.Thread(
        target=_serial_worker_loop, daemon=True, name="SerialTX"
    )
    _serial_worker_thread.start()
    logger.info("串口发送线程已启动")

def stop_serial_worker():
    global _serial_worker_thread
    _serial_worker_stop.set()
    try:
        serial_tx_queue.put_nowait(None)
    except Exception:
        pass
    t = _serial_worker_thread
    if t is not None and t.is_alive():
        t.join(timeout=1.5)
    _serial_worker_thread = None
    while not serial_tx_queue.empty():
        try:
            serial_tx_queue.get_nowait()
        except Exception:
            break
    logger.info("串口发送线程已停止")

def safe_serial_write(data, force=False):
    if isinstance(data, str):
        data = data.encode()
    
    # 快速失败：布尔值在 CPython 下读取是原子的，先做无锁检查
    # 注意：这里可能有极微的竞态，但对于"是否发送"这种非关键操作可以接受
    if not state.service_active:
        return False
    
    # 命令序列锁检查（Event 读取是无锁的）
    if not force and _sequence_active.is_set() and not getattr(_in_sequence, 'active', False):
        return False
    
    # 只在必要时获取锁检查串口对象
    with state.lock:
        if not state.ser:
            return False
    
    try:
        serial_tx_queue.put_nowait(data)
        return True
    except queue.Full:
        # 队列满时，丢弃最旧的数据以容纳新数据（FIFO 策略）
        try:
            serial_tx_queue.get_nowait()
            serial_tx_queue.task_done()
        except queue.Empty:
            pass
        try:
            serial_tx_queue.put_nowait(data)
            return True
        except queue.Full:
            logger.warning("串口发送队列已满，丢弃数据")
            return False

# ===================== 表情触发系统 =====================
# 命令序列锁：表情序列执行期间阻止其他命令并行发送
_cmd_sequence_lock = threading.RLock()
_sequence_active = threading.Event()
_in_sequence = threading.local()

# ZZ/momo 缓冲超时（秒）——0.5秒内匹配则触发动画，超时则显示文字
ZZ_BUFFER_TIMEOUT = 0.5
MOMO_BUFFER_TIMEOUT = 0.5

def _flush_zz_buffer():
    with state.lock:
        if not state.zz_pending:
            return
        state.zz_pending = False
        state.zz_flush_timer = None
    safe_serial_write(b"Z\n")

def _flush_momo_buffer():
    with state.lock:
        buf = state.momo_pending_buffer
        state.momo_pending_buffer = ""
        state.momo_flush_timer = None
    for c in buf:
        safe_serial_write(c.upper().encode() + b"\n")

def _trigger_expression_temporary(cmd_char, restore_delay=3.0):
    def _sequence():
        _cmd_sequence_lock.acquire()
        _sequence_active.set()
        _in_sequence.active = True
        try:
            safe_serial_write(f"{cmd_char}\n".encode())
            time.sleep(restore_delay)
            safe_serial_write(b"b\n")
        finally:
            _in_sequence.active = False
            _sequence_active.clear()
            _cmd_sequence_lock.release()
    t = threading.Thread(target=_sequence, daemon=True, name="ExprSeq")
    t.start()

def _trigger_expr_action(action):
    cmd = EXPR_ACTION_COMMANDS.get(action)
    if not cmd:
        return
    if action in EXPR_RESTORE_ACTIONS:
        with state.lock:
            auto_restore = state.expr_auto_restore
        if auto_restore:
            cmd_char = cmd.decode().strip()
            _trigger_expression_temporary(cmd_char, 3.0)
        else:
            safe_serial_write(cmd)
    else:
        safe_serial_write(cmd)

def _send_close_sequence():
    with state.lock:
        dlc_on = state.dlc_enabled
        service_running = state.service_active
    if not service_running:
        return
    _cmd_sequence_lock.acquire()
    _sequence_active.set()
    _in_sequence.active = True
    try:
        safe_serial_write(b"b\n", force=True)        # 切换表情
        time.sleep(0.3)
        safe_serial_write(b",X3Y3\n", force=True)     # 眼睛回正
        time.sleep(0.3)
        if dlc_on:
            safe_serial_write(b"n\n", force=True)     # 脖子回正（DLC开启时）
            time.sleep(0.3)
        for _ in range(3):
            safe_serial_write(b"c\n", force=True)      # 下巴向上转动3次
            time.sleep(0.3)
        if dlc_on:
            safe_serial_write(b"d\n", force=True)      # 昏睡指令（DLC开启时）
            time.sleep(0.5)
    finally:
        _in_sequence.active = False
        _sequence_active.clear()
        _cmd_sequence_lock.release()

def _cancel_momo_chain_timer():
    global _momo_timer
    if _momo_timer is not None:
        _momo_timer.cancel()
        _momo_timer = None

def _start_momo_chain_timer(delay):
    global _momo_timer
    _cancel_momo_chain_timer()
    _momo_timer = threading.Timer(delay, _momo_chain_timeout)
    _momo_timer.daemon = True
    _momo_timer.start()

def _momo_chain_timeout():
    with state.lock:
        if state.momo_step == 0:
            return
        state.momo_step = 0
        state.momo_flow_active = False
        state.momo_last_time = 0.0
    def _send_b():
        _cmd_sequence_lock.acquire()
        _sequence_active.set()
        _in_sequence.active = True
        try:
            safe_serial_write(b"b\n")
        finally:
            _in_sequence.active = False
            _sequence_active.clear()
            _cmd_sequence_lock.release()
    t = threading.Thread(target=_send_b, daemon=True, name="MomoReset")
    t.start()

def _handle_momo_chain():
    with state.lock:
        step = state.momo_step
        now = time.time()

    if step == 0:
        with state.lock:
            state.momo_step = 1
            state.momo_flow_active = True
            state.momo_last_time = now
        def _seq0():
            _cmd_sequence_lock.acquire()
            _sequence_active.set()
            _in_sequence.active = True
            try:
                safe_serial_write(b"h\n")
            finally:
                _in_sequence.active = False
                _sequence_active.clear()
                _cmd_sequence_lock.release()
            _start_momo_chain_timer(3.0)
        t = threading.Thread(target=_seq0, daemon=True, name="MomoSeq0")
        t.start()
    elif step == 1:
        with state.lock:
            state.momo_step = 2
            state.momo_last_time = now
        def _seq1():
            _cmd_sequence_lock.acquire()
            _sequence_active.set()
            _in_sequence.active = True
            try:
                safe_serial_write(b"i\n")
            finally:
                _in_sequence.active = False
                _sequence_active.clear()
                _cmd_sequence_lock.release()
            _start_momo_chain_timer(3.0)
        t = threading.Thread(target=_seq1, daemon=True, name="MomoSeq1")
        t.start()
    elif step == 2:
        with state.lock:
            state.momo_step = 0
            state.momo_flow_active = False
            state.momo_last_time = 0.0
        _cancel_momo_chain_timer()
        def _seq2():
            _cmd_sequence_lock.acquire()
            _sequence_active.set()
            _in_sequence.active = True
            try:
                safe_serial_write(b"g\n")
                time.sleep(5.0)
                safe_serial_write(b"b\n")
            finally:
                _in_sequence.active = False
                _sequence_active.clear()
                _cmd_sequence_lock.release()
        t = threading.Thread(target=_seq2, daemon=True, name="MomoSeq2")
        t.start()

def _check_expression_triggers(key):
    char = None
    try:
        if hasattr(key, 'char') and key.char:
            char = key.char
    except Exception:
        pass
    if char is None:
        return False
    char_lower = char.lower()

    with state.lock:
        momo_locked = state.momo_flow_active
        dlc_on = state.dlc_enabled
        mods = set(state.pressed_modifiers)

    if not dlc_on:
        return False

    # "?" 和 "!" 需要 Shift 组合产生，在修饰键检查之前处理
    # "?" → 问号（momo 流程中屏蔽）
    if char == "?" and not momo_locked:
        _trigger_expression_temporary("e", 3.0)
        return True

    # "!" → 感叹号（momo 流程中屏蔽）
    if char == "!" and not momo_locked:
        _trigger_expression_temporary("i", 3.0)
        return True

    # 有修饰键时不触发表情（组合键只执行绑定动作）
    if mods:
        return False

    # 非z/m/o字符：冲刷缓冲区后正常处理
    if char_lower not in ('z', 'm', 'o'):
        _flush_zz_buffer()
        _flush_momo_buffer()
        return False

    # ---- ZZ 缓冲触发 ----
    if char_lower == 'z' and not momo_locked:
        _flush_momo_buffer()
        with state.lock:
            if state.zz_pending:
                # 0.5秒内第二个z → 触发动画，不显示任何z
                state.zz_pending = False
                if state.zz_flush_timer:
                    state.zz_flush_timer.cancel()
                    state.zz_flush_timer = None
            else:
                # 第一个z：缓冲，启动0.5秒超时
                state.zz_pending = True
                state.zz_flush_timer = threading.Timer(
                    ZZ_BUFFER_TIMEOUT, _flush_zz_buffer
                )
                state.zz_flush_timer.daemon = True
                state.zz_flush_timer.start()
                return "buffered"
        # 触发ZZ动画（d → 3s → b），顺序发送
        def _zz_seq():
            _cmd_sequence_lock.acquire()
            _sequence_active.set()
            _in_sequence.active = True
            try:
                safe_serial_write(b"d\n")
                time.sleep(3.0)
                safe_serial_write(b"b\n")
            finally:
                _in_sequence.active = False
                _sequence_active.clear()
                _cmd_sequence_lock.release()
        t = threading.Thread(target=_zz_seq, daemon=True, name="ZZSeq")
        t.start()
        return True

    # ---- momo 缓冲触发 ----
    if char_lower in ('m', 'o'):
        _flush_zz_buffer()
        with state.lock:
            if not state.momo_pending_buffer:
                state.momo_pending_buffer = char_lower
            else:
                state.momo_pending_buffer += char_lower
            buf = state.momo_pending_buffer

            if buf == "momo":
                # 完成！触发momo链，不显示任何m/o
                state.momo_pending_buffer = ""
                if state.momo_flush_timer:
                    state.momo_flush_timer.cancel()
                    state.momo_flush_timer = None
                trigger = True
            elif "momo".startswith(buf):
                # 仍可能构成momo，继续缓冲
                if state.momo_flush_timer:
                    state.momo_flush_timer.cancel()
                state.momo_flush_timer = threading.Timer(
                    MOMO_BUFFER_TIMEOUT, _flush_momo_buffer
                )
                state.momo_flush_timer.daemon = True
                state.momo_flush_timer.start()
                return "buffered"
            else:
                # 无法构成momo，冲刷并正常显示
                state.momo_pending_buffer = ""
                if state.momo_flush_timer:
                    state.momo_flush_timer.cancel()
                    state.momo_flush_timer = None
                trigger = False
        if trigger:
            _handle_momo_chain()
            return True
        else:
            _flush_momo_buffer()
            return False

    return False

# ===================== Raw Input 处理 =====================
_raw_kb_enabled = False

class _RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", ctypes.c_uint32),
        ("dwSize", ctypes.c_uint32),
        ("hDevice", ctypes.c_void_p),
        ("wParam", ctypes.c_void_p),
    ]

class _RAWKEYBOARD(ctypes.Structure):
    _fields_ = [
        ("MakeCode", ctypes.c_ushort),
        ("Flags", ctypes.c_ushort),
        ("Reserved", ctypes.c_ushort),
        ("VKey", ctypes.c_ushort),
        ("Message", ctypes.c_uint32),
        ("ExtraInformation", ctypes.c_void_p),
    ]

class _RAWINPUT(ctypes.Structure):
    _fields_ = [
        ("header", _RAWINPUTHEADER),
        ("keyboard", _RAWKEYBOARD),
    ]

def _handle_raw_input(lparam):
    if not _raw_kb_enabled:
        return
    try:
        user32.GetRawInputData.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint), ctypes.c_uint,
        ]
        user32.GetRawInputData.restype = ctypes.c_uint
        hraw = ctypes.c_void_p(lparam)
        size = ctypes.c_uint(0)
        user32.GetRawInputData(hraw, RID_INPUT, None, ctypes.byref(size), ctypes.sizeof(_RAWINPUTHEADER))
        if size.value == 0:
            return
        buf = (ctypes.c_ubyte * size.value)()
        ret = user32.GetRawInputData(hraw, RID_INPUT, buf, ctypes.byref(size), ctypes.sizeof(_RAWINPUTHEADER))
        if ret == 0:
            return
        raw = ctypes.cast(buf, ctypes.POINTER(_RAWINPUT)).contents
        if raw.header.dwType != RIM_TYPEKEYBOARD:
            return
        vk = raw.keyboard.VKey
        msg = raw.keyboard.Message
        scan_code = raw.keyboard.MakeCode
        if raw.keyboard.Flags & 0x02:
            scan_code |= 0xE000
        is_down = (msg == WM_RAW_KEYDOWN or msg == WM_RAW_SYSKEYDOWN)
        is_up = (msg == WM_RAW_KEYUP or msg == WM_RAW_SYSKEYUP)
        if not is_down and not is_up:
            return
        key = _vk_to_rawkey(vk, scan_code)
        if is_down:
            on_press(key)
        else:
            on_release(key)
    except Exception as e:
        logger.error(f"Raw Input 处理异常: {e}")

# ===================== 输入钩子安装 / 卸载 =====================
def _stop_mouse_hook():
    global mouse_listener
    if mouse_listener is not None:
        try:
            mouse_listener.stop()
        except Exception:
            pass
        mouse_listener = None

def _stop_key_hook():
    global _raw_kb_enabled
    _raw_kb_enabled = False

def _start_mouse_hook():
    global mouse_listener
    if mouse_listener is not None:
        try:
            if mouse_listener.is_alive():
                return
        except Exception:
            mouse_listener = None
    try:
        mouse_listener = Listener(on_move=on_move, on_click=on_click, on_scroll=on_scroll)
        mouse_listener.daemon = True
        mouse_listener.start()
    except Exception as e:
        logger.error(f"启动鼠标钩子失败: {e}")
        mouse_listener = None

def _start_key_hook():
    global _raw_kb_enabled
    _raw_kb_enabled = True

_hooks_mode = None  # "interact" | "unload" | "key_only"

def sync_input_hooks():
    global _hooks_mode
    with _hooks_lock:
        with state.lock:
            active = state.service_active
            interact = state.interaction_enabled
        if active and interact:
            mode = "interact"
            _start_key_hook()
            _start_mouse_hook()
            with state.lock:
                state.last_map_x = state.last_map_y = -1
                state.last_move_time = 0.0
        elif active and not interact:
            mode = "unload"
            _stop_mouse_hook()
            _stop_key_hook()
        else:
            mode = "key_only"
            _stop_mouse_hook()
            _start_key_hook()
        if mode != _hooks_mode:
            _hooks_mode = mode
            if mode == "interact":
                logger.info("输入监听已开启（互动模式）")
            elif mode == "unload":
                logger.info("输入监听已关闭（游戏/反作弊/保护模式）")
            else:
                logger.info("输入监听：仅保留键盘（服务未启动，便于改键）")

# ===================== 鼠标监听看门狗（键盘已用 Raw Input，无需看门狗） =====================
_mouse_watchdog_running = False
_mouse_watchdog_thread = None

def _mouse_watchdog():
    """看门狗：检测鼠标钩子线程是否失效，自动重启。"""
    global _mouse_watchdog_running
    while _mouse_watchdog_running:
        time.sleep(10)  # 优化：从5秒增加到10秒，降低CPU唤醒频率
        if not _mouse_watchdog_running:
            break
        with state.lock:
            active = state.service_active
            interact = state.interaction_enabled
        if not active or not interact:
            continue
        with _hooks_lock:
            if mouse_listener is None or not mouse_listener.is_alive():
                logger.warning("鼠标监听线程已死，正在重启...")
                _stop_mouse_hook()
                _start_mouse_hook()

def _start_mouse_watchdog():
    global _mouse_watchdog_running, _mouse_watchdog_thread
    _mouse_watchdog_running = True
    if _mouse_watchdog_thread is None or not _mouse_watchdog_thread.is_alive():
        _mouse_watchdog_thread = threading.Thread(
            target=_mouse_watchdog, daemon=True, name="MouseWatchdog"
        )
        _mouse_watchdog_thread.start()
        logger.info("鼠标监听看门狗已启动")

def _stop_mouse_watchdog():
    global _mouse_watchdog_running, _mouse_watchdog_thread
    _mouse_watchdog_running = False
    _mouse_watchdog_thread = None

def scan_serial_ports():
    ports = serial.tools.list_ports.comports()
    port_list, ch340 = [], None
    for p in ports:
        if "CH340" in (p.description or "").upper():
            port_list.append(p.device)
            if ch340 is None:
                ch340 = p.device
    return port_list, ch340

# ===================== 回调 =====================
class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def get_cursor_pos():
    pt = _POINT()
    try:
        if user32.GetCursorPos(ctypes.byref(pt)):
            return int(pt.x), int(pt.y)
    except Exception:
        pass
    return None

def apply_mouse_position(x, y, force=False, count_as_input=False):
    with state.lock:
        if not state.service_active or not state.interaction_enabled or state.hardware_overloaded:
            return False
        if state.is_centered_state and not force:
            return False
        now = time.time()
        if not force and (now - state.last_move_time < MOUSE_MOVE_INTERVAL):
            return False
        state.last_move_time = now
        ox_min, ox_max = state.ORIGIN_X_MIN, state.ORIGIN_X_MAX
        oy_min, oy_max = state.ORIGIN_Y_MIN, state.ORIGIN_Y_MAX
        monitors = state.monitors

    clamp_x = max(ox_min, min(ox_max, x))
    clamp_y = max(oy_min, min(oy_max, y))

    # X 轴始终用全局虚拟桌面范围，保证跨屏幕连续移动不跳变
    x_ratio = (clamp_x - ox_min) / max(1, ox_max - ox_min)

    # Y 轴：只动态切换分母（1080/1366），原点保持全局 oy_min 不变
    # 这样鼠标在任何屏幕都能到底部（ratio=1.0），且跨屏幕不产生跳变
    y_denominator = max(1, oy_max - oy_min)  # 默认用全局高度
    if monitors:
        for m in monitors:
            if m["x"] <= clamp_x < m["x"] + m["width"] and m["y"] <= clamp_y < m["y"] + m["height"]:
                y_denominator = max(1, m["height"] - 1)
                break
    y_ratio = (clamp_y - oy_min) / y_denominator
    map_x = int(TARGET_X_START - x_ratio * (TARGET_X_START - TARGET_X_END))
    map_y = int(TARGET_Y_MIN + y_ratio * (TARGET_Y_MAX - TARGET_Y_MIN))
    map_x = max(TARGET_X_END, min(TARGET_X_START, map_x))
    map_y = max(TARGET_Y_MIN, min(TARGET_Y_MAX, map_y))

    with state.lock:
        changed = (map_x != state.last_map_x or map_y != state.last_map_y)
        if changed:
            state.last_map_x, state.last_map_y = map_x, map_y
            if count_as_input:
                state.last_input_signal_time = now
                state.is_centered_state = False
    if changed:
        safe_serial_write(f",X{map_x}Y{map_y}\n")
        return True
    return False

def _cursor_really_moved(x, y):
    with state.lock:
        lx, ly = state.last_cursor_x, state.last_cursor_y
        th = state.CURSOR_MOVE_THRESHOLD
        if lx is None or ly is None:
            state.last_cursor_x, state.last_cursor_y = x, y
            return True
        if abs(x - lx) >= th or abs(y - ly) >= th:
            state.last_cursor_x, state.last_cursor_y = x, y
            return True
    return False

def _main_thread_call(callback):
    if threading.current_thread() is threading.main_thread():
        try:
            callback()
        except Exception as e:
            logger.error(f"主线程回调异常: {e}")
    else:
        root.after(0, callback)

def on_move(x, y):
    # 快速检查：无锁读取布尔值（CPython 原子操作）
    if not state.service_active or not state.interaction_enabled or state.hardware_overloaded:
        return
    
    # 只有当 pynput 坐标显示移动超过阈值时，才获取系统级精确坐标
    if not _cursor_really_moved(x, y):
        return
    
    # 获取系统级坐标以确保准确性（多屏偏移校正）
    pos = get_cursor_pos()
    if pos is not None:
        x, y = pos
        # 同步系统坐标到状态，供后台线程参考（避免状态不一致）
        with state.lock:
            state.last_sys_cursor_x = x
            state.last_sys_cursor_y = y
    
    with state.lock:
        was_centered = state.is_centered_state
        state.last_input_signal_time = time.time()
        if was_centered:
            state.is_centered_state = False
            state.last_map_x = state.last_map_y = -1
    apply_mouse_position(x, y, force=was_centered, count_as_input=True)

def on_click(x, y, button, pressed):
    # ---- 绑定模式：捕获鼠标按键 ----
    with state.lock:
        binding = state.binding_mode
        binding_cb = state.binding_callback
    if binding and binding_cb and pressed:
        mouse_str = mouse_button_to_str(button)
        if mouse_str:
            with state.lock:
                state.binding_mode = False
                state.binding_callback = None
            _main_thread_call(lambda s=mouse_str: binding_cb(s))
        return

    with state.lock:
        if not state.service_active or not state.interaction_enabled or state.hardware_overloaded or not pressed:
            return
        if state.momo_flow_active:
            return
        state.last_input_signal_time = time.time()
        state.is_centered_state = False
        keybinds = state.keybinds.copy()
        neck_active = state.neck_active
        mouth_active = state.mouth_active
        dlc_on = state.dlc_enabled

    # 检查鼠标按键是否绑定了动作（眨眼默认绑定鼠标左键）
    mouse_str = mouse_button_to_str(button)
    if mouse_str:
        for action, bound_key in keybinds.items():
            if bound_key == mouse_str:
                if action in EXPR_ACTION_COMMANDS:
                    if dlc_on:
                        _trigger_expr_action(action)
                    return
                cmd = get_action_command(action, neck_active, mouth_active)
                if cmd:
                    safe_serial_write(cmd)
                    return

def on_scroll(x, y, dx, dy):
    # ---- 绑定模式：捕获滚轮 ----
    with state.lock:
        binding = state.binding_mode
        binding_cb = state.binding_callback
    if binding and binding_cb:
        wheel_str = "mouse_wheel_up" if dy > 0 else "mouse_wheel_down"
        with state.lock:
            state.binding_mode = False
            state.binding_callback = None
        _main_thread_call(lambda s=wheel_str: binding_cb(s))
        return

    with state.lock:
        if not state.service_active or not state.interaction_enabled or state.hardware_overloaded:
            return
        if state.momo_flow_active:
            return
        state.last_input_signal_time = time.time()
        state.is_centered_state = False
        keybinds = state.keybinds.copy()
        neck_active = state.neck_active
        mouth_active = state.mouth_active
        dlc_on = state.dlc_enabled

    # 检查滚轮是否绑定了动作
    wheel_str = "mouse_wheel_up" if dy > 0 else "mouse_wheel_down"
    for action, bound_key in keybinds.items():
        if bound_key == wheel_str:
            if action in EXPR_ACTION_COMMANDS:
                if dlc_on:
                    _trigger_expr_action(action)
                return
            cmd = get_action_command(action, neck_active, mouth_active)
            if cmd:
                safe_serial_write(cmd)
                return

def on_press(key):
    key_str = key_to_str(key)
    if key_str is None:
        return

    # 记录最后键盘事件时间（看门狗用）
    with state.lock:
        state.last_keyboard_event_time = time.time()

    # ---- 更新修饰键状态 ----
    if key_str in MODIFIER_KEYS:
        with state.lock:
            state.pressed_modifiers.add(key_str)

    # ---- 绑定模式：支持组合键 ----
    with state.lock:
        binding = state.binding_mode
        binding_cb = state.binding_callback
        mods_snapshot = set(state.pressed_modifiers)

    if binding and binding_cb:
        # Esc 单独按下 → 取消
        if key_str == "esc" and not (mods_snapshot - {"esc"}):
            with state.lock:
                state.binding_mode = False
                state.binding_callback = None
            _main_thread_call(lambda: binding_cb("esc"))
            return
        # 纯修饰键：只记录，等待主键
        if key_str in MODIFIER_KEYS:
            held = " + ".join(
                KEY_DISPLAY_NAMES.get(m, m) for m in MODIFIER_ORDER if m in mods_snapshot
            )
            _main_thread_call(lambda h=held: _update_binding_hint(h))
            return
        # 主键（可带修饰键）→ 完成绑定
        combo = build_combo_str(key_str, mods_snapshot)
        with state.lock:
            state.binding_mode = False
            state.binding_callback = None
        _main_thread_call(lambda c=combo: binding_cb(c))
        return

    with state.lock:
        kb = state.keybinds
        service_active = state.service_active
        interaction_enabled = state.interaction_enabled
        hardware_overloaded = state.hardware_overloaded
        mouth_active = state.mouth_active
        keyboard_mouth_active = state.keyboard_mouth_active
        neck_active = state.neck_active
        eye_input_display = state.eye_input_display_active
        dlc_on = state.dlc_enabled
        momo_locked = state.momo_flow_active
        mods_snapshot = set(state.pressed_modifiers)

    # 修饰键本身不触发动作
    if key_str in MODIFIER_KEYS:
        return

    combo = build_combo_str(key_str, mods_snapshot)

    # ---- 快捷开关热键（不依赖互动状态，只要有键盘监听即可触发）----
    toggle_map = {}
    for _action in ("toggle_mouth", "toggle_keyboard_mouth", "toggle_neck",
                    "toggle_eye_input", "toggle_service"):
        _bound = kb.get(_action)
        if _bound:
            toggle_map[_bound] = _action
    
    if combo and combo in toggle_map:
        _main_thread_call(lambda a=toggle_map[combo]: _handle_toggle_hotkey(a))
        return

    # ---- 正常互动模式 ----
    if not service_active or not interaction_enabled or hardware_overloaded:
        return

    with state.lock:
        state.last_input_signal_time = time.time()

    # ---- 表情模式触发检测（?/!/zz/momo）----
    expr_result = _check_expression_triggers(key)
    if expr_result is True:
        return  # 已触发表情，字符已处理
    if expr_result == "buffered":
        return  # 字符缓冲中，不显示

    # ---- momo 流程中锁定其他键位互动 ----
    if momo_locked:
        return

    # 连续输入 xin 触发爱心（无修饰键时）
    try:
        if not mods_snapshot and hasattr(key, 'char') and key.char and key.char.isalpha():
            with state.lock:
                state.key_buffer += key.char.lower()
                if len(state.key_buffer) > 10:
                    state.key_buffer = state.key_buffer[-10:]
                if state.key_buffer.endswith("xin"):
                    safe_serial_write(b"z\n")
                    state.key_buffer = ""
                    return
    except Exception:
        pass

    if not input_throttler.allow():
        return

    with state.lock:
        state.is_centered_state = False

    try:
        # 新增表情快捷键匹配（DLC 开启时生效）
        if dlc_on:
            for action in EXPR_ACTION_COMMANDS:
                bound_key = kb.get(action)
                if bound_key and combo == bound_key:
                    _trigger_expr_action(action); return
        
        # 精确匹配组合键 / 单键（使用字典映射，O(1) 查找）
        action_cmd_map = {
            kb.get("heart"): b"z\n",
            kb.get("expression"): b"b\n",
            kb.get("blink"): b"a\n",
            kb.get("space"): b"y\n",
            kb.get("backspace"): b"w\n",
            kb.get("enter"): b"x\n",
        }
        
        cmd = action_cmd_map.get(combo)
        if cmd:
            safe_serial_write(cmd); return
        
        if neck_active:
            nl_key = kb.get("neck_left")
            if nl_key and combo == nl_key:
                safe_serial_write(b"k\n"); return
            nr_key = kb.get("neck_right")
            if nr_key and combo == nr_key:
                safe_serial_write(b"l\n"); return
                
        if mouth_active:
            mu_key = kb.get("mouth_up")
            if mu_key and combo == mu_key:
                safe_serial_write(b"c\n"); return
            md_key = kb.get("mouth_down")
            if md_key and combo == md_key:
                safe_serial_write(b"f\n"); return
                
        # 键盘字母/数字触发嘴巴开合（单独开关）
        if keyboard_mouth_active and mouth_simulator and not mods_snapshot:
            if is_alnum_interact_key(key_str):
                mouth_simulator.trigger()
                
        # 字母/数字直传（主键盘 + 小键盘）：无修饰键时发送到眼睛显示屏
        if not mods_snapshot and is_alnum_interact_key(key_str) and eye_input_display:
            payload = (key_str.upper() if key_str.isalpha() else key_str).encode() + b"\n"
            safe_serial_write(payload)
    except Exception:
        pass


def on_release(key):
    key_str = key_to_str(key)
    if key_str in MODIFIER_KEYS:
        with state.lock:
            state.pressed_modifiers.discard(key_str)


def _update_binding_hint(held_text):
    try:
        if hasattr(root, "_keybind_hint_label") and root._keybind_hint_label.winfo_exists():
            root._keybind_hint_label.config(
                text=f"已按住 {held_text}，请再按主键...（Esc 取消）"
            )
    except Exception:
        pass

# ===================== 后台线程 =====================
def mouse_timeout_checker():
    poll = max(0.05, MOUSE_MOVE_INTERVAL)
    last_center_attempt = 0.0
    while True:
        with state.lock:
            if not state.service_active:
                break
            active = state.service_active
            interact = state.interaction_enabled
            overloaded = state.hardware_overloaded
            auto_center = state.auto_center_eyes
            last_input = state.last_input_signal_time
            is_centered = state.is_centered_state

        time.sleep(poll)
        if not active or not interact or overloaded:
            continue

        if not is_centered:
            pos = get_cursor_pos()
            if pos is not None:
                px, py = pos
                # 优化：鼠标完全静止时跳过，减少后续计算
                with state.lock:
                    if px == state.last_sys_cursor_x and py == state.last_sys_cursor_y:
                        pass  # 坐标未变，跳过
                    else:
                        state.last_sys_cursor_x = px
                        state.last_sys_cursor_y = py
                        apply_mouse_position(px, py, force=False, count_as_input=False)

        with state.lock:
            last_input = state.last_input_signal_time
            is_centered = state.is_centered_state
            auto_center = state.auto_center_eyes
        now = time.time()
        idle = now - last_input

        with state.lock:
            if state.key_buffer and idle > KEY_BUFFER_TIMEOUT:
                state.key_buffer = ""
            if state.expr_buffer and idle > KEY_BUFFER_TIMEOUT:
                state.expr_buffer = ""

        if auto_center and idle >= 2.0 and not is_centered:
            if now - last_center_attempt < 0.5:
                continue
            last_center_attempt = now
            ok = safe_serial_write(b",X3Y3\n")
            if ok:
                with state.lock:
                    state.is_centered_state = True
                    state.last_map_x, state.last_map_y = 3, 3
                logger.info("眼球自动居中已触发")
            else:
                logger.warning("眼球自动居中发送失败，将重试")

def hardware_monitor_loop():
    while True:
        with state.lock:
            if not state.service_active:
                break
        time.sleep(HARDWARE_POLL_INTERVAL)
        with state.lock:
            if not state.service_active:
                break
        try:
            overloaded = hw_monitor.check_overload()
            with state.lock:
                was = state.hardware_overloaded
                if overloaded and not was:
                    state.hardware_overloaded = True
                    state.interaction_enabled = False
                    root.after(0, lambda: update_mode_display("性能保护模式 (CPU过载)"))
                    # 过载时同样完全卸载钩子
                    threading.Thread(target=sync_input_hooks, daemon=True).start()
                elif not overloaded and was:
                    state.hardware_overloaded = False
                    update_interaction_by_process()
        except Exception as e:
            logger.error(f"硬件监控异常: {e}")

# ===================== 现代化组件 =====================


class ModernToggle(tk.Frame):

    _TW = 54
    _TH = 30
    _KS = 22
    _KM = 4

    def __init__(self, parent, label, callback=None, active=False,
                 hotkey_text="", bg=None, **kwargs):
        bg = bg or COLORS["card"]
        super().__init__(parent, bg=bg, **kwargs)
        self._callback = callback
        self._active = active
        self._bg = bg
        self._bg_hover = COLORS.get("card_hover", "#1B2440")
        self._hover = False
        self._widgets = []
        self._photo = None

        self.canvas = tk.Canvas(self, width=self._TW, height=self._TH,
                                bg=bg, highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, padx=(14, 12), pady=9)
        self._widgets.append(self.canvas)

        self.label = tk.Label(self, text=label, bg=bg, fg=COLORS["text"],
                              font=("思源真黑体", 10))
        self.label.pack(side=tk.LEFT, padx=(0, 6))
        self._widgets.append(self.label)

        self.status_dot = tk.Label(self, text="●", bg=bg,
                                   fg=COLORS["toggle_on"] if active else COLORS["text_muted"],
                                   font=("思源真黑体", 7))
        self.status_dot.pack(side=tk.LEFT, padx=(0, 8))
        self._widgets.append(self.status_dot)

        self.hotkey_badge = None
        self.hotkey_label = None
        if hotkey_text:
            self._make_hotkey_badge(hotkey_text)

        self._draw()

        for w in list(self._widgets) + [self]:
            w.bind("<Button-1>", self._on_click)
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)

    def _make_hotkey_badge(self, text):
        self.hotkey_badge = tk.Frame(self, bg=COLORS["bg_secondary"],
                                     highlightbackground=COLORS["border_light"],
                                     highlightthickness=1)
        self.hotkey_badge.pack(side=tk.RIGHT, padx=(0, 14))
        self.hotkey_label = tk.Label(self.hotkey_badge, text=text,
                                     bg=COLORS["bg_secondary"], fg=COLORS["accent"],
                                     font=("Consolas", 9, "bold"), padx=10, pady=3)
        self.hotkey_label.pack()
        self._widgets.append(self.hotkey_badge)
        self._widgets.append(self.hotkey_label)

    @staticmethod
    def _hex_to_rgb(hex_color):
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))

    @staticmethod
    def _fill_pill_pil(draw, x1, y1, x2, y2, fill):
        h = y2 - y1
        r = h // 2
        draw.rectangle([x1 + r, y1, x2 - r, y2], fill=fill)
        draw.ellipse([x1, y1, x1 + h, y2], fill=fill)
        draw.ellipse([x2 - h, y1, x2, y2], fill=fill)

    def _draw_pill(self, x1, y1, x2, y2, fill, outline=""):
        h = y2 - y1
        r = h // 2
        self.canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="")
        self.canvas.create_oval(x1, y1, x1 + h, y2, fill=fill, outline="")
        self.canvas.create_oval(x2 - h, y1, x2, y2, fill=fill, outline="")
        if outline:
            self.canvas.create_line(x1 + r, y1, x2 - r, y1, fill=outline, width=1)
            self.canvas.create_line(x1 + r, y2, x2 - r, y2, fill=outline, width=1)
            self.canvas.create_arc(x1, y1, x1 + h, y2, start=90, extent=180,
                                   style=tk.ARC, outline=outline, width=1)
            self.canvas.create_arc(x2 - h, y1, x2, y2, start=270, extent=180,
                                   style=tk.ARC, outline=outline, width=1)

    def _draw(self):
        """使用原生 Canvas 绘制，避免 PIL 开销（性能优化）"""
        self._draw_canvas()

    def _draw_pil(self):
        w, h, ks, km = self._TW, self._TH, self._KS, self._KM
        scale = 4
        sw, sh = w * scale, h * scale
        sks, skm = ks * scale, km * scale

        img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        tx1, ty1 = scale, 2 * scale
        tx2, ty2 = (w - 1) * scale, (h - 2) * scale
        th = ty2 - ty1

        if self._active:
            track_fill = self._hex_to_rgb(COLORS["toggle_on"]) + (255,)
            self._fill_pill_pil(draw, tx1, ty1, tx2, ty2, track_fill)
            kx = (w - ks - km) * scale
            knob_fill = self._hex_to_rgb(COLORS["toggle_knob"]) + (255,)
        else:
            bg = self._bg_hover if self._hover else self._bg
            border_fill = self._hex_to_rgb("#3A4A66") + (255,)
            bg_fill = self._hex_to_rgb(bg) + (255,)
            bw = scale

            self._fill_pill_pil(draw, tx1, ty1, tx2, ty2, border_fill)
            self._fill_pill_pil(draw, tx1 + bw, ty1 + bw, tx2 - bw, ty2 - bw, bg_fill)

            kx = km * scale
            knob_fill = self._hex_to_rgb(COLORS["toggle_knob_off"]) + (255,)

        draw.ellipse([kx, skm, kx + sks, skm + sks], fill=knob_fill)

        img = img.resize((w, h), _LANCZOS)
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.create_image(0, 0, image=self._photo, anchor=tk.NW)

    def _draw_canvas(self):
        w, h, ks, km = self._TW, self._TH, self._KS, self._KM
        if self._active:
            self._draw_pill(1, 2, w - 1, h - 2, fill=COLORS["toggle_on"])
            kx = w - ks - km
            self.canvas.create_oval(kx, km, kx + ks, km + ks,
                                    fill=COLORS["toggle_knob"], outline="")
        else:
            bg = self._bg_hover if self._hover else self._bg
            self._draw_pill(1, 2, w - 1, h - 2, fill=bg, outline="#3A4A66")
            kx = km
            self.canvas.create_oval(kx, km, kx + ks, km + ks,
                                    fill=COLORS["toggle_knob_off"], outline="")

    def _set_row_bg(self, color):
        self.config(bg=color)
        for w in self._widgets:
            try:
                w.config(bg=color)
            except Exception:
                pass

    def _on_click(self, event=None):
        if self._callback:
            self._callback()

    def _on_enter(self, event=None):
        self._hover = True
        self._set_row_bg(self._bg_hover)
        self.label.config(fg=COLORS["accent"])
        self._draw()

    def _on_leave(self, event=None):
        self._hover = False
        self._set_row_bg(self._bg)
        self.label.config(fg=COLORS["text"])
        self._draw()

    def set_active(self, active):
        self._active = active
        self._draw()
        if active:
            self.status_dot.config(text="●", fg=COLORS["toggle_on"])
        else:
            self.status_dot.config(text="○", fg=COLORS["text_muted"])

    def set_hotkey_text(self, text):
        if text:
            if self.hotkey_badge is None:
                self._make_hotkey_badge(text)
                for w in [self.hotkey_badge, self.hotkey_label]:
                    w.bind("<Button-1>", self._on_click)
                    w.bind("<Enter>", self._on_enter)
                    w.bind("<Leave>", self._on_leave)
            else:
                self.hotkey_label.config(text=text)
        else:
            if self.hotkey_label:
                self.hotkey_label.config(text="")

    @property
    def active(self):
        return self._active


class ModernButton(tk.Frame):

    def __init__(self, parent, text, command, bg=None, fg=None, active_bg=None,
                 font=None, height=2, **kwargs):
        bg = bg or COLORS["btn"]
        fg = fg or COLORS["text"]
        active_bg = active_bg or COLORS["btn_hover"]
        font = font or ("思源真黑体", 10)
        super().__init__(parent, bg=bg, **kwargs)
        self._command = command
        self._bg = bg
        self._active_bg = active_bg
        self._height = height

        self.label = tk.Label(self, text=text, bg=bg, fg=fg, font=font,
                              cursor="hand2", pady=6 * height)
        self.label.pack(fill=tk.BOTH, expand=True, padx=12)

        self.label.bind("<Button-1>", self._on_click)
        self.label.bind("<Enter>", self._on_enter)
        self.label.bind("<Leave>", self._on_leave)

    def _on_click(self, event=None):
        if self._command:
            self._command()

    def _on_enter(self, event=None):
        self.config(bg=self._active_bg)
        self.label.config(bg=self._active_bg)

    def _on_leave(self, event=None):
        self.config(bg=self._bg)
        self.label.config(bg=self._bg)

    def config(self, **kwargs):
        if "state" in kwargs:
            state = kwargs.pop("state")
            if state == tk.DISABLED:
                self.label.unbind("<Button-1>")
                self.label.config(fg=COLORS["text_muted"])
            else:
                self.label.bind("<Button-1>", self._on_click)
        if "text" in kwargs:
            self.label.config(text=kwargs.pop("text"))
        if "bg" in kwargs:
            self._bg = kwargs["bg"]
        super().config(**kwargs)


class RoundedButton(tk.Canvas):

    def __init__(self, parent, text, command=None, width=220, height=46,
                 radius=14, bg=None, fg=None, hover_bg=None,
                 disabled_bg=None, disabled_fg=None,
                 font=None, canvas_bg=None, **kwargs):
        self._command = command
        self._bg = bg or COLORS["accent"]
        self._hover_bg = hover_bg or COLORS["accent_dim"]
        self._fg = fg or "#0A0E1A"
        self._disabled_bg = disabled_bg or COLORS["btn_hover"]
        self._disabled_fg = disabled_fg or COLORS["text_muted"]
        self._text = text
        self._font = font or ("思源真黑体", 12, "bold")
        self._width = width
        self._height = height
        self._radius = radius
        self._hover = False
        self._disabled = False
        self._photo = None
        self._canvas_bg = canvas_bg or COLORS["bg"]
        self._responsive = kwargs.pop("responsive", False)

        super().__init__(parent, width=width, height=height,
                         bg=self._canvas_bg, highlightthickness=0)

        self._draw_button()

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        if self._responsive:
            self.bind("<Configure>", self._on_configure)

    def _on_configure(self, event):
        """窗口大小变化时重新绘制按钮以适应新宽度"""
        if event.width > 10 and event.width != self._width:
            self._width = event.width
            self._draw_button()

    @staticmethod
    def _draw_rounded_rect_pil(draw, xy, radius, fill):
        x1, y1, x2, y2 = xy
        draw.rectangle([x1 + radius, y1, x2 - radius, y2], fill=fill)
        draw.rectangle([x1, y1 + radius, x2, y2 - radius], fill=fill)
        draw.pieslice([x1, y1, x1 + 2 * radius, y1 + 2 * radius], 180, 270, fill=fill)
        draw.pieslice([x2 - 2 * radius, y1, x2, y1 + 2 * radius], 270, 360, fill=fill)
        draw.pieslice([x1, y2 - 2 * radius, x1 + 2 * radius, y2], 90, 180, fill=fill)
        draw.pieslice([x2 - 2 * radius, y2 - 2 * radius, x2, y2], 0, 90, fill=fill)

    def _draw_button(self):
        """使用原生 Canvas 绘制圆角按钮，避免 PIL 开销（性能优化）"""
        self.delete("all")
        if self._disabled:
            fill = self._disabled_bg
            text_fg = self._disabled_fg
        elif self._hover:
            fill = self._hover_bg
            text_fg = self._fg
        else:
            fill = self._bg
            text_fg = self._fg

        r = self._radius
        w, h = self._width, self._height
        # 使用矩形+椭圆组合绘制圆角（性能远优于PIL）
        self.create_rectangle(r, 0, w - r, h, fill=fill, outline="")
        self.create_rectangle(0, r, w, h - r, fill=fill, outline="")
        self.create_oval(0, 0, r * 2, r * 2, fill=fill, outline="")
        self.create_oval(w - r * 2, 0, w, r * 2, fill=fill, outline="")
        self.create_oval(0, h - r * 2, r * 2, h, fill=fill, outline="")
        self.create_oval(w - r * 2, h - r * 2, w, h, fill=fill, outline="")

        self.create_text(self._width // 2, self._height // 2,
                         text=self._text, fill=text_fg, font=self._font)

    def _on_enter(self, event=None):
        if self._disabled:
            return
        self._hover = True
        self._draw_button()
        self.config(cursor="hand2")

    def _on_leave(self, event=None):
        self._hover = False
        self._draw_button()

    def _on_click(self, event=None):
        if self._disabled:
            return
        if self._command:
            self._command()

    def config(self, **kwargs):
        if "state" in kwargs:
            st = kwargs.pop("state")
            if st == tk.DISABLED:
                self._disabled = True
                self._hover = False
            else:
                self._disabled = False
            self._draw_button()
        if "text" in kwargs:
            self._text = kwargs.pop("text")
            self._draw_button()
        if kwargs:
            super().config(**kwargs)


# ===================== UI 辅助 =====================
def update_ui_for_service_stopped():
    start_btn.config(state=tk.NORMAL)
    stop_btn.config(state=tk.DISABLED)
    port_combobox.config(state="readonly")
    refresh_port_btn.config(state=tk.NORMAL)
    res_entry.config(state=tk.NORMAL)

def update_ui_for_service_started():
    start_btn.config(state=tk.DISABLED)
    stop_btn.config(state=tk.NORMAL)
    port_combobox.config(state=tk.DISABLED)
    refresh_port_btn.config(state=tk.DISABLED)
    res_entry.config(state=tk.DISABLED)

def update_mode_display(text):
    mode_status_label.config(text=text)
    if "互动" in text:
        mode_status_label.config(fg=COLORS["success"])
        _update_status_dot(COLORS["success"])
    elif "保护" in text:
        mode_status_label.config(fg=COLORS["warning"])
        _update_status_dot(COLORS["warning"])
    else:
        mode_status_label.config(fg=COLORS["danger"])
        _update_status_dot(COLORS["danger"])

def _update_status_dot(color):
    canvas = globals().get("status_dot_canvas")
    if canvas is not None:
        canvas.delete("all")
        canvas.create_oval(1, 1, 9, 9, fill=color, outline="")

def toggle_mouth():
    with state.lock:
        state.mouth_active = not state.mouth_active
        active = state.mouth_active
    if 'mouth_toggle' in globals() and mouth_toggle:
        mouth_toggle.set_active(active)
    config_data["mouth_active"] = active
    schedule_config_save()

def toggle_keyboard_mouth():
    with state.lock:
        state.keyboard_mouth_active = not state.keyboard_mouth_active
        active = state.keyboard_mouth_active
    if 'keyboard_mouth_toggle' in globals() and keyboard_mouth_toggle:
        keyboard_mouth_toggle.set_active(active)
    config_data["keyboard_mouth_active"] = active
    schedule_config_save()

def toggle_neck():
    with state.lock:
        state.neck_active = not state.neck_active
        active = state.neck_active
    if 'neck_toggle' in globals() and neck_toggle:
        neck_toggle.set_active(active)
    config_data["neck_active"] = active
    schedule_config_save()

def toggle_eye_input():
    with state.lock:
        state.eye_input_display_active = not state.eye_input_display_active
        active = state.eye_input_display_active
    if 'eye_input_toggle' in globals() and eye_input_toggle:
        eye_input_toggle.set_active(active)
    config_data["eye_input_display_active"] = active
    schedule_config_save()

def toggle_dlc():
    with state.lock:
        state.dlc_enabled = not state.dlc_enabled
        active = state.dlc_enabled
    if 'dlc_toggle' in globals() and dlc_toggle:
        dlc_toggle.set_active(active)
    config_data["dlc_enabled"] = active
    schedule_config_save()
    # 同步已打开的自定义按键窗口
    KeybindWindow.update_all_dlc_state(active)

def toggle_expr_auto_restore():
    with state.lock:
        state.expr_auto_restore = not state.expr_auto_restore
        active = state.expr_auto_restore
    config_data["expr_auto_restore"] = active
    schedule_config_save()
    # 同步已打开的自定义按键窗口
    KeybindWindow.update_all_auto_restore_state(active)

def toggle_eco_qos():
    """切换 EcoQoS 效率模式"""
    if not is_eco_qos_supported():
        return
    current = config_data.get("eco_qos_enabled", False)
    target = not current
    success = set_eco_qos(target)
    if success:
        config_data["eco_qos_enabled"] = target
        schedule_config_save()
    # 同步 UI 状态（显示实际生效状态）
    try:
        if eco_qos_toggle is not None:
            eco_qos_toggle.set_active(is_eco_qos_active())
    except (NameError, AttributeError):
        pass

def _sync_eco_qos_toggle():
    """同步 EcoQoS 开关 UI 状态与实际生效状态（供 init_tasks 后台线程调用）"""
    try:
        if eco_qos_toggle is not None:
            eco_qos_toggle.set_active(is_eco_qos_active())
    except (NameError, AttributeError):
        pass

def toggle_service_hotkey():
    with state.lock:
        active = state.service_active
    if active:
        _main_thread_call(manual_stop)
    else:
        _main_thread_call(manual_start)

def _handle_toggle_hotkey(action):
    if action == "toggle_mouth":
        toggle_mouth()
    elif action == "toggle_keyboard_mouth":
        toggle_keyboard_mouth()
    elif action == "toggle_neck":
        toggle_neck()
    elif action == "toggle_eye_input":
        toggle_eye_input()
    elif action == "toggle_service":
        toggle_service_hotkey()

def update_toggle_hotkey_labels():
    with state.lock:
        keybinds = state.keybinds.copy()
    toggle_widgets = {
        "toggle_mouth": "mouth_toggle",
        "toggle_keyboard_mouth": "keyboard_mouth_toggle",
        "toggle_neck": "neck_toggle",
        "toggle_eye_input": "eye_input_toggle",
    }
    g = globals()
    for action, widget_name in toggle_widgets.items():
        widget = g.get(widget_name)
        if widget is not None:
            hotkey = get_key_display(keybinds.get(action, ""))
            widget.set_hotkey_text(f"[{hotkey}]" if hotkey else "")

def refresh_ports():
    try:
        ports, ch340 = scan_serial_ports()
        port_combobox['values'] = ports

        saved_port = config_data.get("port", "").strip()
        if saved_port and saved_port in ports:
            port_combobox.set(saved_port)
        elif ch340:
            port_combobox.set(ch340)
        elif ports:
            port_combobox.set(ports[0])
        else:
            port_combobox.set("")
    except Exception as e:
        logger.warning(f"刷新串口失败: {e}")

def _get_work_area():
    try:
        rect = wintypes.RECT()
        user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
        return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        return 0, 0, win.winfo_screenwidth(), win.winfo_screenheight()

def place_window_right_of_main(win, width, height, offset_y=40):
    """将窗口放置在主窗口右侧；若右侧空间不足则放左侧；始终保证在屏幕内"""
    try:
        root.update_idletasks()
        main_x = root.winfo_rootx()
        main_y = root.winfo_rooty()
        main_w = root.winfo_width()
        main_h = root.winfo_height()

        wa_left, wa_top, wa_right, wa_bottom = _get_work_area()
        wa_w = wa_right - wa_left
        wa_h = wa_bottom - wa_top

        # 优先右侧
        new_x = main_x + main_w + 8
        new_y = main_y + offset_y
        if new_x + width > wa_right:
            # 右侧放不下，尝试左侧
            new_x = main_x - width - 8
        if new_x < wa_left:
            # 左侧也放不下，居中在屏幕内
            new_x = wa_left + (wa_w - width) // 2

        # Y 轴边界检查
        if new_y + height > wa_bottom:
            new_y = wa_bottom - height - 8
        if new_y < wa_top:
            new_y = wa_top + 8

        win.geometry(f"{width}x{height}+{new_x}+{new_y}")
    except Exception:
        win.geometry(f"{width}x{height}")

# ===================== 多屏幕分辨率选择窗口 =====================
class ResolutionSelectWindow:
    _active_instance = None

    @classmethod
    def get_or_create(cls, parent, callback):
        """单例：若已有打开的窗口则聚焦，否则新建"""
        if cls._active_instance is not None:
            inst = cls._active_instance
            try:
                if inst.win.winfo_exists():
                    inst.win.lift()
                    inst.win.focus_force()
                    return inst
            except Exception:
                pass
            cls._active_instance = None
        inst = cls(parent, callback)
        cls._active_instance = inst
        return inst

    def _clear_active(self):
        """窗口关闭时清理单例引用"""
        if ResolutionSelectWindow._active_instance is self:
            ResolutionSelectWindow._active_instance = None

    def __init__(self, parent, callback):
        self.callback = callback
        self.monitors = log_monitors_info()  # 检测并写日志
        self.win = tk.Toplevel(parent)
        self.win.title("选择屏幕分辨率")
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.configure(bg=COLORS["bg"])
        place_window_right_of_main(self.win, 440, 460, offset_y=60)

        try:
            if os.path.exists(ICON_FILE):
                self.win.iconbitmap(ICON_FILE)
        except Exception:
            pass

        tk.Label(self.win, text="🖥  检测到多个显示器", font=("思源真黑体", 13, "bold"),
                 fg=COLORS["accent"], bg=COLORS["bg"]).pack(pady=(14, 6))
        tk.Label(self.win, text=f"当前共 {len(self.monitors)} 块屏幕，请选择使用方式：",
                 font=("思源真黑体", 9), fg=COLORS["text_dim"], bg=COLORS["bg"]).pack(pady=(0, 10))

        card = tk.Frame(self.win, bg=COLORS["card"], padx=16, pady=12)
        card.pack(fill=tk.X, padx=18, pady=(0, 4))

        self.mode_var = tk.StringVar(value="extend")

        vox, voy, vw, vh = get_virtual_screen_bounds(self.monitors)

        tk.Radiobutton(card, text="扩展模式（推荐）", variable=self.mode_var, value="extend",
                       bg=COLORS["card"], fg=COLORS["text"], selectcolor=COLORS["bg"],
                       activebackground=COLORS["card"], font=("思源真黑体", 10),
                       command=self._update_info).pack(anchor="w", pady=4)
        self.extend_label = tk.Label(
            card,
            text=f"    虚拟桌面：{vw} × {vh}  （原点 {vox},{voy}）",
            bg=COLORS["card"], fg=COLORS["text_dim"], font=("思源真黑体", 9)
        )
        self.extend_label.pack(anchor="w")

        # 主屏信息
        pw, ph, pox, poy = 0, 0, 0, 0
        for m in self.monitors:
            if m["is_primary"]:
                pw, ph, pox, poy = m["width"], m["height"], m["x"], m["y"]
                break
        if pw == 0 and self.monitors:
            m0 = self.monitors[0]
            pw, ph, pox, poy = m0["width"], m0["height"], m0["x"], m0["y"]

        tk.Radiobutton(card, text="仅使用主屏幕", variable=self.mode_var, value="primary",
                       bg=COLORS["card"], fg=COLORS["text"], selectcolor=COLORS["bg"],
                       activebackground=COLORS["card"], font=("思源真黑体", 10),
                       command=self._update_info).pack(anchor="w", pady=(12, 4))
        self.primary_label = tk.Label(
            card,
            text=f"    主屏幕：{pw} × {ph}  （位置 {pox},{poy}）",
            bg=COLORS["card"], fg=COLORS["text_dim"], font=("思源真黑体", 9)
        )
        self.primary_label.pack(anchor="w")

        tk.Radiobutton(card, text="指定某一块屏幕", variable=self.mode_var, value="specific",
                       bg=COLORS["card"], fg=COLORS["text"], selectcolor=COLORS["bg"],
                       activebackground=COLORS["card"], font=("思源真黑体", 10),
                       command=self._update_info).pack(anchor="w", pady=(12, 4))

        self.monitor_var = tk.IntVar(value=0)
        self.monitor_frame = tk.Frame(card, bg=COLORS["card"])
        self.monitor_frame.pack(anchor="w", padx=20, pady=4)

        for idx, m in enumerate(self.monitors):
            primary_tag = "（主）" if m["is_primary"] else ""
            text = f"屏幕 {idx+1}{primary_tag}：{m['width']}×{m['height']} @({m['x']},{m['y']})"
            tk.Radiobutton(self.monitor_frame, text=text, variable=self.monitor_var, value=idx,
                           bg=COLORS["card"], fg=COLORS["text_dim"], selectcolor=COLORS["bg"],
                           activebackground=COLORS["card"], font=("思源真黑体", 9)).pack(anchor="w")

        btn_frame = tk.Frame(self.win, bg=COLORS["bg"])
        btn_frame.pack(fill=tk.X, pady=10, padx=18)

        def on_cancel():
            w, h = get_primary_resolution()
            ox, oy = 0, 0
            for m in self.monitors:
                if m["is_primary"]:
                    ox, oy = m["x"], m["y"]
                    break
            try:
                self.callback(f"{w}x{h}", ox, oy)
            except TypeError:
                self.callback(f"{w}x{h}")
            self._clear_active()
            self.win.destroy()

        tk.Button(btn_frame, text="取消", command=on_cancel,
                  bg=COLORS["btn"], fg=COLORS["text"], relief=tk.FLAT,
                  font=("思源真黑体", 10), cursor="hand2", width=10).pack(side=tk.LEFT)

        tk.Button(btn_frame, text="确定", command=self._confirm,
                  bg=COLORS["accent"], fg="#0A0E1A", relief=tk.FLAT,
                  font=("思源真黑体", 10, "bold"), cursor="hand2", width=10).pack(side=tk.RIGHT)

        self._update_info()
        self.win.protocol("WM_DELETE_WINDOW", on_cancel)

    def _update_info(self):
        state = "normal" if self.mode_var.get() == "specific" else "disabled"
        for child in self.monitor_frame.winfo_children():
            child.configure(state=state)

    def _confirm(self):
        mode = self.mode_var.get()
        if mode == "extend":
            # 直接用已检测到的 monitors 计算，避免再调 SystemMetrics
            ox, oy, w, h = get_virtual_screen_bounds(self.monitors)
        elif mode == "primary":
            w, h, ox, oy = 0, 0, 0, 0
            for m in self.monitors:
                if m["is_primary"]:
                    w, h, ox, oy = m["width"], m["height"], m["x"], m["y"]
                    break
            if w == 0 and self.monitors:
                m = self.monitors[0]
                w, h, ox, oy = m["width"], m["height"], m["x"], m["y"]
        else:
            idx = self.monitor_var.get()
            if idx < 0 or idx >= len(self.monitors):
                idx = 0
            m = self.monitors[idx]
            w, h = m["width"], m["height"]
            ox, oy = m["x"], m["y"]

        logger.error(f"[分辨率] 选择确认: mode={mode}, res={w}x{h}, origin=({ox},{oy})")
        self.callback(f"{w}x{h}", ox, oy)
        self._clear_active()
        self.win.destroy()

# ===================== 按键自定义窗口 =====================
class KeybindWindow:
    _active_instances = []

    def __init__(self, parent):
        self.win = tk.Toplevel(parent)
        self.win.title("自定义按键")
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.configure(bg=COLORS["bg"])
        place_window_right_of_main(self.win, 580, 680, offset_y=15)
        self._closing = False
        try:
            if os.path.exists(ICON_FILE):
                self.win.iconbitmap(ICON_FILE)
        except Exception:
            pass

        tk.Label(self.win, text="⌨  自定义按键绑定", font=("思源真黑体", 14, "bold"),
                 fg=COLORS["accent"], bg=COLORS["bg"]).pack(pady=(14, 2))
        tk.Label(self.win, text="点击「修改」后按下新按键即可绑定（支持键盘组合键、鼠标按键、滚轮，Esc 取消）",
                 font=("思源真黑体", 9), fg=COLORS["text_dim"], bg=COLORS["bg"]).pack(pady=(0, 6))

        # ---- 可滚动区域 ----
        scroll_outer = tk.Frame(self.win, bg=COLORS["bg"])
        scroll_outer.pack(fill=tk.BOTH, expand=True, padx=16)

        self._canvas = tk.Canvas(scroll_outer, bg=COLORS["bg"], highlightthickness=0,
                                 width=540, height=460)
        sb = ttk.Scrollbar(scroll_outer, orient="vertical", command=self._canvas.yview)
        self._scroll_inner = tk.Frame(self._canvas, bg=COLORS["bg"])

        self._inner_win = self._canvas.create_window((0, 0), window=self._scroll_inner,
                                                      anchor="nw", width=540)
        self._scroll_inner.bind("<Configure>",
                                lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.configure(yscrollcommand=sb.set)

        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfig(self._inner_win, width=e.width))

        self.action_labels = {
            "expression": "切换表情", "neck_left": "脖子左转", "neck_right": "脖子右转",
            "mouth_up": "嘴巴上", "mouth_down": "嘴巴下", "heart": "显示爱心 ❤",
            "space": "空格动作", "backspace": "退格动作", "enter": "回车动作",
            "blink": "眨眼 👁",
            "toggle_mouth": "开关：嘴巴控制", "toggle_keyboard_mouth": "开关：打字互动",
            "toggle_neck": "开关：脖子控制", "toggle_eye_input": "开关：眼睛显示输入",
            "toggle_service": "开关：启动/停止服务",
            # ---- 新增表情快捷键 ----
            "expr_sleepy": "表情：昏睡 😴", "expr_question": "表情：问号 ❓",
            "expr_heart_beat": "表情：跳动爱心 💓", "expr_squint": "表情：眯眼 😏",
            "expr_exclamation": "表情：感叹号 ❗", "expr_dizziness": "表情：眩晕 😵",
            "expr_mosquito": "表情：蚊香眩晕 🌀", "neck_reset": "脖子回正",
        }
        self.toggle_action_keys = {
            "toggle_mouth", "toggle_keyboard_mouth", "toggle_neck",
            "toggle_eye_input", "toggle_service",
        }
        self.expr_action_keys = set(EXPR_KEYBIND_ACTIONS)
        self.key_labels = {}
        self.modify_btns = {}
        self.clear_btns = {}

        with state.lock:
            binds = state.keybinds.copy()
            self.dlc_on = state.dlc_enabled
            self.auto_restore_on = state.expr_auto_restore

        self._add_section_header(self._scroll_inner, "互动按键")
        for action, name in self.action_labels.items():
            if action not in self.toggle_action_keys and action not in self.expr_action_keys:
                self._add_keybind_row(self._scroll_inner, action, name, binds)

        expr_header_text = "表情快捷键" + ("" if self.dlc_on else "（需开启附加DLC功能）")
        self._add_section_header(self._scroll_inner, expr_header_text)
        self._add_section_header(self._scroll_inner, "※ DLC快捷键必须使用组合键（如 Shift+M）")
        for action, name in self.action_labels.items():
            if action in self.expr_action_keys:
                self._add_keybind_row(self._scroll_inner, action, name, binds)

        # ---- 自动恢复表情开关 ----
        self.auto_restore_toggle = ModernToggle(
            self._scroll_inner, "自动恢复表情",
            callback=toggle_expr_auto_restore,
            active=self.auto_restore_on, bg=COLORS["card"]
        )
        self.auto_restore_toggle.pack(fill=tk.X, pady=2)

        self._apply_dlc_state()

        self._add_section_header(self._scroll_inner, "快捷开关热键")
        for action, name in self.action_labels.items():
            if action in self.toggle_action_keys:
                self._add_keybind_row(self._scroll_inner, action, name, binds)

        # 底部间距
        tk.Frame(self._scroll_inner, bg=COLORS["bg"], height=8).pack()

        bottom = tk.Frame(self.win, bg=COLORS["bg"])
        bottom.pack(fill=tk.X, side=tk.BOTTOM, pady=10, padx=16)

        tk.Button(bottom, text="恢复默认", command=self.reset_defaults,
                  bg=COLORS["btn"], fg=COLORS["text"], relief=tk.FLAT,
                  font=("思源真黑体", 10), cursor="hand2", width=12).pack(side=tk.LEFT)
        tk.Button(bottom, text="完成", command=self.on_close,
                  bg=COLORS["accent"], fg="#0A0E1A", relief=tk.FLAT,
                  font=("思源真黑体", 10, "bold"), cursor="hand2", width=12).pack(side=tk.RIGHT)

        self.listening_label = tk.Label(self.win, text="", bg=COLORS["bg"],
                                        fg=COLORS["warning"], font=("思源真黑体", 10))
        self.listening_label.pack(side=tk.BOTTOM, pady=(2, 4))
        try:
            root._keybind_hint_label = self.listening_label
        except Exception:
            pass
        self.win.protocol("WM_DELETE_WINDOW", self.on_close)
        KeybindWindow._active_instances.append(self)

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _add_section_header(self, parent, text):
        hdr = tk.Frame(parent, bg=COLORS["bg_secondary"],
                       highlightbackground=COLORS["border"], highlightthickness=1)
        hdr.pack(fill=tk.X, pady=(10, 4))
        tk.Label(hdr, text=f"  {text}", bg=COLORS["bg_secondary"], fg=COLORS["accent"],
                 font=("思源真黑体", 10, "bold"), padx=12, pady=5).pack(anchor="w")

    def _add_keybind_row(self, parent, action, name, binds):
        row = tk.Frame(parent, bg=COLORS["card"], height=42)
        row.pack(fill=tk.X, pady=2)
        row.pack_propagate(False)

        tk.Label(row, text=name, bg=COLORS["card"], fg=COLORS["text"],
                 font=("思源真黑体", 10), width=14, anchor="w").pack(side=tk.LEFT, padx=12)

        # 键盘键样式显示
        key_box = tk.Frame(row, bg=COLORS["bg_secondary"],
                           highlightbackground=COLORS["border_light"],
                           highlightthickness=1, relief=tk.RAISED)
        key_box.pack(side=tk.LEFT, padx=(0, 8))
        current = binds.get(action, "")
        display_text = get_key_display(current) if current else "未绑定"
        lbl = tk.Label(key_box, text=display_text,
                       bg=COLORS["bg_secondary"],
                       fg=COLORS["accent"] if current else COLORS["text_muted"],
                       font=("Consolas", 10, "bold"), padx=12, pady=4, width=10)
        lbl.pack()
        self.key_labels[action] = lbl

        btn = tk.Button(row, text="  修改  ", bg=COLORS["btn"], fg=COLORS["text"],
                        activebackground=COLORS["btn_hover"], relief=tk.FLAT,
                        font=("思源真黑体", 9), cursor="hand2",
                        command=lambda a=action: self.start_binding(a))
        btn.pack(side=tk.RIGHT, padx=(4, 12))
        self.modify_btns[action] = btn

        clr_btn = tk.Button(row, text=" 清除 ", bg=COLORS["btn"], fg=COLORS["text_dim"],
                            activebackground=COLORS["btn_hover"], relief=tk.FLAT,
                            font=("思源真黑体", 9), cursor="hand2",
                            command=lambda a=action: self.clear_binding(a))
        clr_btn.pack(side=tk.RIGHT, padx=(0, 0))
        self.clear_btns[action] = clr_btn

    def _apply_dlc_state(self):
        """根据 DLC 开关状态启用/禁用表情快捷键的修改和清除按钮"""
        btn_state = tk.NORMAL if self.dlc_on else tk.DISABLED
        for action in self.expr_action_keys:
            if action in self.modify_btns:
                self.modify_btns[action].config(state=btn_state)
            if action in self.clear_btns:
                self.clear_btns[action].config(state=btn_state)

    @classmethod
    def get_or_create(cls, parent):
        for inst in cls._active_instances:
            try:
                if inst.win.winfo_exists():
                    inst.win.lift()
                    inst.win.focus_force()
                    return inst
            except Exception:
                pass
            cls._active_instances.remove(inst)
        return cls(parent)

    @classmethod
    def update_all_dlc_state(cls, dlc_on):
        """DLC 开关切换时同步所有已打开的 KeybindWindow"""
        for inst in cls._active_instances:
            inst.dlc_on = dlc_on
            inst._apply_dlc_state()

    @classmethod
    def update_all_auto_restore_state(cls, auto_restore_on):
        """自动恢复表情开关切换时同步所有已打开的 KeybindWindow"""
        for inst in cls._active_instances:
            inst.auto_restore_on = auto_restore_on
            try:
                if inst.win.winfo_exists() and hasattr(inst, 'auto_restore_toggle'):
                    inst.auto_restore_toggle.set_active(auto_restore_on)
            except Exception:
                pass

    def start_binding(self, action):
        with state.lock:
            state.binding_mode = True
            state.binding_callback = lambda ks: self.on_key_captured(action, ks)
            state.pressed_modifiers.clear()
        # 启动鼠标钩子以支持鼠标按键/滚轮绑定（加锁防止与 sync_input_hooks 竞争）
        with _hooks_lock:
            _start_mouse_hook()
        self.listening_label.config(
            text=f"请按下【{self.action_labels[action]}】的新按键（键盘/鼠标/滚轮均可，Esc 取消）"
        )
        for b in self.modify_btns.values():
            b.config(state=tk.DISABLED)
        for b in self.clear_btns.values():
            b.config(state=tk.DISABLED)

    def on_key_captured(self, action, key_str):
        # 窗口已关闭时丢弃回调，防止访问已销毁的控件导致崩溃
        if self._closing or not self.win.winfo_exists():
            return
        if key_str == "esc":
            self.listening_label.config(text="已取消")
            self._restore()
            return
        if key_str in MODIFIER_KEYS:
            self.listening_label.config(text="请再按一个主键（不能只绑定 Shift/Ctrl/Alt）")
            with state.lock:
                state.binding_mode = True
                state.binding_callback = lambda ks: self.on_key_captured(action, ks)
            return
        # DLC 表情快捷键必须使用组合键（含 Shift/Ctrl/Alt），禁止绑定单个字母/数字键
        if action in self.expr_action_keys and "+" not in key_str:
            self.listening_label.config(text="DLC快捷键必须使用组合键（如 Shift+M），请点击「修改」重新绑定")
            self._restore()
            return
        # 冲突检测：先在锁内查找冲突，锁外更新 GUI，避免死锁
        conflict_act = None
        with state.lock:
            for act, k in state.keybinds.items():
                if act != action and k == key_str:
                    conflict_act = act
                    break
            if conflict_act is None:
                state.keybinds[action] = key_str
                config_data["keybinds"] = state.keybinds.copy()
        if conflict_act is not None:
            self.listening_label.config(
                text=f"按键已被【{self.action_labels.get(conflict_act)}】占用"
            )
            # 清除残留修饰键，防止后续组合键判定出错
            with state.lock:
                state.binding_mode = True
                state.binding_callback = lambda ks: self.on_key_captured(action, ks)
                state.pressed_modifiers.clear()
            return
        ConfigManager.save(config_data)
        self.key_labels[action].config(text=get_key_display(key_str), fg=COLORS["accent"])
        self.listening_label.config(text=f"已绑定：{get_key_display(key_str)}")
        update_toggle_hotkey_labels()
        self._restore()

    def clear_binding(self, action):
        with state.lock:
            state.keybinds[action] = ""
            config_data["keybinds"] = state.keybinds.copy()
        ConfigManager.save(config_data)
        self.key_labels[action].config(text="未绑定", fg=COLORS["text_muted"])
        self.listening_label.config(text=f"已清除【{self.action_labels[action]}】的绑定")
        update_toggle_hotkey_labels()

    def _restore(self):
        for action, b in self.modify_btns.items():
            if action in self.expr_action_keys and not self.dlc_on:
                b.config(state=tk.DISABLED)
            else:
                b.config(state=tk.NORMAL)
        for action, b in self.clear_btns.items():
            if action in self.expr_action_keys and not self.dlc_on:
                b.config(state=tk.DISABLED)
            else:
                b.config(state=tk.NORMAL)
        with state.lock:
            state.binding_mode = False
            state.binding_callback = None
            state.pressed_modifiers.clear()
        # 恢复钩子到正常状态
        sync_input_hooks()

    def reset_defaults(self):
        if messagebox.askyesno("确认", "确定恢复所有默认按键？"):
            with state.lock:
                if self.dlc_on:
                    state.keybinds = DEFAULT_KEYBINDS.copy()
                else:
                    # DLC 关闭时保留表情快捷键的当前绑定
                    new_binds = DEFAULT_KEYBINDS.copy()
                    for a in self.expr_action_keys:
                        new_binds[a] = state.keybinds.get(a, "")
                    state.keybinds = new_binds
                config_data["keybinds"] = state.keybinds.copy()
            ConfigManager.save(config_data)
            for a, lbl in self.key_labels.items():
                val = state.keybinds.get(a, DEFAULT_KEYBINDS[a])
                if val:
                    lbl.config(text=get_key_display(val), fg=COLORS["accent"])
                else:
                    lbl.config(text="未绑定", fg=COLORS["text_muted"])
            self.listening_label.config(text="已恢复默认")
            update_toggle_hotkey_labels()

    def on_close(self):
        self._closing = True
        if self in KeybindWindow._active_instances:
            KeybindWindow._active_instances.remove(self)
        with state.lock:
            state.binding_mode = False
            state.binding_callback = None
            state.pressed_modifiers.clear()
        try:
            self._canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass
        try:
            if hasattr(root, "_keybind_hint_label"):
                root._keybind_hint_label = None
        except Exception:
            pass
        # 恢复钩子到正常状态
        sync_input_hooks()
        update_toggle_hotkey_labels()
        self.win.destroy()

# ===================== 游戏防护进程管理窗口 =====================
class ProcessManagerWindow:
    _instance = None

    def __init__(self, parent):
        self.win = tk.Toplevel(parent)
        self.win.title("游戏防护进程管理")
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.configure(bg=COLORS["bg"])
        place_window_right_of_main(self.win, 440, 620, offset_y=15)

        try:
            if os.path.exists(ICON_FILE):
                self.win.iconbitmap(ICON_FILE)
        except Exception:
            pass

        tk.Label(self.win, text="🎮  游戏防护进程管理", font=("思源真黑体", 13, "bold"),
                 fg=COLORS["accent"], bg=COLORS["bg"]).pack(pady=(10, 4))

        tk.Label(self.win, text="列表中的进程运行时将自动关闭监听", font=("思源真黑体", 8),
                 fg=COLORS["text_dim"], bg=COLORS["bg"]).pack(pady=(0, 6))

        # ---- 进程列表 ----
        list_card = tk.Frame(self.win, bg=COLORS["card"], padx=10, pady=8)
        list_card.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 4))

        legend_row = tk.Frame(list_card, bg=COLORS["card"])
        legend_row.pack(fill=tk.X, pady=(0, 4))
        tk.Label(legend_row, text="● 内置", font=("思源真黑体", 8),
                 fg=COLORS["accent"], bg=COLORS["card"]).pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(legend_row, text="● 自定义", font=("思源真黑体", 8),
                 fg=COLORS["success"], bg=COLORS["card"]).pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(legend_row, text="● 已禁用", font=("思源真黑体", 8),
                 fg=COLORS["text_muted"], bg=COLORS["card"]).pack(side=tk.LEFT)

        list_frame = tk.Frame(list_card, bg=COLORS["bg_secondary"], bd=0, highlightthickness=1,
                              highlightbackground=COLORS["border"])
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.proc_listbox = tk.Listbox(list_frame, bg=COLORS["bg_secondary"], fg=COLORS["text"],
                                       selectbackground=COLORS["accent_dim"],
                                       selectforeground="#FFFFFF",
                                       font=("Consolas", 9), bd=0, height=14,
                                       highlightthickness=0, exportselection=False)
        self.proc_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.proc_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.proc_listbox.config(yscrollcommand=scrollbar.set)

        self._refresh_list()

        # ---- 操作按钮 ----
        btn_row1 = tk.Frame(self.win, bg=COLORS["bg"])
        btn_row1.pack(fill=tk.X, padx=16, pady=(4, 4))

        RoundedButton(btn_row1, text="🗑  删除/禁用", command=self._remove_selected,
                      width=130, height=32, radius=10,
                      bg=COLORS["danger"], fg="#FFFFFF",
                      hover_bg="#DC2626", font=("思源真黑体", 9, "bold"),
                      canvas_bg=COLORS["bg"]).pack(side=tk.LEFT, padx=(0, 6))

        RoundedButton(btn_row1, text="♻  恢复选中", command=self._restore_selected,
                      width=130, height=32, radius=10,
                      bg=COLORS["warning"], fg="#0A0E1A",
                      hover_bg="#D97706", font=("思源真黑体", 9, "bold"),
                      canvas_bg=COLORS["bg"]).pack(side=tk.LEFT)

        # ---- 添加进程输入框 ----
        add_card = tk.Frame(self.win, bg=COLORS["card"], padx=10, pady=8)
        add_card.pack(fill=tk.X, padx=16, pady=(4, 4))

        tk.Label(add_card, text="手动添加进程名：", font=("思源真黑体", 9, "bold"),
                 fg=COLORS["text"], bg=COLORS["card"]).pack(anchor="w", pady=(0, 4))

        input_row = tk.Frame(add_card, bg=COLORS["card"])
        input_row.pack(fill=tk.X)

        self.entry_var = tk.StringVar()
        entry = tk.Entry(input_row, textvariable=self.entry_var,
                         font=("Consolas", 10), bg=COLORS["bg_secondary"], fg=COLORS["text"],
                         insertbackground=COLORS["text"], bd=0, highlightthickness=1,
                         highlightbackground=COLORS["border"], highlightcolor=COLORS["accent"])
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        entry.bind("<Return>", lambda e: self._add_from_entry())

        tk.Label(add_card, text="（含或不含 .exe 均可）", font=("思源真黑体", 7),
                 fg=COLORS["text_muted"], bg=COLORS["card"]).pack(anchor="w", pady=(2, 0))

        btn_row2 = tk.Frame(add_card, bg=COLORS["card"])
        btn_row2.pack(fill=tk.X, pady=(4, 0))
        RoundedButton(btn_row2, text="➕  添加", command=self._add_from_entry,
                      width=100, height=30, radius=8,
                      bg=COLORS["success"], fg="#FFFFFF",
                      hover_bg="#059669", font=("思源真黑体", 9, "bold"),
                      canvas_bg=COLORS["card"]).pack(side=tk.LEFT, padx=(0, 6))
        RoundedButton(btn_row2, text="📋  从运行中选择", command=self._select_from_running,
                      width=140, height=30, radius=8,
                      bg=COLORS["accent_dim"], fg="#FFFFFF",
                      hover_bg=COLORS["accent"], font=("思源真黑体", 9, "bold"),
                      canvas_bg=COLORS["card"]).pack(side=tk.LEFT)

        # ---- 关闭按钮 ----
        RoundedButton(self.win, text="关闭", command=self.on_close,
                      width=120, height=34, radius=10,
                      bg=COLORS["btn"], fg=COLORS["text"],
                      hover_bg=COLORS["btn_hover"], font=("思源真黑体", 10),
                      canvas_bg=COLORS["bg"]).pack(pady=(6, 12))

        self.win.protocol("WM_DELETE_WINDOW", self.on_close)
        ProcessManagerWindow._instance = self

    def _get_custom_list(self):
        lst = config_data.get("custom_blocking_processes", [])
        if not isinstance(lst, list):
            lst = []
        return [p.strip() for p in lst if p.strip()]

    def _save_custom_list(self, lst):
        config_data["custom_blocking_processes"] = lst
        ConfigManager.save(config_data)

    def _get_disabled_list(self):
        lst = config_data.get("disabled_builtin_processes", [])
        if not isinstance(lst, list):
            lst = []
        return [p.strip().lower() for p in lst if p.strip()]

    def _save_disabled_list(self, lst):
        config_data["disabled_builtin_processes"] = lst
        ConfigManager.save(config_data)

    def _refresh_list(self):
        self.proc_listbox.delete(0, tk.END)
        self._entries = []

        custom = self._get_custom_list()
        custom_set = frozenset(p.lower() for p in custom)
        disabled = set(self._get_disabled_list())

        builtin_all = sorted(MONITOR_PROCESSES + ANTI_CHEAT_PROCESSES, key=str.lower)
        for p in builtin_all:
            pl = p.lower()
            if pl in disabled:
                self.proc_listbox.insert(tk.END, f"  {p}  [已禁用]")
                self.proc_listbox.itemconfig(tk.END, fg=COLORS["text_muted"])
                self._entries.append(("builtin_disabled", p))
            else:
                self.proc_listbox.insert(tk.END, f"  {p}")
                self.proc_listbox.itemconfig(tk.END, fg=COLORS["accent"])
                self._entries.append(("builtin", p))

        for p in sorted(custom, key=str.lower):
            if p.lower() not in (b.lower() for b in (MONITOR_PROCESSES + ANTI_CHEAT_PROCESSES)):
                self.proc_listbox.insert(tk.END, f"  {p}  [自定义]")
                self.proc_listbox.itemconfig(tk.END, fg=COLORS["success"])
                self._entries.append(("custom", p))

    def _add_from_entry(self):
        name = self.entry_var.get().strip()
        if not name:
            return
        if not name.lower().endswith(".exe"):
            name = name + ".exe"
        lst = self._get_custom_list()
        if name.lower() in (p.lower() for p in lst):
            messagebox.showinfo("提示", f"{name} 已在列表中", parent=self.win)
            return
        lst.append(name)
        self._save_custom_list(lst)
        self.entry_var.set("")
        self._refresh_list()

    def _remove_selected(self):
        sel = self.proc_listbox.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选择一个进程", parent=self.win)
            return
        idx = sel[0]
        kind, name = self._entries[idx]
        if kind == "custom":
            lst = self._get_custom_list()
            for i, p in enumerate(lst):
                if p.lower() == name.lower():
                    del lst[i]
                    break
            self._save_custom_list(lst)
        elif kind == "builtin":
            dis = self._get_disabled_list()
            if name.lower() not in dis:
                dis.append(name.lower())
            self._save_disabled_list(dis)
        elif kind == "builtin_disabled":
            messagebox.showinfo("提示", "该进程已禁用，可使用「恢复选中」重新启用", parent=self.win)
            return
        self._refresh_list()

    def _restore_selected(self):
        sel = self.proc_listbox.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选择一个进程", parent=self.win)
            return
        idx = sel[0]
        kind, name = self._entries[idx]
        if kind == "builtin_disabled":
            dis = self._get_disabled_list()
            dis = [p for p in dis if p != name.lower()]
            self._save_disabled_list(dis)
        elif kind == "custom":
            messagebox.showinfo("提示", "自定义进程无需恢复，如需删除请使用「删除/禁用」", parent=self.win)
            return
        elif kind == "builtin":
            messagebox.showinfo("提示", "该内置进程已启用，无需恢复", parent=self.win)
            return
        self._refresh_list()

    def _select_from_running(self):
        # 已有打开的选择窗口则聚焦，不重复打开
        if hasattr(self, '_sel_win') and self._sel_win is not None:
            try:
                if self._sel_win.winfo_exists():
                    self._sel_win.lift()
                    self._sel_win.focus_force()
                    return
            except Exception:
                pass
            self._sel_win = None
        try:
            procs = set()
            for p in psutil.process_iter(['name']):
                pname = p.info.get('name') or ""
                if pname:
                    procs.add(pname)
            running = sorted(procs, key=str.lower)
        except Exception as e:
            messagebox.showerror("错误", f"获取进程列表失败：\n{e}", parent=self.win)
            return

        sel_win = tk.Toplevel(self.win)
        self._sel_win = sel_win
        sel_win.title("选择运行中的进程")
        sel_win.resizable(False, False)
        sel_win.transient(self.win)
        sel_win.configure(bg=COLORS["bg"])
        sel_win.geometry("360x460")

        # 居中到父窗口（设置窗口）上，确保不会跑出屏幕
        sel_win.update_idletasks()
        try:
            parent_x = self.win.winfo_rootx()
            parent_y = self.win.winfo_rooty()
            parent_w = self.win.winfo_width()
            parent_h = self.win.winfo_height()
            pop_x = parent_x + (parent_w - 360) // 2
            pop_y = parent_y + (parent_h - 460) // 2
            wa_left, wa_top, wa_right, wa_bottom = _get_work_area()
            pop_x = max(wa_left + 8, min(pop_x, wa_right - 360 - 8))
            pop_y = max(wa_top + 8, min(pop_y, wa_bottom - 460 - 8))
            sel_win.geometry(f"360x460+{pop_x}+{pop_y}")
        except Exception:
            pass

        try:
            if os.path.exists(ICON_FILE):
                sel_win.iconbitmap(ICON_FILE)
        except Exception:
            pass

        tk.Label(sel_win, text="选择要添加的进程：", font=("思源真黑体", 10, "bold"),
                 fg=COLORS["accent"], bg=COLORS["bg"]).pack(pady=(8, 4))

        search_var = tk.StringVar()
        search_entry = tk.Entry(sel_win, textvariable=search_var,
                                font=("Consolas", 10), bg=COLORS["bg_secondary"], fg=COLORS["text"],
                                insertbackground=COLORS["text"], bd=0, highlightthickness=1,
                                highlightbackground=COLORS["border"], highlightcolor=COLORS["accent"])
        search_entry.pack(fill=tk.X, padx=16, ipady=3)
        search_entry.insert(0, "搜索...")
        search_entry.bind("<FocusIn>", lambda e: search_entry.delete(0, tk.END) if search_var.get() == "搜索..." else None)

        list_frame = tk.Frame(sel_win, bg=COLORS["bg_secondary"], bd=0, highlightthickness=1,
                              highlightbackground=COLORS["border"])
        list_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=6)

        proc_lb = tk.Listbox(list_frame, bg=COLORS["bg_secondary"], fg=COLORS["text"],
                             selectbackground=COLORS["accent_dim"], selectforeground="#FFFFFF",
                             font=("Consolas", 9), bd=0, highlightthickness=0,
                             exportselection=False)
        proc_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=proc_lb.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        proc_lb.config(yscrollcommand=sb.set)

        def populate(filter_text=""):
            proc_lb.delete(0, tk.END)
            ft = filter_text.lower().strip()
            for pname in running:
                if not ft or ft in pname.lower():
                    proc_lb.insert(tk.END, pname)

        populate()

        def on_search(*_):
            populate(search_var.get())

        search_var.trace_add("write", on_search)

        def on_add():
            sel = proc_lb.curselection()
            if not sel:
                messagebox.showinfo("提示", "请先选择一个进程", parent=sel_win)
                return
            name = proc_lb.get(sel[0])
            lst = self._get_custom_list()
            if name.lower() in (p.lower() for p in lst):
                messagebox.showinfo("提示", f"{name} 已在列表中", parent=sel_win)
                return
            lst.append(name)
            self._save_custom_list(lst)
            self._refresh_list()
            self._close_sel_win()

        def close_sel():
            self._close_sel_win()

        btn_frame = tk.Frame(sel_win, bg=COLORS["bg"])
        btn_frame.pack(fill=tk.X, padx=16, pady=(0, 10))
        RoundedButton(btn_frame, text="➕  添加选中", command=on_add,
                      width=140, height=32, radius=8,
                      bg=COLORS["success"], fg="#FFFFFF",
                      hover_bg="#059669", font=("思源真黑体", 9, "bold"),
                      canvas_bg=COLORS["bg"]).pack(side=tk.LEFT, padx=(0, 6))
        RoundedButton(btn_frame, text="取消", command=close_sel,
                      width=80, height=32, radius=8,
                      bg=COLORS["btn"], fg=COLORS["text"],
                      hover_bg=COLORS["btn_hover"], font=("思源真黑体", 9),
                      canvas_bg=COLORS["bg"]).pack(side=tk.LEFT)

        sel_win.protocol("WM_DELETE_WINDOW", close_sel)
        proc_lb.bind("<Double-Button-1>", lambda e: on_add())

    def _close_sel_win(self):
        if hasattr(self, '_sel_win') and self._sel_win is not None:
            try:
                self._sel_win.destroy()
            except Exception:
                pass
            self._sel_win = None

    def on_close(self):
        self._close_sel_win()
        ProcessManagerWindow._instance = None
        self.win.destroy()

    @classmethod
    def get_or_create(cls, parent):
        """单例：若已有打开的窗口则聚焦，否则新建"""
        if cls._instance is not None:
            try:
                if cls._instance.win.winfo_exists():
                    cls._instance.win.lift()
                    cls._instance.win.focus_force()
                    return cls._instance
            except Exception:
                pass
            cls._instance = None
        return cls(parent)

# ===================== 设置窗口 =====================
class SettingsWindow:
    _instance = None

    def __init__(self, parent):
        self.win = tk.Toplevel(parent)
        self.win.title("设置")
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.configure(bg=COLORS["bg"])
        place_window_right_of_main(self.win, 280, 260, offset_y=40)

        try:
            if os.path.exists(ICON_FILE):
                self.win.iconbitmap(ICON_FILE)
        except Exception:
            pass

        tk.Label(self.win, text="⚙  偏好设置", font=("思源真黑体", 12, "bold"),
                 fg=COLORS["accent"], bg=COLORS["bg"]).pack(pady=(10, 6))

        card = tk.Frame(self.win, bg=COLORS["card"], padx=14, pady=10)
        card.pack(fill=tk.BOTH, expand=True, padx=16)

        self.auto_start_var = tk.BooleanVar(value=config_data.get("auto_start", False))
        self.auto_interact_var = tk.BooleanVar(value=config_data.get("auto_interact", True))
        self.auto_center_var = tk.BooleanVar(value=config_data.get("auto_center_eyes", True))

        def add_check(var, text, cmd):
            row = tk.Frame(card, bg=COLORS["card"])
            row.pack(fill=tk.X, expand=True)
            ttk.Checkbutton(row, variable=var, text=text, style="Tech.TCheckbutton", command=cmd).pack(side=tk.LEFT, anchor="w")

        def on_start():
            config_data["auto_start"] = self.auto_start_var.get()
            ConfigManager.save(config_data)
            ConfigManager.set_auto_start(self.auto_start_var.get())

        def on_interact():
            config_data["auto_interact"] = self.auto_interact_var.get()
            ConfigManager.save(config_data)

        def on_center():
            with state.lock:
                state.auto_center_eyes = self.auto_center_var.get()
            config_data["auto_center_eyes"] = self.auto_center_var.get()
            ConfigManager.save(config_data)

        add_check(self.auto_start_var, "加入开机自动启动", on_start)
        add_check(self.auto_interact_var, "启动时自动打开互动", on_interact)
        add_check(self.auto_center_var, "眼球自动居中", on_center)

        # 自定义按键按钮：圆角居中
        RoundedButton(self.win, text="⌨  自定义按键",
                      command=lambda: KeybindWindow.get_or_create(self.win),
                      width=220, height=38, radius=12,
                      bg=COLORS["accent"], fg="#0A0E1A",
                      hover_bg=COLORS["accent_dim"],
                      font=("思源真黑体", 11, "bold"),
                      canvas_bg=COLORS["bg"]).pack(pady=(8, 4))

        # 游戏防护进程管理按钮
        RoundedButton(self.win, text="🎮  游戏防护进程管理",
                      command=lambda: ProcessManagerWindow.get_or_create(self.win),
                      width=220, height=38, radius=12,
                      bg=COLORS["btn"], fg=COLORS["text"],
                      hover_bg=COLORS["btn_hover"],
                      font=("思源真黑体", 11, "bold"),
                      canvas_bg=COLORS["bg"]).pack(pady=(4, 4))

        tk.Label(self.win, text="* 所有设置已自动保存", font=("思源真黑体", 8),
                 fg=COLORS["text_dim"], bg=COLORS["bg"]).pack(pady=(0, 10))
        self.win.protocol("WM_DELETE_WINDOW", self.on_close)
        SettingsWindow._instance = self

    def on_close(self):
        SettingsWindow._instance = None
        self.win.destroy()

def open_settings():
    if SettingsWindow._instance is not None:
        try:
            if SettingsWindow._instance.win.winfo_exists():
                SettingsWindow._instance.win.lift()
                SettingsWindow._instance.win.focus_force()
                return
        except Exception:
            pass
        SettingsWindow._instance = None
    SettingsWindow(root)

# ===================== 服务控制 =====================
def start_service(auto=False):
    global mouth_simulator
    port = port_combobox.get().strip()
    if not port:
        if auto:
            try: root.deiconify()
            except Exception: pass
        messagebox.showerror("错误", "未检测到可用的 COM 设备！\n请确认硬件已通过 USB 连接到电脑后重试。")
        return False

    # 验证端口是否在当前可用列表中（防止使用过期的保存端口）
    available_ports, _ = scan_serial_ports()
    if available_ports and port not in available_ports:
        if auto:
            try: root.deiconify()
            except Exception: pass
        messagebox.showerror(
            "COM 设备异常",
            f"端口 {port} 当前不可用或设备已断开。\n"
            f"检测到的可用端口：{', '.join(available_ports) if available_ports else '无'}\n"
            f"请在连接配置中重新选择正确的端口。"
        )
        port_combobox.set("")
        refresh_ports()
        return False

    try:
        w, h = map(int, res_entry.get().strip().lower().split('x'))
    except Exception:
        if auto:
            try: root.deiconify()
            except Exception: pass
        messagebox.showerror("格式错误", "分辨率格式：宽x高\n示例：1920x1080")
        return False

    ox = int(config_data.get("origin_x", 0) or 0)
    oy = int(config_data.get("origin_y", 0) or 0)

    with state.lock:
        state.origin_x = ox
        state.origin_y = oy
        state.ORIGIN_X_MIN, state.ORIGIN_X_MAX = ox, ox + w - 1
        state.ORIGIN_Y_MIN, state.ORIGIN_Y_MAX = oy, oy + h - 1
        state.monitors = get_all_monitors()
        logger.info(f"映射区域: X[{state.ORIGIN_X_MIN}~{state.ORIGIN_X_MAX}] Y[{state.ORIGIN_Y_MIN}~{state.ORIGIN_Y_MAX}] res={w}x{h}")

    # 如果服务已在运行，先停止（防止重复打开端口）
    old_ser = None
    with state.lock:
        if state.service_active or state.ser:
            old_ser = state.ser
            state.ser = None
            state.service_active = False
    if old_ser:
        try: old_ser.close()
        except Exception: pass
        stop_serial_worker()
        time.sleep(0.5)

    # 尝试打开串口（最多重试3次，处理端口未完全释放的情况）
    ser = None
    last_err = None
    for attempt in range(3):
        try:
            ser = serial.Serial(port, BAUDRATE, timeout=1)
            time.sleep(2)
            if not ser.is_open:
                raise Exception("打开失败")
            last_err = None
            break
        except Exception as e:
            last_err = e
            ser = None
            if attempt < 2:
                logger.warning(f"串口打开第{attempt+1}次失败: {e}，等待后重试...")
                time.sleep(1)
    if ser is None:
        if auto:
            try: root.deiconify()
            except Exception: pass
        err_msg = str(last_err) if last_err else "未知错误"
        if "PermissionError" in err_msg or "拒绝访问" in err_msg:
            hint = "端口被其他程序占用，或上一次未正常关闭。\n请关闭其他串口工具（如Arduino IDE、PuTTY等）后重试。"
        else:
            hint = "请检查设备是否正确连接。"
        messagebox.showerror("串口错误", f"端口 {port} 打开失败：\n{err_msg}\n\n{hint}")
        refresh_ports()
        return False

    with state.lock:
        state.ser = ser
        state.service_active = True
        state.hardware_overloaded = False
        state.last_input_signal_time = time.time()
        state.is_centered_state = False
        state.key_buffer = ""
        # 清理表情触发状态
        state.expr_buffer = ""
        state.momo_step = 0
        state.momo_flow_active = False
        state.momo_last_time = 0.0
        state.zz_pending = False
        state.momo_pending_buffer = ""
        if state.zz_flush_timer:
            state.zz_flush_timer.cancel()
            state.zz_flush_timer = None
        if state.momo_flush_timer:
            state.momo_flush_timer.cancel()
            state.momo_flush_timer = None
    # 取消残留的 momo 链定时器
    _cancel_momo_chain_timer()

    start_serial_worker()
    mouth_simulator = MouthSimulator(safe_serial_write)

    update_interaction_by_process()

    threading.Thread(target=mouse_timeout_checker, daemon=True).start()
    threading.Thread(target=hardware_monitor_loop, daemon=True).start()
    threading.Thread(target=process_monitor_loop, daemon=True, name="ProcessMonitor").start()

    update_ui_for_service_started()
    messagebox.showinfo(
        "成功",
        "互动模式已启用！\n"
        "CPU 监控已开启（阈值 90%）\n"
        "进程监视已开启：发现游戏/反作弊将自动关闭监听，结束后自动恢复"
    )
    return True

def stop_service():
    with state.lock:
        if not state.service_active:
            return
        state.service_active = False
        state.interaction_enabled = False
        ser = state.ser
        state.ser = None
        # 清理表情触发状态
        state.expr_buffer = ""
        state.momo_step = 0
        state.momo_flow_active = False
        state.momo_last_time = 0.0
        state.zz_pending = False
        state.momo_pending_buffer = ""
        if state.zz_flush_timer:
            state.zz_flush_timer.cancel()
            state.zz_flush_timer = None
        if state.momo_flush_timer:
            state.momo_flush_timer.cancel()
            state.momo_flush_timer = None
    _cancel_momo_chain_timer()
    stop_serial_worker()
    sync_input_hooks()
    if ser and getattr(ser, "is_open", False):
        try:
            ser.close()
        except Exception:
            pass
    update_ui_for_service_stopped()
    update_mode_display("摆件模式")

PROCESS_MONITOR_INTERVAL = 2.5  # 秒，监视轮询间隔（已优化：从1.5s增加，降低CPU唤醒频率）

def find_blocking_process():
    """优化版：更高效的进程检测，减少 psutil 开销（性能优化）"""
    try:
        targets = get_blocking_targets()
        if not targets:
            return False, None, False
        # 优化：只迭代一次，尽早退出，异常处理更精细
        for p in psutil.process_iter(['name']):
            try:
                name = p.info.get('name')
                if name:
                    name_lower = name.lower()
                    if name_lower in targets:
                        return True, name_lower, False
            except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                continue
        return False, None, False
    except Exception as e:
        logger.warning(f"进程监视异常: {e}")
        return False, None, True

def is_any_target_running():
    found, _, err = find_blocking_process()
    if err:
        return None
    return found

def apply_process_monitor_state(found, proc_name, detect_error):
    with state.lock:
        if not state.service_active:
            return
        if state.hardware_overloaded:
            # CPU 过载优先，不在这里抢状态
            return
        prev_enabled = state.interaction_enabled

    if detect_error:
        with state.lock:
            state.interaction_enabled = False
        root.after(0, lambda: update_mode_display("进程检测异常，监听已关闭"))
        sync_input_hooks()
        return

    if found:
        with state.lock:
            state.interaction_enabled = False
        shown = (proc_name or "游戏进程").replace(".exe", "")
        root.after(0, lambda n=shown: update_mode_display(f"检测到 {n}，监听已关闭"))
        if prev_enabled:
            logger.info(f"进程监视：发现 {proc_name}，已关闭监听")
        sync_input_hooks()
    else:
        with state.lock:
            state.interaction_enabled = True
        root.after(0, lambda: update_mode_display("互动模式"))
        if not prev_enabled:
            logger.info("进程监视：目标进程已结束，已恢复监听")
            # 互动启动时发送嘴巴关闭
            safe_serial_write(b"c\n")
            # 脖子回正为 DLC 指令，仅 DLC 开启时发送
            with state.lock:
                dlc_on = state.dlc_enabled
            if dlc_on:
                safe_serial_write(b"n\n")
        sync_input_hooks()

def update_interaction_by_process():
    with state.lock:
        if state.hardware_overloaded:
            state.interaction_enabled = False
            root.after(0, lambda: update_mode_display("性能保护模式 (CPU过载)"))
            sync_input_hooks()
            return
    found, name, err = find_blocking_process()
    apply_process_monitor_state(found, name, err)

def process_monitor_loop():
    logger.info("进程监视已启动")
    # last_sig: None=未初始化, 'game', 'clear', 'error'
    last_sig = None
    while True:
        with state.lock:
            if not state.service_active:
                break
        with state.lock:
            if state.hardware_overloaded:
                time.sleep(PROCESS_MONITOR_INTERVAL)
                continue

        found, name, err = find_blocking_process()
        if err:
            sig = "error"
        elif found:
            sig = "game"
        else:
            sig = "clear"

        if sig != last_sig:
            apply_process_monitor_state(found, name, err)
            last_sig = sig

        time.sleep(PROCESS_MONITOR_INTERVAL)
    logger.info("进程监视已停止")

def manual_start(auto=False):
    start_service(auto=auto)

def manual_stop():
    stop_service()

def get_screen_resolution():
    w, h = get_primary_resolution()
    return f"{w}x{h}"

def apply_resolution_change(res_str, ox=0, oy=0):
    """统一处理分辨率变更：更新输入框、配置文件，若服务运行中则实时更新映射区域。"""
    res_entry.delete(0, tk.END)
    res_entry.insert(0, res_str)
    config_data["resolution"] = res_str
    config_data["origin_x"] = ox
    config_data["origin_y"] = oy
    ConfigManager.save(config_data)
    logger.error(f"[分辨率] 已更新: {res_str}, origin=({ox},{oy})")
    # 服务运行中则实时更新映射区域，无需重启
    with state.lock:
        if state.service_active:
            try:
                w, h = map(int, res_str.strip().lower().split('x'))
                state.origin_x = ox
                state.origin_y = oy
                state.ORIGIN_X_MIN, state.ORIGIN_X_MAX = ox, ox + w - 1
                state.ORIGIN_Y_MIN, state.ORIGIN_Y_MAX = oy, oy + h - 1
                state.monitors = get_all_monitors()
                logger.info(f"[分辨率] 服务运行中实时更新映射区域: X[{state.ORIGIN_X_MIN}~{state.ORIGIN_X_MAX}] Y[{state.ORIGIN_Y_MIN}~{state.ORIGIN_Y_MAX}]")
            except Exception as e:
                logger.error(f"[分辨率] 实时更新映射区域失败: {e}")

def auto_fill_resolution():
    monitors = get_all_monitors()
    if not is_multi_monitor(monitors):
        res = get_screen_resolution()
        ox, oy = 0, 0
        if monitors:
            ox, oy = monitors[0]["x"], monitors[0]["y"]
        apply_resolution_change(res, ox, oy)
    else:
        def on_selected(res_str, ox=0, oy=0):
            apply_resolution_change(res_str, ox, oy)
        ResolutionSelectWindow.get_or_create(root, on_selected)

# ===================== 系统电源事件监控 =====================
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x0004
GWLP_WNDPROC = -4

_power_wndproc_type = None
_original_wndproc = None
_new_wndproc_ref = None

def _on_system_power_event():
    logger.error("[系统事件] 检测到关机/重启/睡眠")
    with state.lock:
        dlc_on = state.dlc_enabled
    if dlc_on:
        logger.error("[系统事件] DLC已开启，发送昏睡指令")
        safe_serial_write(b"d\n", force=True)
    else:
        logger.error("[系统事件] DLC未开启，跳过昏睡指令")

def _install_power_event_monitor():
    global _original_wndproc, _new_wndproc_ref, _power_wndproc_type
    try:
        if root is None or not root.winfo_exists():
            return
        hwnd = root.winfo_id()
        parent = ctypes.windll.user32.GetParent(hwnd)
        if parent:
            hwnd = parent

        _power_wndproc_type = ctypes.WINFUNCTYPE(
            ctypes.c_long, wintypes.HWND, wintypes.UINT,
            wintypes.WPARAM, wintypes.LPARAM
        )

        def _power_wndproc(h, msg, wp, lp):
            if msg == WM_INPUT:
                _handle_raw_input(lp)
            elif msg == WM_QUERYENDSESSION:
                _on_system_power_event()
            elif msg == WM_POWERBROADCAST and wp == PBT_APMSUSPEND:
                _on_system_power_event()
            if _original_wndproc:
                return ctypes.windll.user32.CallWindowProcW(
                    _original_wndproc, h, msg, wp, lp
                )
            return 0

        _new_wndproc_ref = _power_wndproc_type(_power_wndproc)

        # 设置函数签名（兼容 32/64 位）
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            ctypes.windll.user32.SetWindowLongPtrW.argtypes = [
                wintypes.HWND, ctypes.c_int, ctypes.c_void_p
            ]
            ctypes.windll.user32.SetWindowLongPtrW.restype = ctypes.c_void_p
            _original_wndproc = ctypes.windll.user32.SetWindowLongPtrW(
                hwnd, GWLP_WNDPROC, ctypes.cast(_new_wndproc_ref, ctypes.c_void_p)
            )
        else:
            ctypes.windll.user32.SetWindowLongW.argtypes = [
                wintypes.HWND, ctypes.c_int, wintypes.LONG
            ]
            ctypes.windll.user32.SetWindowLongW.restype = wintypes.LONG
            _original_wndproc = ctypes.windll.user32.SetWindowLongW(
                hwnd, GWLP_WNDPROC, ctypes.cast(_new_wndproc_ref, ctypes.c_void_p).value
            )

        ctypes.windll.user32.CallWindowProcW.argtypes = [
            ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
            wintypes.WPARAM, wintypes.LPARAM
        ]
        ctypes.windll.user32.CallWindowProcW.restype = ctypes.c_long

        # 注册 Raw Input 键盘监听（RIDEV_INPUTSINK：窗口不在前台也能接收输入）
        class _RAWINPUTDEVICE(ctypes.Structure):
            _fields_ = [
                ("usUsagePage", ctypes.c_ushort),
                ("usUsage", ctypes.c_ushort),
                ("dwFlags", ctypes.c_uint32),
                ("hwndTarget", ctypes.c_void_p),
            ]

        rid = _RAWINPUTDEVICE()
        rid.usUsagePage = HID_USAGE_PAGE_GENERIC
        rid.usUsage = HID_USAGE_GENERIC_KEYBOARD
        rid.dwFlags = RIDEV_INPUTSINK
        rid.hwndTarget = hwnd
        ctypes.windll.user32.RegisterRawInputDevices.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
        ]
        ctypes.windll.user32.RegisterRawInputDevices.restype = ctypes.c_int
        result = ctypes.windll.user32.RegisterRawInputDevices(
            ctypes.byref(rid), 1, ctypes.sizeof(rid)
        )
        if result:
            logger.info("Raw Input 键盘监听已注册（RIDEV_INPUTSINK）")
        else:
            logger.error("Raw Input 注册失败")

        logger.info("系统电源事件监控已安装")
    except Exception as e:
        logger.error(f"安装系统电源事件监控失败: {e}")

# ===================== 托盘 =====================
def create_tray_icon_image():
    try:
        if os.path.exists(LOGO_FILE):
            return Image.open(LOGO_FILE).resize((64, 64), Image.LANCZOS)
        if os.path.exists(ICON_FILE):
            return Image.open(ICON_FILE).resize((64, 64), Image.LANCZOS)
    except Exception:
        pass
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, 56, 56), fill='#00D4FF')
    return img

def on_tray_click(icon, item):
    if item.text == '显示主界面':
        restore_window()
    elif item.text == '退出程序':
        icon.stop()
        root.quit()

def restore_window():
    root.deiconify()
    root.lift()
    root.focus_force()
    root.after(80, lambda: root.attributes('-topmost', True))
    root.after(180, lambda: root.attributes('-topmost', False))

def setup_tray():
    global tray_icon
    if not pystray:
        return
    menu = pystray.Menu(
        pystray.MenuItem('显示主界面', on_tray_click, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('退出程序', on_tray_click)
    )
    tray_icon = pystray.Icon("BruceConsole", create_tray_icon_image(), "布鲁斯控制台", menu)
    threading.Thread(target=tray_icon.run, daemon=True).start()

def on_window_minimize(event=None):
    if tray_icon:
        root.withdraw()
        try:
            tray_icon.notify("布鲁斯已进入后台", "点击托盘图标恢复")
        except Exception:
            pass
    return "break"

# ===================== 主界面 =====================
def create_gui():
    global root, start_btn, stop_btn, port_combobox, res_entry, refresh_port_btn
    global mode_status_label, status_dot_canvas
    global mouth_toggle, keyboard_mouth_toggle, neck_toggle, eye_input_toggle
    global dlc_toggle
    global config_data, key_listener

    config_data = ConfigManager.load()
    with state.lock:
        state.mouth_active = config_data["mouth_active"]
        state.keyboard_mouth_active = config_data.get("keyboard_mouth_active", DEFAULT_KEYBOARD_MOUTH_ACTIVE)
        state.neck_active = config_data["neck_active"]
        state.eye_input_display_active = config_data.get("eye_input_display_active", DEFAULT_EYE_INPUT_DISPLAY)
        state.auto_center_eyes = config_data.get("auto_center_eyes", True)
        state.dlc_enabled = config_data.get("dlc_enabled", False)
        state.expr_auto_restore = config_data.get("expr_auto_restore", True)
        state.keybinds = config_data.get("keybinds", DEFAULT_KEYBINDS.copy())

    root = tk.Tk()
    root.title("布鲁斯控制台  v4.0")
    root.geometry("700x840")
    root.minsize(640, 800)
    root.configure(bg=COLORS["bg"])

    try:
        if os.path.exists(ICON_FILE):
            root.iconbitmap(ICON_FILE)
    except Exception:
        pass

    style = ttk.Style()
    style.theme_use('clam')
    style.configure(".", background=COLORS["bg"], foreground=COLORS["text"], font=("思源真黑体", 10))
    style.configure("TCombobox", fieldbackground="#0F172A", background="#0F172A",
                    foreground=COLORS["text"], arrowcolor=COLORS["accent"])
    style.map("TCombobox", fieldbackground=[('readonly', '#0F172A')],
              selectbackground=[('focus', COLORS["accent_dim"])])
    style.configure("TEntry", fieldbackground="#0F172A", foreground=COLORS["text"],
                    insertcolor=COLORS["accent"])

    check_img = tk.PhotoImage(width=18, height=18)
    check_img.put(COLORS["accent"], to=(0, 0, 18, 18))
    for x, y in [(4,9),(5,10),(6,11),(7,12),(8,11),(9,10),(10,9),(11,8),(12,7),(13,6),
                 (5,9),(6,10),(7,11),(8,10),(9,9),(10,8),(11,7)]:
        check_img.put("#0A0E1A", (x, y))
    uncheck_img = tk.PhotoImage(width=18, height=18)
    uncheck_img.put("#0F172A", to=(0, 0, 18, 18))
    uncheck_img.put(COLORS["border"], to=(0, 0, 18, 1))
    uncheck_img.put(COLORS["border"], to=(0, 17, 18, 18))
    uncheck_img.put(COLORS["border"], to=(0, 0, 1, 18))
    uncheck_img.put(COLORS["border"], to=(17, 0, 18, 18))
    style.element_create("Tech.indicator", "image", check_img, ("!selected", uncheck_img),
                         border=0, sticky="")
    style.layout("Tech.TCheckbutton", [
        ("Tech.indicator", {"side": "left", "sticky": ""}),
        ("Checkbutton.padding", {"children": [("Checkbutton.label", {"sticky": "w"})], "expand": 1})
    ])
    style.configure("Tech.TCheckbutton", background=COLORS["card"], foreground=COLORS["text"],
                    font=("思源真黑体", 10), padding=2)
    style.map("Tech.TCheckbutton", background=[('active', COLORS["card"])])

    # ---- 顶部标题栏 ----
    header = tk.Frame(root, bg=COLORS["bg_secondary"], height=82)
    header.pack(fill=tk.X)
    header.pack_propagate(False)

    tk.Frame(root, bg=COLORS["accent"], height=2).pack(fill=tk.X)

    logo_label = None
    if ImageTk and os.path.exists(LOGO_FILE):
        try:
            logo_img = Image.open(LOGO_FILE).resize((44, 44), Image.LANCZOS)
            logo_tk = ImageTk.PhotoImage(logo_img)
            logo_label = tk.Label(header, image=logo_tk, bg=COLORS["bg_secondary"])
            logo_label.image = logo_tk
            logo_label.place(x=18, y=19)
        except Exception:
            pass

    title_x = 74 if logo_label else 20
    tk.Label(header, text="布鲁斯控制台", font=("思源真黑体", 15, "bold"),
             fg=COLORS["accent"], bg=COLORS["bg_secondary"]).place(x=title_x, y=18)
    tk.Label(header, text="v4.0·Mod By Marco", font=("思源真黑体", 9),
             fg=COLORS["text_muted"], bg=COLORS["bg_secondary"]).place(x=title_x, y=44)

    tk.Button(header, text="⚙  设置", command=open_settings,
              bg=COLORS["btn"], fg=COLORS["text"], activebackground=COLORS["btn_hover"],
              relief=tk.FLAT, font=("思源真黑体", 9), cursor="hand2",
              padx=14, pady=5).place(relx=1.0, x=-18, y=26, anchor="ne")

    tk.Frame(root, bg=COLORS["border"], height=1).pack(fill=tk.X)

    # ---- 主内容区 ----
    main = tk.Frame(root, bg=COLORS["bg"])
    main.pack(fill=tk.BOTH, expand=True, padx=20, pady=14)

    def make_card(title):
        card = tk.Frame(main, bg=COLORS["card"], highlightbackground=COLORS["border"],
                        highlightthickness=1)
        card.pack(fill=tk.X, pady=(0, 10))
        tk.Label(card, text=f"  {title}", bg=COLORS["card"], fg=COLORS["accent"],
                 font=("思源真黑体", 10, "bold")).pack(anchor="w", padx=16, pady=(10, 6))
        body = tk.Frame(card, bg=COLORS["card"])
        body.pack(fill=tk.X, padx=16, pady=(0, 10))
        return body

    # ---- 连接配置 ----
    conn_body = make_card("连接配置")

    row1 = tk.Frame(conn_body, bg=COLORS["card"])
    row1.pack(fill=tk.X, pady=6)
    tk.Label(row1, text="串口端口", bg=COLORS["card"], fg=COLORS["text_dim"],
             font=("思源真黑体", 9), width=10, anchor="w").pack(side=tk.LEFT)
    port_combobox = ttk.Combobox(row1, width=28, state="readonly")
    port_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
    refresh_port_btn = tk.Button(row1, text="刷新", command=refresh_ports,
                                 bg=COLORS["btn"], fg=COLORS["text"], relief=tk.FLAT,
                                 font=("思源真黑体", 9), cursor="hand2", padx=10)
    refresh_port_btn.pack(side=tk.RIGHT)

    row2 = tk.Frame(conn_body, bg=COLORS["card"])
    row2.pack(fill=tk.X, pady=6)
    tk.Label(row2, text="屏幕分辨率", bg=COLORS["card"], fg=COLORS["text_dim"],
             font=("思源真黑体", 9), width=10, anchor="w").pack(side=tk.LEFT)
    res_entry = ttk.Entry(row2, width=28)
    res_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

    saved_res = config_data.get("resolution", "").strip()
    if saved_res and "x" in saved_res.lower():
        res_entry.insert(0, saved_res)
    else:
        res_entry.insert(0, get_screen_resolution())

    tk.Button(row2, text="自动获取", command=auto_fill_resolution,
              bg=COLORS["btn"], fg=COLORS["text"], relief=tk.FLAT,
              font=("思源真黑体", 9), cursor="hand2", padx=8).pack(side=tk.RIGHT)

    # ---- 核心控制 ----
    ctrl_body = make_card("核心控制")

    btn_row = tk.Frame(ctrl_body, bg=COLORS["card"])
    btn_row.pack(fill=tk.X)
    start_btn = RoundedButton(btn_row, text="▶  启用互动", command=manual_start,
                              width=300, height=56, radius=16,
                              bg=COLORS["accent"], fg="#0A0E1A",
                              hover_bg=COLORS["accent_dim"],
                              disabled_bg=COLORS["btn_hover"],
                              disabled_fg=COLORS["text_muted"],
                              font=("思源真黑体", 12, "bold"),
                              canvas_bg=COLORS["card"],
                              responsive=True)
    start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
    stop_btn = RoundedButton(btn_row, text="■  停止互动", command=manual_stop,
                             width=300, height=56, radius=16,
                             bg=COLORS["danger"], fg="#FFFFFF",
                             hover_bg="#DC2626",
                             disabled_bg=COLORS["btn_hover"],
                             disabled_fg=COLORS["text_muted"],
                             font=("思源真黑体", 12, "bold"),
                             canvas_bg=COLORS["card"],
                             responsive=True)
    stop_btn.config(state=tk.DISABLED)
    stop_btn.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(4, 0))

    # ---- 功能开关 ----
    sw_body = make_card("功能开关")

    with state.lock:
        m_on = state.mouth_active
        km_on = state.keyboard_mouth_active
        n_on = state.neck_active
        ei_on = state.eye_input_display_active
        dlc_on = state.dlc_enabled
        keybinds = state.keybinds.copy()

    toggle_defs = [
        ("嘴巴控制", m_on, toggle_mouth, "toggle_mouth"),
        ("打字互动（嘴巴）", km_on, toggle_keyboard_mouth, "toggle_keyboard_mouth"),
        ("脖子控制", n_on, toggle_neck, "toggle_neck"),
        ("眼睛显示输入内容", ei_on, toggle_eye_input, "toggle_eye_input"),
    ]

    toggle_created = {}
    for i, (label, active, callback, hotkey_action) in enumerate(toggle_defs):
        hotkey_text = get_key_display(keybinds.get(hotkey_action, ""))
        hotkey_str = f"[{hotkey_text}]" if hotkey_text else ""
        t = ModernToggle(sw_body, label, callback=callback, active=active,
                         hotkey_text=hotkey_str, bg=COLORS["card"])
        t.pack(fill=tk.X)
        toggle_created[hotkey_action] = t
        if i < len(toggle_defs) - 1:
            tk.Frame(sw_body, bg=COLORS["border"], height=1).pack(fill=tk.X, padx=12)

    mouth_toggle = toggle_created["toggle_mouth"]
    keyboard_mouth_toggle = toggle_created["toggle_keyboard_mouth"]
    neck_toggle = toggle_created["toggle_neck"]
    eye_input_toggle = toggle_created["toggle_eye_input"]

    # ---- 附加DLC功能开关 ----
    tk.Frame(sw_body, bg=COLORS["border"], height=1).pack(fill=tk.X, padx=12)
    dlc_toggle = ModernToggle(sw_body, "开启附加DLC功能", callback=toggle_dlc,
                              active=dlc_on, hotkey_text="", bg=COLORS["card"])
    dlc_toggle.pack(fill=tk.X)
    tk.Label(sw_body, text="此功能仅限购买DLC用户开启",
             bg=COLORS["card"], fg=COLORS["text_dim"],
             font=("思源真黑体", 8), anchor="w").pack(fill=tk.X, padx=12, pady=(2, 6))

    # ---- EcoQoS 效率模式开关 ----
    global eco_qos_toggle
    eco_qos_supported = is_eco_qos_supported()
    # 初始状态用配置值（实际生效在 init_tasks 中，稍后会同步 UI）
    eco_qos_on = config_data.get("eco_qos_enabled", True) if eco_qos_supported else False
    if eco_qos_supported:
        tk.Frame(sw_body, bg=COLORS["border"], height=1).pack(fill=tk.X, padx=12)
        eco_qos_toggle = ModernToggle(sw_body, "EcoQoS 效率模式", callback=toggle_eco_qos,
                                      active=eco_qos_on, hotkey_text="", bg=COLORS["card"])
        eco_qos_toggle.pack(fill=tk.X)
        tk.Label(sw_body, text="🍃 降低CPU温度和电量消耗（任务管理器可见叶子图标）",
                 bg=COLORS["card"], fg=COLORS["text_dim"],
                 font=("思源真黑体", 8), anchor="w").pack(fill=tk.X, padx=12, pady=(2, 6))
    else:
        eco_qos_toggle = None

    # ---- 状态栏 ----
    status_card = tk.Frame(main, bg=COLORS["card"], highlightbackground=COLORS["border"],
                           highlightthickness=1)
    status_card.pack(fill=tk.X, pady=(0, 10))
    status_inner = tk.Frame(status_card, bg=COLORS["card"])
    status_inner.pack(fill=tk.X, padx=16, pady=10)

    tk.Label(status_inner, text="当前状态", bg=COLORS["card"], fg=COLORS["text_dim"],
             font=("思源真黑体", 9)).pack(side=tk.LEFT)
    status_dot_canvas = tk.Canvas(status_inner, width=10, height=10, bg=COLORS["card"],
                                  highlightthickness=0)
    status_dot_canvas.pack(side=tk.LEFT, padx=(12, 6))
    status_dot_canvas.create_oval(1, 1, 9, 9, fill=COLORS["danger"], outline="")
    mode_status_label = tk.Label(status_inner, text="摆件模式", bg=COLORS["card"],
                                 fg=COLORS["danger"], font=("思源真黑体", 11, "bold"))
    mode_status_label.pack(side=tk.LEFT, padx=4)

    # ---- 底部提示 ----
    tip = tk.Frame(main, bg=COLORS["bg"])
    tip.pack(fill=tk.X, side=tk.BOTTOM, pady=(6, 0))
    tk.Label(tip, text="⚡  快捷键 F2-F6 可快速开关各功能  ·  设置 → 自定义按键（支持鼠标）",
             bg=COLORS["bg"], fg=COLORS["text_dim"], font=("思源真黑体", 8)).pack()
    tip_label_dlc = tk.Label(tip, text="💡 输入 xin=爱心  附加DLC开启时：（?=问号 !=感叹号 zz=昏睡 momo=眯眼-！-❤）",
             bg=COLORS["bg"], fg=COLORS["text_dim"], font=("思源真黑体", 8))
    tip_label_dlc.pack(pady=(2, 0))

    def _show_close_dialog():
        """显示关闭确认对话框，返回 (action, remember) 或 (None, False)"""
        dialog = tk.Toplevel(root)
        dialog.title("关闭确认")
        dialog.resizable(False, False)
        dialog.transient(root)
        dialog.configure(bg=COLORS["bg"])
        dialog_w, dialog_h = 260, 160
        dialog.geometry(f"{dialog_w}x{dialog_h}")
        dialog.update_idletasks()
        x = root.winfo_x() + (root.winfo_width() - dialog_w) // 2
        y = root.winfo_y() + (root.winfo_height() - dialog_h) // 2
        dialog.geometry(f"+{x}+{y}")
        try:
            if os.path.exists(ICON_FILE):
                dialog.iconbitmap(ICON_FILE)
        except Exception:
            pass

        result = {"action": None, "remember": False}

        def make_choice(choice):
            result["action"] = choice
            result["remember"] = remember_var.get()
            dialog.destroy()

        tk.Label(dialog, text="关闭确认", font=("思源真黑体", 12, "bold"),
                 fg=COLORS["accent"], bg=COLORS["bg"]).pack(pady=(6, 3))

        card = tk.Frame(dialog, bg=COLORS["card"], padx=10, pady=6)
        card.pack(fill=tk.X, padx=12, pady=(0, 6))

        tk.Label(card, text="关闭程序还是最小化到托盘？",
                 font=("思源真黑体", 9), fg=COLORS["text_dim"],
                 bg=COLORS["card"]).pack(pady=(0, 6))

        remember_var = tk.BooleanVar(value=False)

        btn_frame = tk.Frame(card, bg=COLORS["card"])
        btn_frame.pack(pady=(0, 4))

        RoundedButton(btn_frame, text="最小化",
                      command=lambda: make_choice("minimize"),
                      width=100, height=32, radius=12,
                      bg=COLORS["btn"], fg=COLORS["text"],
                      hover_bg=COLORS["btn_hover"],
                      font=("思源真黑体", 9),
                      canvas_bg=COLORS["card"]).pack(side=tk.LEFT, padx=5)

        RoundedButton(btn_frame, text="关闭程序",
                      command=lambda: make_choice("close"),
                      width=100, height=32, radius=12,
                      bg=COLORS["danger"], fg="#FFFFFF",
                      hover_bg=COLORS["danger"],
                      font=("思源真黑体", 9, "bold"),
                      canvas_bg=COLORS["card"]).pack(side=tk.LEFT, padx=5)

        cb_wrap = tk.Frame(card, bg=COLORS["card"])
        cb_wrap.pack(fill=tk.X, pady=(2, 0))
        ttk.Checkbutton(cb_wrap, text="记住此操作", variable=remember_var,
                        style="Tech.TCheckbutton").pack(anchor="center")

        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.grab_set()
        dialog.wait_window()
        return result["action"], result["remember"]

    def _do_actual_close():
        config_data["port"] = port_combobox.get().strip()
        config_data["resolution"] = res_entry.get().strip()
        with state.lock:
            config_data["mouth_active"] = state.mouth_active
            config_data["keyboard_mouth_active"] = state.keyboard_mouth_active
            config_data["neck_active"] = state.neck_active
            config_data["eye_input_display_active"] = state.eye_input_display_active
            config_data["dlc_enabled"] = state.dlc_enabled
            config_data["expr_auto_restore"] = state.expr_auto_restore
            config_data["keybinds"] = state.keybinds.copy()
        ConfigManager.save(config_data)
        # 发送关闭复位指令序列（在stop_service之前，确保串口仍可用）
        close_done = threading.Event()
        def _close_seq():
            _send_close_sequence()
            close_done.set()
        t = threading.Thread(target=_close_seq, daemon=True, name="CloseSeq")
        t.start()
        close_done.wait(timeout=6.0)
        stop_service()
        stop_serial_worker()
        _stop_mouse_watchdog()
        with _hooks_lock:
            _stop_mouse_hook()
            _stop_key_hook()
        if tray_icon:
            try: tray_icon.stop()
            except: pass
        root.destroy()

    def on_closing():
        remember = config_data.get("close_action_remember", False)
        saved_action = config_data.get("close_action", "ask")
        if remember and saved_action in ("close", "minimize"):
            action = saved_action
        else:
            action, remember_choice = _show_close_dialog()
            if action is None:
                return
            if remember_choice:
                config_data["close_action_remember"] = True
                config_data["close_action"] = action
            else:
                config_data["close_action_remember"] = False
                config_data["close_action"] = "ask"
            ConfigManager.save(config_data)
        if action == "minimize":
            on_window_minimize()
            return
        _do_actual_close()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.bind("<Unmap>", lambda e: on_window_minimize() if root.state() == 'iconic' else None)

    # ==================== 启动任务 ====================
    def init_tasks():
        setup_tray()
        # 先安装 WndProc + Raw Input 注册，再启用输入处理
        _install_power_event_monitor()
        sync_input_hooks()
        _start_mouse_watchdog()

        def delayed_refresh():
            refresh_ports()
            root.after(300, refresh_ports)

        root.after(200, delayed_refresh)

        def do_auto_start():
            if config_data.get("auto_start", False):
                if config_data.get("auto_interact", False):
                    # 自动启动互动：先尝试启动，成功后再最小化
                    def _try_auto_start():
                        if start_service(auto=True):
                            root.after(300, lambda: root.iconify())
                    root.after(1300, _try_auto_start)
                else:
                    root.after(800, lambda: root.iconify())
            elif config_data.get("auto_interact", False):
                root.after(400, lambda: manual_start(auto=True))

        # 应用 EcoQoS 效率模式
        if is_eco_qos_supported() and config_data.get("eco_qos_enabled", True):
            if set_eco_qos(True):
                logger.info("[启动] EcoQoS 效率模式已启用 🍃")
            else:
                logger.warning("[启动] EcoQoS 开启失败，已禁用")
                config_data["eco_qos_enabled"] = False
            # 同步 UI 开关状态（确保与实际生效状态一致）
            try:
                _main_thread_call(_sync_eco_qos_toggle)
            except Exception:
                pass
        
        monitors = get_all_monitors()
        saved_res = config_data.get("resolution", "").strip()
        log_monitors_info()

        if is_multi_monitor(monitors) and (not saved_res or "x" not in saved_res.lower()):
            def on_resolution_selected(res_str, ox=0, oy=0):
                apply_resolution_change(res_str, ox, oy)
                do_auto_start()

            root.after(600, lambda: ResolutionSelectWindow.get_or_create(root, on_resolution_selected))
        else:
            if "origin_x" not in config_data:
                config_data["origin_x"] = 0
            if "origin_y" not in config_data:
                config_data["origin_y"] = 0
            do_auto_start()

    root.after(400, init_tasks)
    root.mainloop()


if __name__ == "__main__":
    # 以管理员身份运行（确保 Raw Input / 键盘监听在所有窗口下生效）
    def _is_admin():
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    if not _is_admin():
        try:
            params = f'"{os.path.abspath(__file__)}"'
            if len(sys.argv) > 1:
                params += " " + " ".join(f'"{a}"' for a in sys.argv[1:])
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, params, None, 1
            )
            sys.exit(0)
        except Exception:
            pass  # 用户拒绝 UAC 提示，继续以普通权限运行

    try:
        create_gui()
    except Exception as e:
        log_error(f"启动失败: {e}")
        try:
            messagebox.showerror("启动失败", f"{e}\n详情见 bruce_log.txt")
        except:
            pass
