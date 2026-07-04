import asyncio
import json
import time
import websockets
import qrcode
import random
import string
import os
import sys
import tempfile
import requests
import threading
import subprocess
from queue import Empty, Queue

from collections import deque
from pynput.mouse import Controller, Button
from threading import Lock, Thread

# ==========================================
# 全局初始化（只初始化一次，性能最高）
# ==========================================
mouse = Controller()
screen_w, screen_h = 0, 0
state_lock = Lock()
latest_msg = None
pending_laser_dx = 0.0
pending_laser_dy = 0.0
click_queue = deque()
# 后台下载与鼠标线程分离；锁避免多任务同时写同一保存路径导致文件损坏
download_file_lock = Lock()

LASER_SENS = 6

# PC 端协议版本，需与 config/ws.js 中 MINI_PROTOCOL_VERSION 保持一致
PC_PROTOCOL_VERSION = 2
# 要求小程序最低版本
MINI_MIN_REQUIRED_VERSION = 2

# 服务器基础地址（必须改成你的 SpringBoot 地址）
SERVER_BASE = "https://ppt.dilikes.com"
# PC 端 WebSocket 路径（不含域名）。须与服务端「会把手机指令转发到的那个 PC 连接」一致。
# 须与 Spring RoomManager 一致：小程序走 /ws/mini/，PC（Python）走 /ws/python/，否则会占错 Session 导致收不到指令。
# 若自行改成同路径，需同步修改服务端转发逻辑。覆盖示例：set PPT_PC_WS_SUBPATH=ws/mini
PPT_PC_WS_SUBPATH = (os.environ.get("PPT_PC_WS_SUBPATH") or "ws/python").strip().strip("/")
# 文件保存目录
SAVE_DIR = "./ppt_files/"
# 房间号 / 客户端设置 / 传输记录（与脚本同目录）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "ppt_pc_client_room.json")
SETTINGS_PATH = os.path.join(SCRIPT_DIR, "ppt_pc_client_settings.json")
DOWNLOADS_PATH = os.path.join(SCRIPT_DIR, "ppt_pc_client_downloads.json")

DEFAULT_CLIENT_SETTINGS = {
    "screenshot_open_folder": True,
    "transfer_open_folder": True,
    "transfer_open_ppt": True,
    "ppt_notes_enabled": False,
    "open_ppt_path": "",
}

PPT_EXTS = {".ppt", ".pptx", ".pptm", ".pps", ".ppsx", ".pot", ".potx"}
MAX_DOWNLOAD_RECORDS = 50

settings_lock = Lock()
_client_settings = dict(DEFAULT_CLIENT_SETTINGS)
_ppt_app_instance = None

# 自动创建目录
if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)


def load_settings_from_disk() -> None:
    global _client_settings
    with settings_lock:
        if not os.path.isfile(SETTINGS_PATH):
            _client_settings = dict(DEFAULT_CLIENT_SETTINGS)
            return
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = dict(DEFAULT_CLIENT_SETTINGS)
            for k in DEFAULT_CLIENT_SETTINGS:
                if k not in data:
                    continue
                if k == "open_ppt_path":
                    merged[k] = str(data[k] or "")
                else:
                    merged[k] = bool(data[k])
            _client_settings = merged
        except Exception:
            _client_settings = dict(DEFAULT_CLIENT_SETTINGS)


def get_settings_snapshot() -> dict:
    with settings_lock:
        return dict(_client_settings)


def _write_settings_file(data: dict) -> None:
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def persist_settings_from_memory() -> None:
    with settings_lock:
        _write_settings_file(dict(_client_settings))


def set_client_settings(**kwargs) -> None:
    """更新内存中的设置并写入 ppt_pc_client_settings.json。"""
    with settings_lock:
        for k, v in kwargs.items():
            if k not in DEFAULT_CLIENT_SETTINGS:
                continue
            if k == "open_ppt_path":
                _client_settings[k] = str(v or "")
            else:
                _client_settings[k] = bool(v)
        _write_settings_file(dict(_client_settings))


# --- PPT 放映备注（COM，独立线程；需 pywin32）---
_notes_lock = Lock()
_notes_thread = None
_notes_stop = threading.Event()
_notes_wake = Queue()
_notes_last_sent = None  # tuple (norm_slide_key, text) 或 None
_notes_pywin32_warned = False
_notes_warned_slideshow = False
_ppt_notes_announced_read_ok = False
_ppt_notes_enabled_user_hint = False

_WPS_PROGIDS = ("Kwpp.Application", "wps.Application", "Kingsoft.WPP.Application")

_PPT_NOTES_DEBUG = os.environ.get("PPT_NOTES_DEBUG", "").strip().lower() in ("1", "true", "yes")


def _ppt_notes_warn_slideshow_once() -> None:
    """已连接 Office 但未进入放映时提示一次（编辑视图无法读备注）。"""
    global _notes_warned_slideshow
    if _notes_warned_slideshow:
        return
    if not get_settings_snapshot().get("ppt_notes_enabled"):
        return
    _notes_warned_slideshow = True
    print(
        "ℹ️ 演讲者模式已开启：请在 PowerPoint / WPS 中按 F5（从头）或 Shift+F5（从当前页）进入幻灯片放映；"
        "仅在编辑窗口打开时无法同步备注。"
    )


def _ppt_notes_shape_text(sh) -> str:
    """从形状读取备注文本；不依赖 HasText（部分版本/占位符上不可靠）。"""
    seen_local = set()
    chunks = []
    for use_tf2 in (True, False):
        try:
            if use_tf2:
                tf = sh.TextFrame2
            else:
                if not getattr(sh, "HasTextFrame", False):
                    continue
                tf = sh.TextFrame
            tr = tf.TextRange
            t = (tr.Text or "").replace("\r", "\n").strip()
            if t and t not in seen_local:
                seen_local.add(t)
                chunks.append(t)
        except Exception:
            continue
    return "\n".join(chunks).strip() if chunks else ""


# MsoShapeType：组合、表格（与 Office / WPS 兼容接口一致）
_MSO_GROUP = 6
_MSO_TABLE = 19


def _ppt_notes_table_text(sh) -> str:
    """备注页中的表格单元格文本。"""
    parts = []
    seen = set()
    try:
        tbl = sh.Table
        rows = int(tbl.Rows.Count)
        cols = int(tbl.Columns.Count)
        for r in range(1, rows + 1):
            for c in range(1, cols + 1):
                try:
                    cell = tbl.Cell(r, c)
                    inner = cell.Shape
                    t = _ppt_notes_shape_text(inner)
                    if t and t not in seen:
                        seen.add(t)
                        parts.append(t)
                except Exception:
                    continue
    except Exception:
        return ""
    return "\n".join(parts).strip()


def _ppt_notes_walk_shapes(shapes, parts: list, seen: set, depth: int = 0) -> None:
    """递归遍历备注页形状（组合、表格、普通文本框）。"""
    if depth > 32:
        return
    try:
        cnt = int(shapes.Count)
    except Exception:
        return
    for i in range(1, cnt + 1):
        try:
            sh = shapes.Item(i)
        except Exception:
            continue
        try:
            st = int(sh.Type)
        except Exception:
            st = -1
        if st == _MSO_GROUP:
            try:
                _ppt_notes_walk_shapes(sh.GroupItems, parts, seen, depth + 1)
            except Exception:
                pass
            continue
        if st == _MSO_TABLE:
            tt = _ppt_notes_table_text(sh)
            if tt and tt not in seen:
                seen.add(tt)
                parts.append(tt)
            continue
        t = _ppt_notes_shape_text(sh)
        if t and t not in seen:
            seen.add(t)
            parts.append(t)


def _ppt_notes_try_read_once():
    """在已 CoInitialize 的线程中调用。返回 (slide_index_or_None, notes_text)。"""
    global _notes_pywin32_warned
    try:
        import win32com.client as wc  # type: ignore
    except ImportError:
        if not _notes_pywin32_warned:
            _notes_pywin32_warned = True
            print("ℹ️ 未安装 pywin32，演讲者模式不可用（pip install pywin32）")
        return None, ""

    app = None
    for progid in ("PowerPoint.Application",) + _WPS_PROGIDS:
        try:
            app = wc.GetActiveObject(progid)
            if app is not None:
                break
        except Exception:
            continue
    if app is None:
        if _PPT_NOTES_DEBUG:
            print("ℹ️ [PPT_NOTES] GetActiveObject 未找到 PowerPoint/WPS，请先打开演示软件并进入放映")
        return None, ""

    try:
        windows = app.SlideShowWindows
        n = int(windows.Count)
    except Exception as ex:
        if _PPT_NOTES_DEBUG:
            print(f"ℹ️ [PPT_NOTES] 无法访问 SlideShowWindows: {ex!r}")
        return None, ""
    if n < 1:
        _ppt_notes_warn_slideshow_once()
        if _PPT_NOTES_DEBUG:
            print("ℹ️ [PPT_NOTES] SlideShowWindows.Count=0，当前没有放映窗口")
        return None, ""

    if _PPT_NOTES_DEBUG:
        print(f"ℹ️ [PPT_NOTES] SlideShowWindows.Count={n}，将依次尝试各窗口")

    slide = None
    idx = None
    for wi in range(1, n + 1):
        try:
            wnd = windows.Item(wi)
            view = wnd.View
            try:
                idx = int(view.CurrentShowPosition)
            except Exception:
                idx = None
            sl = None
            try:
                sl = view.Slide
            except Exception:
                sl = None
            if sl is None and idx is not None:
                try:
                    sl = wnd.Presentation.Slides.Item(idx)
                except Exception:
                    sl = None
            if sl is not None:
                slide = sl
                if idx is None:
                    try:
                        idx = int(sl.SlideIndex)
                    except Exception:
                        idx = -1
                if _PPT_NOTES_DEBUG:
                    try:
                        pos = view.CurrentShowPosition
                    except Exception:
                        pos = "?"
                    print(f"ℹ️ [PPT_NOTES] 使用放映窗口 #{wi}，CurrentShowPosition={pos} SlideIndex={idx}")
                break
        except Exception as ex:
            if _PPT_NOTES_DEBUG:
                print(f"ℹ️ [PPT_NOTES] 放映窗口 #{wi} 不可用: {ex!r}")
            continue

    if slide is None:
        if _PPT_NOTES_DEBUG:
            print("ℹ️ [PPT_NOTES] 所有放映窗口均无法取得当前 Slide")
        return None, ""

    try:
        notes_page = slide.NotesPage
    except Exception as ex:
        if _PPT_NOTES_DEBUG:
            print(f"ℹ️ [PPT_NOTES] 无法访问 NotesPage: {ex!r}")
        return None, ""

    parts = []
    seen = set()
    try:
        _ppt_notes_walk_shapes(notes_page.Shapes, parts, seen, 0)
    except Exception as ex:
        if _PPT_NOTES_DEBUG:
            print(f"ℹ️ [PPT_NOTES] 遍历备注页形状失败: {ex!r}")
        return idx, ""

    text = "\n".join(parts).strip()
    if _PPT_NOTES_DEBUG:
        print(f"ℹ️ [PPT_NOTES] slide={idx} 形状片段数={len(parts)} 备注长度={len(text)}")
        if not text:
            try:
                sc = int(notes_page.Shapes.Count)
                print(
                    f"ℹ️ [PPT_NOTES] 备注页共 {sc} 个形状但未解析出文字；"
                    "请确认在「普通视图」备注窗格中输入过内容（非仅默认占位提示）"
                )
            except Exception:
                pass
    return idx, text


def _ppt_notes_norm_pair(slide_idx, text: str):
    if slide_idx is None:
        return (-1, "")
    return (int(slide_idx), text or "")


def _schedule_ws_send_ppt_notes(text: str) -> bool:
    """返回是否已成功把发送任务交给 asyncio 循环（不代表服务端一定转发到手机）。"""
    inst = _ppt_app_instance
    if inst is None or getattr(inst, "_exiting", False):
        return False
    ws = inst._ws_holder.get("ws")
    loop = inst._async_loop
    if ws is None or loop is None or not loop.is_running():
        return False
    rid = str(getattr(inst, "room_id", "") or "").strip().upper()
    if not rid:
        return False
    payload = json.dumps(
        {"cmd": "PPT_NOTES", "roomId": rid, "text": text or ""},
        ensure_ascii=False,
    )
    settings_fallback = _client_settings_payload_for_room(rid, embed_ppt_notes_text=text or "")

    async def _send():
        try:
            await ws.send(payload)
            await ws.send(settings_fallback)
        except Exception as ex:
            if _PPT_NOTES_DEBUG:
                print(f"ℹ️ [PPT_NOTES] WebSocket 发送失败: {ex!r}")

    try:
        asyncio.run_coroutine_threadsafe(_send(), loop)
        return True
    except Exception as ex:
        if _PPT_NOTES_DEBUG:
            print(f"ℹ️ [PPT_NOTES] 调度 WebSocket 发送失败: {ex!r}")
        return False


def _schedule_ws_send_to_mini(payload_dict: dict) -> bool:
    """向手机端推送任意 JSON 消息（需含 roomId）。"""
    inst = _ppt_app_instance
    if inst is None or getattr(inst, "_exiting", False):
        return False
    ws = inst._ws_holder.get("ws")
    loop = inst._async_loop
    if ws is None or loop is None or not loop.is_running():
        return False
    rid = str(getattr(inst, "room_id", "") or "").strip().upper()
    if not rid:
        return False
    payload_dict.setdefault("roomId", rid)
    payload = json.dumps(payload_dict, ensure_ascii=False)

    async def _send():
        try:
            await ws.send(payload)
        except Exception:
            pass

    try:
        asyncio.run_coroutine_threadsafe(_send(), loop)
        return True
    except Exception:
        return False


def _ppt_notes_broadcast_clear() -> None:
    global _notes_last_sent
    with _notes_lock:
        _notes_last_sent = None
    _schedule_ws_send_ppt_notes("")


def request_ppt_notes_refresh() -> None:
    if not get_settings_snapshot().get("ppt_notes_enabled"):
        return
    try:
        _notes_wake.put_nowait(True)
    except Exception:
        pass


def _ppt_notes_worker() -> None:
    import pythoncom  # type: ignore

    global _notes_last_sent, _ppt_notes_announced_read_ok
    pythoncom.CoInitialize()
    try:
        while not _notes_stop.is_set():
            if not get_settings_snapshot().get("ppt_notes_enabled"):
                time.sleep(0.25)
                continue
            try:
                _notes_wake.get(timeout=0.2)
                while True:
                    try:
                        _notes_wake.get_nowait()
                    except Empty:
                        break
            except Empty:
                pass
            if _notes_stop.is_set():
                break
            idx, text = _ppt_notes_try_read_once()
            if idx is None:
                text = ""
            pair = _ppt_notes_norm_pair(idx, text)
            should_send = False
            with _notes_lock:
                if _notes_last_sent != pair:
                    _notes_last_sent = pair
                    should_send = True
            if should_send:
                scheduled = _schedule_ws_send_ppt_notes(pair[1])
                if pair[1].strip() and not _ppt_notes_announced_read_ok:
                    _ppt_notes_announced_read_ok = True
                    if scheduled:
                        print(
                            f"✅ 演讲者模式：本机已读到内容（{len(pair[1].strip())} 字），已提交 WebSocket 发送"
                            "（含 PPT_NOTES 与带 ppt_notes_text 的 CLIENT_SETTINGS 双通道，兼容仅转发设置帧的服务端）。"
                        )
                    else:
                        print(
                            "⚠️ 演讲者模式：本机已读到内容，但当前 WebSocket 未就绪，无法发送到手机（请确认已点「启动服务」且已连接）。"
                        )
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def _ensure_notes_thread() -> None:
    global _notes_thread
    if _notes_thread is not None and _notes_thread.is_alive():
        return
    _notes_stop.clear()
    t = Thread(target=_ppt_notes_worker, daemon=True, name="ppt-notes")
    _notes_thread = t
    t.start()


def _stop_notes_thread() -> None:
    global _notes_thread
    _notes_stop.set()
    try:
        _notes_wake.put_nowait(True)
    except Exception:
        pass
    th = _notes_thread
    _notes_thread = None
    if th is not None and th.is_alive():
        th.join(timeout=1.5)


def _ppt_notes_on_settings_changed() -> None:
    global _ppt_notes_announced_read_ok, _ppt_notes_enabled_user_hint
    if get_settings_snapshot().get("ppt_notes_enabled"):
        _ppt_notes_announced_read_ok = False
        if not _ppt_notes_enabled_user_hint:
            _ppt_notes_enabled_user_hint = True
            print(
                "ℹ️ 演讲者模式：已开启。请按 F5/Shift+F5 进入幻灯片放映，并在「普通视图」的备注窗格中输入过文字。"
                " 若你运行的是从其它目录复制的 ppt_pc_client.py，请改为运行已更新备注功能的同一份脚本。"
                " 出现「✅ 演讲者模式：本机已读到…」后手机仍无字，多为服务端未转发 PPT_NOTES；可设环境变量 PPT_NOTES_DEBUG=1 查看细节。"
            )
        _ensure_notes_thread()
        request_ppt_notes_refresh()
    else:
        _ppt_notes_enabled_user_hint = False
        _ppt_notes_announced_read_ok = False
        _stop_notes_thread()
        _ppt_notes_broadcast_clear()


def merge_remote_client_settings(data: dict) -> None:
    patch = {}
    for k in ("screenshot_open_folder", "transfer_open_folder", "transfer_open_ppt", "ppt_notes_enabled"):
        if k in data:
            patch[k] = bool(data[k])
    if not patch:
        return
    set_client_settings(**patch)
    print(f"✅ 已应用手机端设置：{patch}")
    _schedule_gui_settings_refresh()
    _ppt_notes_on_settings_changed()


def explorer_select_file(abs_path: str) -> None:
    p = os.path.normpath(abs_path)
    subprocess.run(["explorer", "/select,", p], check=False)


def explorer_open_folder(folder_path: str) -> None:
    p = os.path.normpath(folder_path)
    subprocess.run(["explorer", p], check=False)


def append_download_record(name: str, path: str) -> None:
    entry = {"name": name, "path": path, "ts": time.time()}
    with settings_lock:
        try:
            if os.path.isfile(DOWNLOADS_PATH):
                with open(DOWNLOADS_PATH, "r", encoding="utf-8") as f:
                    arr = json.load(f)
                if not isinstance(arr, list):
                    arr = []
            else:
                arr = []
        except Exception:
            arr = []
        arr.insert(0, entry)
        arr = arr[:MAX_DOWNLOAD_RECORDS]
        try:
            with open(DOWNLOADS_PATH, "w", encoding="utf-8") as f:
                json.dump(arr, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    _schedule_downloads_list_refresh()


def load_download_records() -> list:
    with settings_lock:
        try:
            if os.path.isfile(DOWNLOADS_PATH):
                with open(DOWNLOADS_PATH, "r", encoding="utf-8") as f:
                    arr = json.load(f)
                if isinstance(arr, list):
                    return arr[:MAX_DOWNLOAD_RECORDS]
        except Exception:
            pass
    return []


def _schedule_gui_settings_refresh() -> None:
    inst = _ppt_app_instance
    if inst is not None:
        try:
            inst.root.after(0, inst._sync_settings_vars_from_model)
        except Exception:
            pass


def _schedule_downloads_list_refresh() -> None:
    inst = _ppt_app_instance
    if inst is not None:
        try:
            inst.root.after(0, inst._refresh_downloads_list)
        except Exception:
            pass


def _client_settings_payload_for_room(room_id: str, embed_ppt_notes_text: str | None = None) -> str:
    """embed_ppt_notes_text 非 None 时附带 ppt_notes_text 字段，供仅转发 CLIENT_SETTINGS 的服务端同步备注。"""
    rid = str(room_id or "").strip().upper()
    snap = get_settings_snapshot()
    obj = {
        "cmd": "CLIENT_SETTINGS",
        "roomId": rid,
        "screenshot_open_folder": bool(snap.get("screenshot_open_folder")),
        "transfer_open_folder": bool(snap.get("transfer_open_folder")),
        "transfer_open_ppt": bool(snap.get("transfer_open_ppt")),
        "ppt_notes_enabled": bool(snap.get("ppt_notes_enabled")),
    }
    if embed_ppt_notes_text is not None:
        obj["ppt_notes_text"] = embed_ppt_notes_text
    return json.dumps(obj, ensure_ascii=False)


async def _ws_send_client_settings(websocket, room_id: str) -> None:
    try:
        await websocket.send(_client_settings_payload_for_room(room_id))
    except Exception:
        pass


def broadcast_client_settings_to_mobile() -> None:
    """从 GUI 线程推送行为开关到小程序（需 WS 已连接）。"""
    inst = _ppt_app_instance
    if inst is None or getattr(inst, "_exiting", False):
        return
    ws = inst._ws_holder.get("ws")
    loop = inst._async_loop
    if ws is None or loop is None or not loop.is_running():
        return
    rid = str(getattr(inst, "room_id", "") or "").strip().upper()
    if not rid:
        return

    async def _send():
        await _ws_send_client_settings(ws, rid)

    try:
        asyncio.run_coroutine_threadsafe(_send(), loop)
    except Exception:
        pass


load_settings_from_disk()
try:
    if get_settings_snapshot().get("ppt_notes_enabled"):
        _ppt_notes_on_settings_changed()
except Exception:
    pass


def get_ws_url(room_id: str) -> str:
    base = SERVER_BASE.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    else:
        base = "ws://" + base
    rid = str(room_id or "").strip().upper()
    sub = (PPT_PC_WS_SUBPATH or "ws/python").strip().strip("/")
    return f"{base}/{sub}/{rid}"


def load_or_create_room_id() -> str:
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            rid = data.get("room_id")
            if isinstance(rid, str) and len(rid) == 6 and rid.isalnum():
                return rid.upper()
        except Exception:
            pass
    rid = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"room_id": rid}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return rid


def save_room_id(rid: str) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"room_id": rid.upper()}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ==========================================
# 文件下载函数
# ==========================================
def download_file(uri):
    """同步下载（可在任意线程调用）。内部持锁，多任务排队执行以免并发写同一文件名。"""
    with download_file_lock:
        try:
            file_url = SERVER_BASE + uri
            print(f"📥 开始下载：{file_url}")

            file_name = os.path.basename(file_url.split("?")[0])
            save_path = os.path.join(SAVE_DIR, file_name)

            abs_path = os.path.abspath(save_path)

            resp = requests.get(file_url, stream=True, timeout=30)
            resp.raise_for_status()

            with open(abs_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            print(f"✅ 文件已保存：{abs_path}")

            snap = get_settings_snapshot()
            append_download_record(file_name, abs_path)

            ext = os.path.splitext(abs_path)[1].lower()
            if ext in PPT_EXTS:
                if snap.get("transfer_open_ppt"):
                    os.startfile(abs_path)
                    print("✅ 已用默认程序打开演示文稿")
            else:
                if snap.get("transfer_open_folder"):
                    explorer_select_file(abs_path)

            return abs_path

        except Exception as e:
            print(f"❌ 下载失败：{e}")
            return None


def start_download_file_async(uri: str) -> None:
    """不阻塞指令线程：后台下载，避免 FILE_ARRIVED 期间翻页/激光等停顿。"""
    if not (uri and str(uri).strip()):
        return
    u = str(uri).strip()

    def _run():
        download_file(u)

    Thread(target=_run, daemon=True).start()


def _schedule_gui_minimize_main_window() -> None:
    """由手机端「PC 窗口最小化」指令调用；必须在 Tk 主线程执行 iconify。"""
    inst = _ppt_app_instance
    if inst is None or getattr(inst, "_exiting", False):
        return

    def job():
        if getattr(inst, "_exiting", False):
            return
        try:
            inst.root.iconify()
        except Exception:
            pass

    try:
        inst.root.after(0, job)
    except Exception:
        pass


def _schedule_gui_restore_main_window() -> None:
    """由手机端「PC 窗口恢复」指令调用；与托盘「显示主窗口」一致。"""
    inst = _ppt_app_instance
    if inst is None or getattr(inst, "_exiting", False):
        return
    try:
        inst.root.after(0, inst._restore_main_window)
    except Exception:
        pass


def _run_on_gui_thread(fn) -> None:
    """在非 Tk 主线程中调度到主线程执行（聚光灯 / 投屏计时等）。"""
    inst = _ppt_app_instance
    if inst is None or getattr(inst, "_exiting", False):
        return

    def job():
        if getattr(inst, "_exiting", False):
            return
        try:
            fn()
        except Exception:
            pass

    try:
        inst.root.after(0, job)
    except Exception:
        pass


# ==========================================
# PPT 指令执行
# ==========================================
def execute_command(data):
    cmd = data.get("cmd")

    if cmd == "NEXT_PAGE":
        import pyautogui

        pyautogui.press("pagedown")
        request_ppt_notes_refresh()
    elif cmd == "PREV_PAGE":
        import pyautogui

        pyautogui.press("pageup")
        request_ppt_notes_refresh()
    elif cmd == "FULL_SCREEN":
        import pyautogui

        pyautogui.press("f5")
        request_ppt_notes_refresh()
    elif cmd == "FROM_CURRENT":
        import pyautogui

        pyautogui.hotkey("shift", "f5")
        request_ppt_notes_refresh()
    elif cmd == "BLACK_SCREEN":
        import pyautogui

        pyautogui.press("b")
    elif cmd == "WHITE_SCREEN":
        import pyautogui

        pyautogui.press("w")
    elif cmd == "EXIT":
        import pyautogui

        pyautogui.press("esc")
        request_ppt_notes_refresh()
    elif cmd == "SEND_TEXT":
        import pyautogui
        import pyperclip

        text = data.get("text", "")
        if text:
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
    elif cmd == "SELECT_ALL":
        import pyautogui

        pyautogui.hotkey("ctrl", "a")

    elif cmd == "COPY":
        import pyautogui

        pyautogui.hotkey("ctrl", "c")
    elif cmd == "PASTE":
        import pyautogui

        pyautogui.hotkey("ctrl", "v")
    elif cmd == "SCREENSHOT":
        import pyautogui

        save_path = os.path.join(SAVE_DIR, f"screen_{int(time.time())}.png")
        abs_path = os.path.abspath(save_path)
        pyautogui.screenshot(abs_path)
        print(f"✅ 截图已保存：{abs_path}")
        _schedule_ws_send_to_mini({"cmd": "SCREENSHOT_DONE", "filename": os.path.basename(abs_path)})

        snap = get_settings_snapshot()
        if snap.get("screenshot_open_folder"):
            explorer_select_file(abs_path)
    elif cmd == "OPEN_PPT":
        try:
            snap = get_settings_snapshot()
            cfg_path = (snap.get("open_ppt_path") or "").strip()
            if cfg_path and os.path.isfile(cfg_path):
                os.startfile(cfg_path)
                print("✅ 已打开本机配置的默认演示文稿")
            else:
                # 固定 tmp.pptx 易被上次打开的 PowerPoint 占用，导致 [Errno 13] Permission denied
                tmp_root = os.environ.get("TEMP") or os.environ.get("TMP") or tempfile.gettempdir()
                fd, temp_path = tempfile.mkstemp(suffix=".pptx", prefix="ppt_remote_", dir=tmp_root)
                os.close(fd)
                os.startfile(temp_path)
                print("✅ 已启动本机默认 PPT 程序（临时空白文稿）")
        except Exception as e:
            print("❌ 启动失败", e)
    elif cmd == "CLIENT_SETTINGS":
        merge_remote_client_settings(data)
    elif cmd == "DELETE":
        import pyautogui

        try:
            pyautogui.press("backspace")
            print("✅ 删除成功")
        except Exception as e:
            print("❌ 删除失败", e)
    elif cmd == "FILE_ARRIVED":
        url = data.get("url")
        if url:
            print("📎 已排队后台下载")
            start_download_file_async(url)
    elif cmd == "PC_WINDOW_MINIMIZE":
        _schedule_gui_minimize_main_window()
    elif cmd == "PC_WINDOW_RESTORE":
        _schedule_gui_restore_main_window()
    elif cmd in ("SPOTLIGHT_SHOW", "SPOTLIGHT_UPDATE"):
        pl = dict(data) if isinstance(data, dict) else {}

        def _spot_run():
            i = _ppt_app_instance
            if i and not getattr(i, "_exiting", False):
                i._gui_spotlight_apply(pl)

        _run_on_gui_thread(_spot_run)
    elif cmd == "SPOTLIGHT_HIDE":

        def _spot_hide_run():
            i = _ppt_app_instance
            if i and not getattr(i, "_exiting", False):
                i._gui_spotlight_hide()

        _run_on_gui_thread(_spot_hide_run)
    elif cmd == "TIMER_OVERLAY_SHOW":
        pl = dict(data) if isinstance(data, dict) else {}

        def _tshow():
            i = _ppt_app_instance
            if i and not getattr(i, "_exiting", False):
                i._gui_timer_overlay_show(pl)

        _run_on_gui_thread(_tshow)
    elif cmd == "TIMER_OVERLAY_HIDE":

        def _thide():
            i = _ppt_app_instance
            if i and not getattr(i, "_exiting", False):
                i._gui_timer_overlay_hide()

        _run_on_gui_thread(_thide)
    elif cmd == "TIMER_OVERLAY_PAUSE":

        def _tpause():
            i = _ppt_app_instance
            if i and not getattr(i, "_exiting", False):
                i._gui_timer_overlay_pause()

        _run_on_gui_thread(_tpause)
    elif cmd == "TIMER_OVERLAY_RESUME":

        def _tres():
            i = _ppt_app_instance
            if i and not getattr(i, "_exiting", False):
                i._gui_timer_overlay_resume()

        _run_on_gui_thread(_tres)
    elif cmd == "TIMER_OVERLAY_RESET":
        pl = dict(data) if isinstance(data, dict) else {}

        def _treset():
            i = _ppt_app_instance
            if i and not getattr(i, "_exiting", False):
                i._gui_timer_overlay_reset(pl)

        _run_on_gui_thread(_treset)


def dispatch_remote_command(data: dict, source: str = "ws") -> None:
    """WebSocket 与手势模块统一指令入口。"""
    global latest_msg, pending_laser_dx, pending_laser_dy
    if not isinstance(data, dict):
        return
    cmd = data.get("cmd")
    if cmd == "LASER":
        if data.get("dx") is not None and data.get("dy") is not None:
            with state_lock:
                pending_laser_dx += float(data["dx"])
                pending_laser_dy += float(data["dy"])
            return
        with state_lock:
            latest_msg = json.dumps(data, ensure_ascii=False)
        return
    if cmd == "MOUSE_CLICK":
        cnt = int(data.get("count", 1))
        with state_lock:
            click_queue.append(cnt)
        return
    with state_lock:
        latest_msg = json.dumps(data, ensure_ascii=False)


# ==========================================
# 独立鼠标线程
# ==========================================
def mouse_render_thread():
    global latest_msg, screen_w, screen_h, pending_laser_dx, pending_laser_dy
    import pyautogui

    screen_w, screen_h = pyautogui.size()

    while True:
        try:
            clicks_to_run = []
            pdx = 0.0
            pdy = 0.0
            msg = None
            with state_lock:
                while click_queue:
                    clicks_to_run.append(click_queue.popleft())
                pdx = pending_laser_dx
                pdy = pending_laser_dy
                pending_laser_dx = 0.0
                pending_laser_dy = 0.0
                msg = latest_msg
                latest_msg = None

            for cnt in clicks_to_run:
                if cnt >= 2:
                    mouse.click(Button.left, 2)
                else:
                    mouse.click(Button.left, 1)

            if pdx != 0.0 or pdy != 0.0:
                mouse.move(pdx * LASER_SENS, pdy * LASER_SENS)

            if msg is not None:
                data = json.loads(msg)
                if data.get("cmd") == "LASER":
                    x = data.get("x", 0)
                    y = data.get("y", 0)
                    mouse.position = (float(x) * screen_w, float(y) * screen_h)
                else:
                    execute_command(data)

        except Exception:
            pass

        time.sleep(0.008)


Thread(target=mouse_render_thread, daemon=True).start()


def _presence_room_id_matches(msg_room: object, expected_room: str) -> bool:
    """服务端下发的 roomId 须与当前会话一致；缺 roomId 则忽略（不匹配）。"""
    if msg_room is None:
        return False
    a = str(msg_room).strip().upper()
    if not a:
        return False
    return a == str(expected_room).strip().upper()


def apply_mobile_peer_presence(online: bool) -> None:
    """更新「配对码」旁移动端就绪文案；无 GUI 时忽略。"""
    inst = _ppt_app_instance
    if inst is None or not hasattr(inst, "_set_pairing_title_mobile_online"):
        return

    def _run():
        if getattr(inst, "_exiting", False):
            return
        inst._set_pairing_title_mobile_online(online)

    try:
        inst.root.after(0, _run)
    except Exception:
        pass


# ==========================================
# 异步 WebSocket（供桌面端启停）
# ==========================================
async def websocket_client_loop(room_id: str, ws_ref_holder: dict, status_cb):
    global latest_msg, pending_laser_dx, pending_laser_dy
    url = get_ws_url(room_id)
    print(f"🔗 WebSocket 连接地址：{url}")

    def notify(text: str):
        if status_cb:
            status_cb(text)

    err = None
    try:
        async with websockets.connect(
            url,
            ping_interval=None,
            ping_timeout=None,
            max_size=None,
        ) as websocket:
            ws_ref_holder["ws"] = websocket
            notify("已连接 · 等待手机端指令")
            apply_mobile_peer_presence(False)
            print("\n✅ 连接成功！等待控制指令...")

            async for message in websocket:
                try:
                    data = json.loads(message)
                    cmd = data.get("cmd")
                    if cmd == "MINI_HELLO":
                        mini_ver = int(data.get("version") or 0)
                        if mini_ver < MINI_MIN_REQUIRED_VERSION:
                            mismatch = json.dumps({
                                "cmd": "VERSION_MISMATCH",
                                "roomId": room_id,
                                "pc_version": PC_PROTOCOL_VERSION,
                                "min_required": MINI_MIN_REQUIRED_VERSION,
                            }, ensure_ascii=False)
                            try:
                                await websocket.send(mismatch)
                            except Exception:
                                pass
                            print(f"⚠️ 小程序版本过低（{mini_ver}），要求 >= {MINI_MIN_REQUIRED_VERSION}，已通知手机端升级")
                        else:
                            print(f"✅ 握手成功：小程序版本 {mini_ver}，PC 版本 {PC_PROTOCOL_VERSION}")
                        continue
                    if cmd in ("ONLINE", "OFFLINE"):
                        if _presence_room_id_matches(data.get("roomId"), room_id):
                            is_online = cmd == "ONLINE"
                            apply_mobile_peer_presence(is_online)
                            if is_online:
                                await _ws_send_client_settings(websocket, room_id)
                        continue
                    if cmd in ("LASER", "MOUSE_CLICK"):
                        dispatch_remote_command(data, "ws")
                        continue
                except Exception:
                    pass
                dispatch_remote_command(data, "ws")

    except Exception as e:
        err = e
        print(f"❌ 连接断开：{e}")
    finally:
        ws_ref_holder["ws"] = None
        apply_mobile_peer_presence(False)
        if err is not None:
            notify(f"连接异常 · {err}")
        else:
            notify("已停止 · 可点击「启动服务」重新连接")


# ==========================================
# 桌面 GUI + 托盘
# ==========================================
try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    tk = None

try:
    from PIL import Image, ImageDraw, ImageTk

    _HAS_PIL = True
    try:
        _LANCZOS = Image.Resampling.LANCZOS
        _RESIZE_FAST = Image.Resampling.BILINEAR
    except AttributeError:
        _LANCZOS = Image.LANCZOS
        _RESIZE_FAST = Image.BILINEAR
except ImportError:
    _HAS_PIL = False
    _LANCZOS = None
    _RESIZE_FAST = None

try:
    import numpy as np

    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False
    np = None  # type: ignore

try:
    import pystray
    from pystray import MenuItem as item

    _HAS_PYSTRAY = True
except ImportError:
    _HAS_PYSTRAY = False

# 聚光灯：圆形镂空 + 外围半透明（Windows 用 UpdateLayeredWindow 逐像素 alpha）
SPOTLIGHT_OUTSIDE_ALPHA = 168
# 椭圆先在缩小画布上绘制再双线性放大到全屏，显著降低 PIL 绘制开销
SPOTLIGHT_RENDER_MAX_EDGE = 520
# PC 端合成刷新最短间隔（秒），合并手机高频 SPOTLIGHT_UPDATE
SPOTLIGHT_PC_THROTTLE_SEC = 0.036

# 非 Windows 回退：外围颜色（略浅于纯黑，模拟压暗）
SPOTLIGHT_FALLBACK_OUTSIDE = "#151515"


def _spotlight_build_rgba_image(sw: int, sh: int, cx: float, cy: float, hw: float, hh: float):
    """归一化参数；返回 PIL RGBA（圆内全透明，圆外半透明黑）。低分辨率绘制后放大。"""
    if not _HAS_PIL:
        return None
    from PIL import Image, ImageDraw

    sw = max(1, int(sw))
    sh = max(1, int(sh))
    long_edge = max(sw, sh)
    if long_edge <= SPOTLIGHT_RENDER_MAX_EDGE:
        rw, rh = sw, sh
        scale = 1.0
    else:
        scale = SPOTLIGHT_RENDER_MAX_EDGE / float(long_edge)
        rw = max(1, int(round(sw * scale)))
        rh = max(1, int(round(sh * scale)))

    cx_px = float(cx) * rw
    cy_px = float(cy) * rh
    r = min(float(hw) * rw, float(hh) * rh)
    r = max(2.0, r)
    im = Image.new("RGBA", (rw, rh), (0, 0, 0, SPOTLIGHT_OUTSIDE_ALPHA))
    dr = ImageDraw.Draw(im)
    dr.ellipse(
        [cx_px - r, cy_px - r, cx_px + r, cy_px + r],
        fill=(0, 0, 0, 0),
    )
    if (rw != sw or rh != sh) and _RESIZE_FAST is not None:
        im = im.resize((sw, sh), _RESIZE_FAST)
    elif rw != sw or rh != sh:
        im = im.resize((sw, sh), Image.BILINEAR)
    return im


def _pil_rgba_to_bgra_bytes(pil_rgba) -> bytes:
    """RGBA → BGRA 供 GDI；优先 NumPy 向量化，否则回退。"""
    im = pil_rgba.convert("RGBA")
    w, h = im.size
    raw = im.tobytes("raw", "RGBA")
    if _HAS_NUMPY and np is not None and len(raw) == w * h * 4:
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 4)
        out = np.empty((h, w, 4), dtype=np.uint8)
        out[..., 0] = arr[..., 2]
        out[..., 1] = arr[..., 1]
        out[..., 2] = arr[..., 0]
        out[..., 3] = arr[..., 3]
        return out.tobytes()
    buf = bytearray(len(raw))
    for i in range(0, len(raw), 4):
        buf[i] = raw[i + 2]
        buf[i + 1] = raw[i + 1]
        buf[i + 2] = raw[i]
        buf[i + 3] = raw[i + 3]
    return bytes(buf)


def _win32_spotlight_init_layered(hwnd: int) -> None:
    import ctypes
    from ctypes import wintypes

    h = wintypes.HWND(int(hwnd))
    user32 = ctypes.windll.user32
    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x80000
    ex = user32.GetWindowLongW(h, GWL_EXSTYLE)
    user32.SetWindowLongW(h, GWL_EXSTYLE, ex | WS_EX_LAYERED)


def _spotlight_release_gdi_cache(inst) -> None:
    """释放复用的 CreateDIBSection / DC（隐藏或退出聚光灯时调用）。"""
    if inst is None:
        return
    c = getattr(inst, "_spotlight_gdi_cache", None)
    if not c:
        inst._spotlight_gdi_cache = None
        return
    import ctypes
    from ctypes import wintypes

    gdi32 = ctypes.windll.gdi32
    if c.get("hbmp"):
        gdi32.DeleteObject(c["hbmp"])
    if c.get("hdc_mem"):
        gdi32.DeleteDC(c["hdc_mem"])
    inst._spotlight_gdi_cache = None


def _win32_spotlight_paint_layered(inst, hwnd: int, screen_x: int, screen_y: int, pil_rgba) -> bool:
    """分层窗口位图更新；复用同尺寸 DIB，仅 memmove 新像素。"""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    ULW_ALPHA = 0x02
    AC_SRC_OVER = 0x00
    AC_SRC_ALPHA = 0x01

    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [
            ("BlendOp", ctypes.c_ubyte),
            ("BlendFlags", ctypes.c_ubyte),
            ("SourceConstantAlpha", ctypes.c_ubyte),
            ("AlphaFormat", ctypes.c_ubyte),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER)]

    w, h = pil_rgba.size
    bgra = _pil_rgba_to_bgra_bytes(pil_rgba)
    nbytes = len(bgra)

    c = getattr(inst, "_spotlight_gdi_cache", None)
    if c is None or c.get("w") != w or c.get("h") != h:
        _spotlight_release_gdi_cache(inst)
        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth = w
        header.biHeight = -h
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0
        bmi = BITMAPINFO(bmiHeader=header)

        hdc_screen = user32.GetDC(wintypes.HWND(0))
        if not hdc_screen:
            return False
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        bits = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(
            hdc_mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0
        )
        if not hbmp:
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(wintypes.HWND(0), hdc_screen)
            return False
        gdi32.SelectObject(hdc_mem, hbmp)
        user32.ReleaseDC(wintypes.HWND(0), hdc_screen)
        inst._spotlight_gdi_cache = {
            "w": w,
            "h": h,
            "hbmp": hbmp,
            "hdc_mem": hdc_mem,
            "bits": bits,
        }
        c = inst._spotlight_gdi_cache

    ctypes.memmove(c["bits"], bgra, nbytes)

    pt_dst = POINT(int(screen_x), int(screen_y))
    size_src = SIZE(int(w), int(h))
    pt_src = POINT(0, 0)
    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)

    ok = user32.UpdateLayeredWindow(
        wintypes.HWND(int(hwnd)),
        None,
        ctypes.byref(pt_dst),
        ctypes.byref(size_src),
        c["hdc_mem"],
        ctypes.byref(pt_src),
        0,
        ctypes.byref(blend),
        ULW_ALPHA,
    )
    return bool(ok)


def _tray_icon_image():
    img = Image.new("RGB", (64, 64), color=(37, 99, 235))
    d = ImageDraw.Draw(img)
    try:
        d.rounded_rectangle((10, 10, 54, 54), radius=8, outline=(255, 255, 255), width=3)
    except AttributeError:
        d.rectangle((10, 10, 54, 54), outline=(255, 255, 255), width=3)
    return img


# 界面配色：冷灰底 + 白卡片 + 单一品牌蓝，减少「系统默认控件」感
_UI = {
    "bg": "#f1f5f9",
    "surface": "#ffffff",
    "surface_alt": "#f8fafc",
    "primary": "#2563eb",
    "primary_active": "#1d4ed8",
    "stop": "#64748b",
    "stop_active": "#475569",
    "stop_muted": "#94a3b8",
    "text": "#0f172a",
    "muted": "#64748b",
    "muted_sub": "#94a3b8",
    "border": "#e2e8f0",
    "card_rim": "#e8edf3",
    "qr_rim": "#e2e8f0",
    "status_bar": "#f8fafc",
    "select_bg": "#dbeafe",
    "secondary_hover": "#f1f5f9",
}


def _ui_pack_surface_card(parent):
    """单层带 highlight 在 Windows 上易呈双线；用外圈细边 + 内白底模拟卡片。"""
    rim = tk.Frame(parent, bg=_UI["card_rim"])
    rim.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
    card = tk.Frame(rim, bg=_UI["surface"])
    card.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
    return card


def _make_btn(parent, text, cmd, primary=False):
    """统一按钮样式。模块级函数，被 PptDesktopApp._build_ui / _build_gesture_tab 共用。"""
    if primary:
        return tk.Button(
            parent,
            text=text,
            command=cmd,
            font=("Segoe UI", 9, "bold"),
            fg="#ffffff",
            bg=_UI["primary"],
            activeforeground="#ffffff",
            activebackground=_UI["primary_active"],
            relief=tk.FLAT,
            bd=0,
            padx=18,
            pady=9,
            cursor="hand2",
            highlightthickness=0,
        )
    return tk.Button(
        parent,
        text=text,
        command=cmd,
        font=("Segoe UI", 9),
        fg=_UI["text"],
        bg=_UI["surface"],
        activeforeground=_UI["text"],
        activebackground=_UI["secondary_hover"],
        relief=tk.FLAT,
        bd=0,
        padx=16,
        pady=8,
        cursor="hand2",
        highlightthickness=1,
        highlightbackground=_UI["border"],
        highlightcolor=_UI["primary"],
    )


class PptDesktopApp:
    def __init__(self):
        if tk is None:
            raise RuntimeError("需要 Python 自带 tkinter")

        self.room_id = load_or_create_room_id()
        self._qr_pil = None
        self._qr_photo = None

        self._ws_thread = None
        self._async_loop = None
        self._ws_holder = {"ws": None}
        self._tray_icon = None
        self._tray_thread = None
        self._exiting = False
        self._gesture_engine = None

        self.root = tk.Tk()
        self.root.title("PPT 遥控")
        self.root.minsize(620, 620)
        self.root.geometry("780x780")
        self.root.configure(bg=_UI["bg"])
        self._gui_settings_pause = False

        # 全屏顶置层（聚光灯 / 投屏计时）
        self._spotlight_win = None
        self._spotlight_canvas = None
        self._spotlight_key_color = "#fe01fe"
        self._spotlight_norm = (0.5, 0.5, 0.075, 0.06)
        self._spotlight_layered_ready = False
        self._spotlight_gdi_cache = None
        self._spotlight_last_paint_monotonic = 0.0
        self._spotlight_after_id = None
        self._spotlight_pending_tuple = None

        self._timer_overlay_win = None
        self._timer_label_var = None
        self._timer_after_id = None
        self._timer_mode = "countdown"
        self._timer_paused = False
        self._timer_remain = 0
        self._timer_elapsed = 0
        self._timer_initial_seconds = 0

        self._build_ui()

        global _ppt_app_instance
        _ppt_app_instance = self
        self._sync_settings_vars_from_model()
        self._refresh_downloads_list()

        self.root.protocol("WM_DELETE_WINDOW", self._on_user_close)
        try:
            self.root.bind("<Unmap>", self._on_unmap_maybe_tray)
        except tk.TclError:
            pass

        self._refresh_qr_display_once()

    def _status(self, text: str):
        def u():
            if self._exiting:
                return
            self.status_var.set(text)

        self.root.after(0, u)

    def _set_pairing_title_mobile_online(self, online: bool):
        if self._exiting or not hasattr(self, "pairing_title_var"):
            return
        self.pairing_title_var.set(
            "配对码（移动端已就绪）" if online else "配对码（移动端未连接）"
        )

    @staticmethod
    def _clamp_spotlight_norm(cx, cy, half_w, half_h):
        try:
            hw = float(half_w)
            hh = float(half_h)
        except (TypeError, ValueError):
            hw, hh = 0.075, 0.06
        hw = max(0.02, min(0.48, hw))
        hh = max(0.02, min(0.48, hh))
        try:
            cx = float(cx)
            cy = float(cy)
        except (TypeError, ValueError):
            cx, cy = 0.5, 0.5
        r_norm = min(hw, hh)
        cx = max(r_norm, min(1.0 - r_norm, cx))
        cy = max(r_norm, min(1.0 - r_norm, cy))
        return cx, cy, hw, hh

    def _gui_spotlight_apply(self, payload) -> None:
        if self._exiting:
            return
        if not isinstance(payload, dict):
            payload = {}
        cx, cy, hw, hh = self._clamp_spotlight_norm(
            payload.get("cx", self._spotlight_norm[0]),
            payload.get("cy", self._spotlight_norm[1]),
            payload.get("halfW", self._spotlight_norm[2]),
            payload.get("halfH", self._spotlight_norm[3]),
        )
        self._spotlight_norm = (cx, cy, hw, hh)
        try:
            import pyautogui

            sw, sh = pyautogui.size()
        except Exception:
            return

        self._spotlight_pending_tuple = (cx, cy, hw, hh, sw, sh)
        self._spotlight_request_paint()

    def _spotlight_request_paint(self) -> None:
        if self._exiting or self._spotlight_pending_tuple is None:
            return
        if self._spotlight_after_id is not None:
            return
        now = time.monotonic()
        last = self._spotlight_last_paint_monotonic
        if last <= 0.0 or (now - last) >= SPOTLIGHT_PC_THROTTLE_SEC:
            self._spotlight_do_paint_now()
            self._spotlight_last_paint_monotonic = time.monotonic()
            return

        rem_ms = max(1, int((SPOTLIGHT_PC_THROTTLE_SEC - (now - last)) * 1000) + 1)

        def _delayed():
            self._spotlight_after_id = None
            if self._exiting:
                return
            self._spotlight_do_paint_now()
            self._spotlight_last_paint_monotonic = time.monotonic()

        self._spotlight_after_id = self.root.after(rem_ms, _delayed)

    def _spotlight_do_paint_now(self) -> None:
        if self._exiting:
            return
        p = self._spotlight_pending_tuple
        if not p:
            return
        cx, cy, hw, hh, sw, sh = p

        use_win_layered = sys.platform == "win32" and _HAS_PIL
        key = self._spotlight_key_color

        if self._spotlight_win is None:
            w = tk.Toplevel(self.root)
            w.overrideredirect(True)
            try:
                w.attributes("-topmost", True)
            except tk.TclError:
                pass
            if use_win_layered:
                self._spotlight_win = w
                self._spotlight_canvas = None
            else:
                try:
                    w.attributes("-transparentcolor", key)
                except tk.TclError:
                    pass
                cv = tk.Canvas(
                    w,
                    highlightthickness=0,
                    bg=SPOTLIGHT_FALLBACK_OUTSIDE,
                    bd=0,
                )
                cv.pack(fill=tk.BOTH, expand=True)
                self._spotlight_win = w
                self._spotlight_canvas = cv
            self._spotlight_layered_ready = False

        self._spotlight_win.geometry(f"{int(sw)}x{int(sh)}+0+0")
        self._spotlight_win.update_idletasks()

        if use_win_layered:
            img = _spotlight_build_rgba_image(sw, sh, cx, cy, hw, hh)
            if img is None:
                return
            hwnd = int(self._spotlight_win.winfo_id())
            if not self._spotlight_layered_ready:
                _win32_spotlight_init_layered(hwnd)
                self._spotlight_layered_ready = True
            rx = int(self._spotlight_win.winfo_rootx())
            ry = int(self._spotlight_win.winfo_rooty())
            _win32_spotlight_paint_layered(self, hwnd, rx, ry, img)
        else:
            cv = self._spotlight_canvas
            if cv is None:
                return
            cv.config(width=sw, height=sh)
            cv.delete("all")
            cx_px = cx * sw
            cy_px = cy * sh
            r = min(hw * sw, hh * sh)
            x1 = cx_px - r
            y1 = cy_px - r
            x2 = cx_px + r
            y2 = cy_px + r
            cv.create_rectangle(
                0,
                0,
                sw,
                sh,
                fill=SPOTLIGHT_FALLBACK_OUTSIDE,
                outline=SPOTLIGHT_FALLBACK_OUTSIDE,
                width=0,
            )
            cv.create_oval(x1, y1, x2, y2, fill=key, outline=key, width=0)
        try:
            self._spotlight_win.lift()
            self._spotlight_win.attributes("-topmost", True)
        except tk.TclError:
            pass

    def _gui_spotlight_hide(self) -> None:
        if self._spotlight_after_id is not None:
            try:
                self.root.after_cancel(self._spotlight_after_id)
            except Exception:
                pass
            self._spotlight_after_id = None
        self._spotlight_pending_tuple = None
        self._spotlight_last_paint_monotonic = 0.0
        _spotlight_release_gdi_cache(self)
        if self._spotlight_win is not None:
            try:
                self._spotlight_win.destroy()
            except tk.TclError:
                pass
            self._spotlight_win = None
            self._spotlight_canvas = None
            self._spotlight_layered_ready = False

    @staticmethod
    def _format_timer_label(total_sec: int) -> str:
        s = max(0, int(total_sec))
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        if h > 0:
            return f"{h:d}:{m:02d}:{sec:02d}"
        return f"{m:02d}:{sec:02d}"

    def _timer_cancel_after(self) -> None:
        if self._timer_after_id is not None:
            try:
                self.root.after_cancel(self._timer_after_id)
            except Exception:
                pass
            self._timer_after_id = None

    def _gui_timer_overlay_tick(self) -> None:
        if self._exiting or self._timer_overlay_win is None:
            return
        if self._timer_paused:
            return
        if self._timer_mode == "countdown":
            self._timer_remain -= 1
            if self._timer_remain < 0:
                self._timer_remain = 0
            disp = self._timer_remain
            if self._timer_label_var is not None:
                self._timer_label_var.set(self._format_timer_label(disp))
            if self._timer_remain <= 0:
                return
        else:
            self._timer_elapsed += 1
            disp = self._timer_elapsed
            v = self._timer_label_var
            if v is not None:
                v.set(self._format_timer_label(disp))
        self._timer_after_id = self.root.after(1000, self._gui_timer_overlay_tick)

    def _ensure_timer_overlay_window(self) -> None:
        if self._timer_overlay_win is not None:
            try:
                import pyautogui

                sw, sh = pyautogui.size()
                self._timer_overlay_win.geometry(f"{int(sw)}x{int(sh)}+0+0")
            except Exception:
                pass
            return
        try:
            import pyautogui

            sw, sh = pyautogui.size()
        except Exception:
            return
        w = tk.Toplevel(self.root)
        w.overrideredirect(True)
        try:
            w.attributes("-topmost", True)
        except tk.TclError:
            pass
        w.configure(bg="#1a1a1a")
        w.geometry(f"{int(sw)}x{int(sh)}+0+0")
        self._timer_label_var = tk.StringVar(value="00:00")
        lbl = tk.Label(
            w,
            textvariable=self._timer_label_var,
            fg="#ffffff",
            bg="#1a1a1a",
            font=("Segoe UI", 96, "bold"),
        )
        lbl.place(relx=0.5, rely=0.5, anchor="center")
        self._timer_overlay_win = w
        try:
            w.lift()
        except tk.TclError:
            pass

    def _gui_timer_overlay_show(self, payload) -> None:
        if self._exiting:
            return
        if not isinstance(payload, dict):
            payload = {}
        mode = str(payload.get("mode") or "countdown").lower()
        if mode not in ("countdown", "stopwatch"):
            mode = "countdown"
        self._timer_mode = mode
        try:
            sec = int(payload.get("seconds", 0))
        except (TypeError, ValueError):
            sec = 0
        if mode == "countdown":
            self._timer_initial_seconds = max(0, sec)
            self._timer_remain = self._timer_initial_seconds
            disp = self._timer_remain
        else:
            self._timer_initial_seconds = 0
            self._timer_elapsed = max(0, sec)
            disp = self._timer_elapsed
        self._timer_paused = False
        self._ensure_timer_overlay_window()
        if self._timer_label_var is not None:
            self._timer_label_var.set(self._format_timer_label(disp))
        self._timer_cancel_after()
        self._timer_after_id = self.root.after(1000, self._gui_timer_overlay_tick)

    def _gui_timer_overlay_hide(self) -> None:
        self._timer_cancel_after()
        if self._timer_overlay_win is not None:
            try:
                self._timer_overlay_win.destroy()
            except tk.TclError:
                pass
            self._timer_overlay_win = None
            self._timer_label_var = None

    def _gui_timer_overlay_pause(self) -> None:
        self._timer_paused = True
        self._timer_cancel_after()

    def _gui_timer_overlay_resume(self) -> None:
        if self._timer_overlay_win is None:
            return
        self._timer_paused = False
        self._timer_cancel_after()
        self._timer_after_id = self.root.after(1000, self._gui_timer_overlay_tick)

    def _gui_timer_overlay_reset(self, payload) -> None:
        if not isinstance(payload, dict):
            payload = {}
        try:
            sec = int(payload.get("seconds", 0))
        except (TypeError, ValueError):
            sec = 0
        if self._timer_mode == "countdown":
            self._timer_remain = max(0, sec)
            self._timer_initial_seconds = self._timer_remain
            d = self._timer_remain
        else:
            self._timer_elapsed = max(0, sec)
            d = self._timer_elapsed
        if self._timer_label_var is not None:
            self._timer_label_var.set(self._format_timer_label(d))
        if self._timer_overlay_win is not None and not self._timer_paused:
            self._timer_cancel_after()
            self._timer_after_id = self.root.after(1000, self._gui_timer_overlay_tick)

    def _dispose_all_overlays(self) -> None:
        try:
            self._timer_cancel_after()
        except Exception:
            pass
        if self._timer_overlay_win is not None:
            try:
                self._timer_overlay_win.destroy()
            except tk.TclError:
                pass
            self._timer_overlay_win = None
            self._timer_label_var = None
        if self._spotlight_after_id is not None:
            try:
                self.root.after_cancel(self._spotlight_after_id)
            except Exception:
                pass
            self._spotlight_after_id = None
        self._spotlight_pending_tuple = None
        self._spotlight_last_paint_monotonic = 0.0
        _spotlight_release_gdi_cache(self)
        if self._spotlight_win is not None:
            try:
                self._spotlight_win.destroy()
            except tk.TclError:
                pass
            self._spotlight_win = None
            self._spotlight_canvas = None
            self._spotlight_layered_ready = False

    def _build_ui(self):
        self.status_var = tk.StringVar(value="就绪 · 未连接")

        outer = tk.Frame(self.root, bg=_UI["bg"])
        outer.pack(fill=tk.BOTH, expand=True)

        brand_bar = tk.Frame(outer, height=3, bg=_UI["primary"])
        brand_bar.pack(fill=tk.X)
        brand_bar.pack_propagate(False)

        # 顶栏：品牌区 + 服务开关（单按钮双状态）
        header = tk.Frame(outer, bg=_UI["surface"], highlightthickness=0)
        header.pack(fill=tk.X, padx=0, pady=0)
        head_inner = tk.Frame(header, bg=_UI["surface"])
        head_inner.pack(fill=tk.X, padx=32, pady=(22, 20))

        brand = tk.Frame(head_inner, bg=_UI["surface"])
        brand.pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(
            brand,
            text="PPT 遥控",
            font=("Segoe UI", 20, "bold"),
            fg=_UI["text"],
            bg=_UI["surface"],
        ).pack(anchor=tk.W)
        tk.Label(
            brand,
            text="电脑端接收端 · 扫码与手机配对",
            font=("Segoe UI", 10),
            fg=_UI["muted"],
            bg=_UI["surface"],
        ).pack(anchor=tk.W, pady=(6, 0))

        self._toggle_btn = tk.Button(
            head_inner,
            text="启动服务",
            command=self._on_toggle_service,
            font=("Segoe UI", 10, "bold"),
            fg="#ffffff",
            bg=_UI["primary"],
            activeforeground="#ffffff",
            activebackground=_UI["primary_active"],
            relief=tk.FLAT,
            bd=0,
            padx=26,
            pady=11,
            cursor="hand2",
            highlightthickness=0,
        )
        self._toggle_btn.pack(side=tk.RIGHT, anchor=tk.CENTER)

        head_sep = tk.Frame(outer, height=1, bg=_UI["border"])
        head_sep.pack(fill=tk.X)
        head_sep.pack_propagate(False)

        try:
            style = ttk.Style()
            style.theme_use("clam")
            style.configure("TSeparator", background=_UI["border"])
            style.configure("TFrame", background=_UI["bg"])
            style.configure("TNotebook", background=_UI["bg"], borderwidth=0, tabmargins=[10, 6, 10, 0])
            style.configure(
                "TNotebook.Tab",
                padding=(18, 10),
                font=("Segoe UI", 10),
            )
            try:
                style.map(
                    "TNotebook.Tab",
                    background=[("selected", _UI["surface"]), ("!selected", _UI["bg"])],
                    foreground=[("selected", _UI["text"]), ("!selected", _UI["muted"])],
                    font=[
                        ("selected", ("Segoe UI", 10, "bold")),
                        ("!selected", ("Segoe UI", 10)),
                    ],
                )
            except tk.TclError:
                style.map(
                    "TNotebook.Tab",
                    background=[("selected", _UI["surface"]), ("!selected", _UI["bg"])],
                    foreground=[("selected", _UI["text"]), ("!selected", _UI["muted"])],
                )
        except tk.TclError:
            pass

        # 底栏固定在最下方，主内容在中间扩展
        status_bar = tk.Frame(outer, bg=_UI["status_bar"], highlightthickness=0)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        stat_top = tk.Frame(status_bar, height=1, bg=_UI["border"])
        stat_top.pack(fill=tk.X)
        stat_top.pack_propagate(False)
        tk.Label(
            status_bar,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            fg=_UI["muted"],
            bg=_UI["status_bar"],
            anchor=tk.W,
        ).pack(fill=tk.X, padx=32, pady=14)

        _wrap = 620

        # 主内容：选项卡（默认「二维码信息」）
        main = tk.Frame(outer, bg=_UI["bg"])
        main.pack(fill=tk.BOTH, expand=True, padx=28, pady=(10, 16))

        self._notebook = ttk.Notebook(main)
        self._notebook.pack(fill=tk.BOTH, expand=True)

        tab_qr = tk.Frame(self._notebook, bg=_UI["bg"])
        tab_behavior = tk.Frame(self._notebook, bg=_UI["bg"])
        tab_transfer = tk.Frame(self._notebook, bg=_UI["bg"])
        tab_gesture = tk.Frame(self._notebook, bg=_UI["bg"])

        self._notebook.add(tab_qr, text="二维码信息")
        self._notebook.add(tab_behavior, text="行为设置")
        self._notebook.add(tab_transfer, text="文件传输")
        self._notebook.add(tab_gesture, text="手势控制")

        # —— 选项卡 1：二维码信息 ——
        card = _ui_pack_surface_card(tab_qr)

        card_pad = tk.Frame(card, bg=_UI["surface"])
        card_pad.pack(fill=tk.BOTH, expand=True, padx=32, pady=32)

        self.pairing_title_var = tk.StringVar(value="配对码（移动端未连接）")
        tk.Label(
            card_pad,
            textvariable=self.pairing_title_var,
            font=("Segoe UI", 10),
            fg=_UI["muted"],
            bg=_UI["surface"],
        ).pack(anchor=tk.W)

        self.room_label = tk.Label(
            card_pad,
            text=self.room_id,
            font=("Segoe UI", 26, "bold"),
            fg=_UI["primary"],
            bg=_UI["surface"],
        )
        self.room_label.pack(anchor=tk.W, pady=(4, 0))

        tk.Label(
            card_pad,
            text="已保存在本机，下次打开仍为同一配对码",
            font=("Segoe UI", 9),
            fg=_UI["muted_sub"],
            bg=_UI["surface"],
        ).pack(anchor=tk.W, pady=(8, 0))

        qr_outer = tk.Frame(card_pad, bg=_UI["qr_rim"])
        qr_outer.pack(pady=(28, 20), anchor=tk.CENTER)
        qr_inner = tk.Frame(qr_outer, bg=_UI["surface_alt"])
        qr_inner.pack(padx=1, pady=1)

        self.qr_label = tk.Label(qr_inner, bg=_UI["surface_alt"])
        self.qr_label.pack(padx=20, pady=20)

        tk.Label(
            card_pad,
            text="使用手机微信或配套小程序扫描上方二维码，输入配对码亦可",
            font=("Segoe UI", 9),
            fg=_UI["muted"],
            bg=_UI["surface"],
            wraplength=_wrap,
            justify=tk.LEFT,
        ).pack(anchor=tk.W)

        tk.Label(
            card_pad,
            text="点击窗口关闭按钮将退出本程序（不后台运行）。从任务栏最小化时仍可进入系统托盘",
            font=("Segoe UI", 8),
            fg=_UI["muted_sub"],
            bg=_UI["surface"],
            wraplength=_wrap,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(14, 0))

        foot = tk.Frame(card_pad, bg=_UI["surface"])
        foot.pack(fill=tk.X, pady=(20, 0))
        ttk.Separator(foot, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 12))
        tk.Label(
            foot,
            text="需要更换配对码时，删除程序目录下的 ppt_pc_client_room.json 后重新打开",
            font=("Segoe UI", 8),
            fg=_UI["muted_sub"],
            bg=_UI["surface"],
            wraplength=_wrap,
            justify=tk.LEFT,
        ).pack(anchor=tk.W)

        # —— 选项卡 2：行为设置 ——
        _s0 = get_settings_snapshot()
        self._var_screenshot = tk.BooleanVar(value=_s0["screenshot_open_folder"])
        self._var_transfer_folder = tk.BooleanVar(value=_s0["transfer_open_folder"])
        self._var_transfer_ppt = tk.BooleanVar(value=_s0["transfer_open_ppt"])
        self._var_ppt_notes = tk.BooleanVar(value=bool(_s0.get("ppt_notes_enabled")))
        self._var_open_ppt_path = tk.StringVar(value=_s0.get("open_ppt_path") or "")

        settings_card = _ui_pack_surface_card(tab_behavior)

        sp = tk.Frame(settings_card, bg=_UI["surface"])
        sp.pack(fill=tk.BOTH, expand=True, padx=32, pady=28)

        tk.Label(
            sp,
            text="行为设置",
            font=("Segoe UI", 12, "bold"),
            fg=_UI["text"],
            bg=_UI["surface"],
        ).pack(anchor=tk.W)

        tk.Label(
            sp,
            text="与手机小程序「遥控设置」中的开关一致，连接时手机端会覆盖此处对应项",
            font=("Segoe UI", 9),
            fg=_UI["muted_sub"],
            bg=_UI["surface"],
            wraplength=_wrap,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(6, 16))

        def _row_check(parent, text, var):
            row = tk.Frame(parent, bg=_UI["surface"])
            row.pack(fill=tk.X, pady=8)
            tk.Checkbutton(
                row,
                text=text,
                variable=var,
                command=self._persist_settings_from_widgets,
                font=("Segoe UI", 10),
                fg=_UI["text"],
                bg=_UI["surface"],
                activebackground=_UI["surface"],
                activeforeground=_UI["text"],
                selectcolor=_UI["select_bg"],
                anchor=tk.W,
                highlightthickness=0,
            ).pack(side=tk.LEFT)

        _row_check(sp, "截屏后打开文件夹（定位到截图文件）", self._var_screenshot)
        _row_check(sp, "传输非演示文稿时打开文件夹", self._var_transfer_folder)
        _row_check(sp, "传输演示文稿时自动打开", self._var_transfer_ppt)
        _row_check(
            sp,
            "演讲者模式（同步到手机；放映时读取备注，需本机 PowerPoint 或 WPS 演示 + pywin32）",
            self._var_ppt_notes,
        )

        ttk.Separator(sp, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(20, 16))

        tk.Label(
            sp,
            text="启动 PPT 默认文件",
            font=("Segoe UI", 11, "bold"),
            fg=_UI["text"],
            bg=_UI["surface"],
        ).pack(anchor=tk.W)
        tk.Label(
            sp,
            text="收到「启动 PPT」指令时优先打开此文件；留空则打开临时空白文稿",
            font=("Segoe UI", 9),
            fg=_UI["muted_sub"],
            bg=_UI["surface"],
            wraplength=_wrap,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(4, 10))

        path_row = tk.Frame(sp, bg=_UI["surface"])
        path_row.pack(fill=tk.X)
        self._entry_open_ppt = tk.Entry(
            path_row,
            textvariable=self._var_open_ppt_path,
            font=("Segoe UI", 9),
            fg=_UI["text"],
            bg=_UI["surface_alt"],
            insertbackground=_UI["text"],
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=_UI["border"],
            highlightcolor=_UI["primary"],
        )
        self._entry_open_ppt.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8)

        btn_row = tk.Frame(sp, bg=_UI["surface"])
        btn_row.pack(fill=tk.X, pady=(10, 0))

        _make_btn(btn_row, "浏览…", self._browse_open_ppt_path, primary=True).pack(side=tk.LEFT, padx=(0, 10))
        _make_btn(btn_row, "清除", self._clear_open_ppt_path, primary=False).pack(side=tk.LEFT)

        self._entry_open_ppt.bind("<FocusOut>", lambda _e: self._persist_settings_from_widgets())

        # —— 选项卡 3：文件传输 ——
        transfer_card = _ui_pack_surface_card(tab_transfer)

        tp = tk.Frame(transfer_card, bg=_UI["surface"])
        tp.pack(fill=tk.BOTH, expand=True, padx=32, pady=28)

        tk.Label(
            tp,
            text="最近传输",
            font=("Segoe UI", 12, "bold"),
            fg=_UI["text"],
            bg=_UI["surface"],
        ).pack(anchor=tk.W)

        tk.Label(
            tp,
            text="从手机发送到本机的文件记录；可选中后在文件夹中显示",
            font=("Segoe UI", 9),
            fg=_UI["muted_sub"],
            bg=_UI["surface"],
            wraplength=_wrap,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(6, 14))

        dl_tool = tk.Frame(tp, bg=_UI["surface"])
        dl_tool.pack(fill=tk.X, pady=(0, 4))
        _make_btn(dl_tool, "在文件夹中显示所选", self._downloads_reveal_selected, primary=True).pack(
            side=tk.LEFT, padx=(0, 10)
        )
        _make_btn(dl_tool, "打开保存目录", self._open_save_dir, primary=False).pack(side=tk.LEFT)

        list_frame = tk.Frame(tp, bg=_UI["surface"])
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        dl_scroll = tk.Scrollbar(list_frame)
        dl_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._downloads_listbox = tk.Listbox(
            list_frame,
            height=14,
            font=("Segoe UI", 9),
            fg=_UI["text"],
            bg=_UI["surface_alt"],
            selectmode=tk.SINGLE,
            selectbackground=_UI["select_bg"],
            selectforeground=_UI["text"],
            activestyle="none",
            yscrollcommand=dl_scroll.set,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=_UI["border"],
            highlightcolor=_UI["primary"],
        )
        self._downloads_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        dl_scroll.config(command=self._downloads_listbox.yview)
        self._downloads_paths = []

        self._build_gesture_tab(tab_gesture, _wrap)

    def _build_gesture_tab(self, parent, wrap: int):
        from pc_gesture.config import load_gesture_config

        gcfg = load_gesture_config()
        gesture_card = _ui_pack_surface_card(parent)
        gp = tk.Frame(gesture_card, bg=_UI["surface"])
        gp.pack(fill=tk.BOTH, expand=True, padx=32, pady=28)

        tk.Label(
            gp,
            text="摄像头手势控制",
            font=("Segoe UI", 12, "bold"),
            fg=_UI["text"],
            bg=_UI["surface"],
        ).pack(anchor=tk.W)
        tk.Label(
            gp,
            text="本地识别，无需连接手机。需安装 mediapipe、opencv-python；首次使用将自动下载模型。",
            font=("Segoe UI", 9),
            fg=_UI["muted_sub"],
            bg=_UI["surface"],
            wraplength=wrap,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(6, 14))

        self._var_gesture_preview = tk.BooleanVar(value=gcfg.preview_only)
        self._var_gesture_mirror = tk.BooleanVar(value=bool(gcfg.raw.get("mirror", True)))
        self._var_gesture_operator = tk.StringVar(
            value="dual" if gcfg.operator_mode == "dual" else "single"
        )
        self._var_gesture_swapped = tk.BooleanVar(value=gcfg.dual_roles_swapped)
        self._gesture_status_var = tk.StringVar(value="未启动")
        self._gesture_fps_var = tk.StringVar(value="FPS: —")

        row0 = tk.Frame(gp, bg=_UI["surface"])
        row0.pack(fill=tk.X, pady=6)
        _make_btn(row0, "启动手势", self._gesture_start, primary=True).pack(side=tk.LEFT, padx=(0, 8))
        _make_btn(row0, "停止", self._gesture_stop, primary=False).pack(side=tk.LEFT, padx=(0, 8))
        tk.Checkbutton(
            row0,
            text="仅预览不执行指令",
            variable=self._var_gesture_preview,
            command=self._gesture_save_options,
            font=("Segoe UI", 10),
            fg=_UI["text"],
            bg=_UI["surface"],
            activebackground=_UI["surface"],
            selectcolor=_UI["select_bg"],
            highlightthickness=0,
        ).pack(side=tk.LEFT, padx=(12, 0))

        row1 = tk.Frame(gp, bg=_UI["surface"])
        row1.pack(fill=tk.X, pady=8)
        tk.Label(row1, text="操作者模式", font=("Segoe UI", 10), fg=_UI["text"], bg=_UI["surface"]).pack(
            side=tk.LEFT
        )
        tk.Radiobutton(
            row1,
            text="单人主控",
            variable=self._var_gesture_operator,
            value="single",
            command=self._gesture_save_options,
            font=("Segoe UI", 10),
            fg=_UI["text"],
            bg=_UI["surface"],
            selectcolor=_UI["select_bg"],
            highlightthickness=0,
        ).pack(side=tk.LEFT, padx=(12, 4))
        tk.Radiobutton(
            row1,
            text="双人协作",
            variable=self._var_gesture_operator,
            value="dual",
            command=self._gesture_save_options,
            font=("Segoe UI", 10),
            fg=_UI["text"],
            bg=_UI["surface"],
            selectcolor=_UI["select_bg"],
            highlightthickness=0,
        ).pack(side=tk.LEFT)

        row2 = tk.Frame(gp, bg=_UI["surface"])
        row2.pack(fill=tk.X, pady=6)
        tk.Checkbutton(
            row2,
            text="镜像画面",
            variable=self._var_gesture_mirror,
            command=self._gesture_save_options,
            font=("Segoe UI", 10),
            fg=_UI["text"],
            bg=_UI["surface"],
            selectcolor=_UI["select_bg"],
            highlightthickness=0,
        ).pack(side=tk.LEFT)
        tk.Checkbutton(
            row2,
            text="交换 A/B 职责（左导航/右指控）",
            variable=self._var_gesture_swapped,
            command=self._gesture_swap_roles,
            font=("Segoe UI", 10),
            fg=_UI["text"],
            bg=_UI["surface"],
            selectcolor=_UI["select_bg"],
            highlightthickness=0,
        ).pack(side=tk.LEFT, padx=(16, 0))

        row3 = tk.Frame(gp, bg=_UI["surface"])
        row3.pack(fill=tk.X, pady=6)
        _make_btn(row3, "开始双人配对", self._gesture_start_pairing, primary=False).pack(side=tk.LEFT, padx=(0, 8))
        _make_btn(row3, "重新配对", self._gesture_reset_pairing, primary=False).pack(side=tk.LEFT)

        ttk.Separator(gp, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(16, 12))
        tk.Label(
            gp,
            textvariable=self._gesture_status_var,
            font=("Segoe UI", 10),
            fg=_UI["primary"],
            bg=_UI["surface"],
            wraplength=wrap,
            justify=tk.LEFT,
        ).pack(anchor=tk.W)
        tk.Label(
            gp,
            textvariable=self._gesture_fps_var,
            font=("Segoe UI", 9),
            fg=_UI["muted"],
            bg=_UI["surface"],
        ).pack(anchor=tk.W, pady=(4, 0))
        tk.Label(
            gp,
            text="手势：食指移动=激光 · 捏合=点击 · 左右挥=翻页 · 握拳/张掌=黑/白屏 · 竖拇指=F5 · 拇指向下=退出 · 托掌进轮盘",
            font=("Segoe UI", 8),
            fg=_UI["muted_sub"],
            bg=_UI["surface"],
            wraplength=wrap,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(12, 0))

    def _ensure_gesture_engine(self):
        if self._gesture_engine is not None:
            return self._gesture_engine
        try:
            from pc_gesture.engine import GestureEngine
        except ImportError as e:
            raise RuntimeError(f"无法加载 pc_gesture：{e}") from e

        def _dispatch(data, source="gesture"):
            dispatch_remote_command(data, source)

        self._gesture_engine = GestureEngine(
            dispatch_fn=_dispatch,
            on_status=self._gesture_on_status,
            on_fps=self._gesture_on_fps,
            on_send_text=self._gesture_send_text_dialog,
        )
        return self._gesture_engine

    def _gesture_save_options(self):
        try:
            from pc_gesture.config import load_gesture_config, save_gesture_config
        except ImportError:
            return
        eng = self._gesture_engine
        cfg = load_gesture_config()
        cfg.raw["preview_only"] = bool(self._var_gesture_preview.get())
        cfg.raw["mirror"] = bool(self._var_gesture_mirror.get())
        cfg.raw["operator_mode"] = self._var_gesture_operator.get()
        cfg.raw["dual_roles_swapped"] = bool(self._var_gesture_swapped.get())
        cfg.raw["enabled"] = True
        save_gesture_config(cfg)
        if eng:
            eng.cfg = cfg
            eng._semantics.reload_config(cfg)

    def _gesture_start(self):
        try:
            self._gesture_save_options()
            eng = self._ensure_gesture_engine()
            eng.cfg.raw["enabled"] = not bool(self._var_gesture_preview.get())
            eng.cfg.raw["preview_only"] = bool(self._var_gesture_preview.get())
            eng.save_config()
            err = eng.start()
            if err:
                self._gesture_status_var.set(err)
                self._status(f"手势：{err}")
            else:
                self._status("手势识别已启动")
        except Exception as e:
            self._gesture_status_var.set(str(e))
            self._status(f"手势启动失败：{e}")

    def _gesture_stop(self):
        if self._gesture_engine:
            self._gesture_engine.stop()
        self._gesture_status_var.set("已停止")
        self._gesture_fps_var.set("FPS: —")

    def _gesture_on_status(self, msg: str):
        def u():
            if self._exiting:
                return
            self._gesture_status_var.set(msg)

        try:
            self.root.after(0, u)
        except Exception:
            pass

    def _gesture_on_fps(self, fps: float):
        def u():
            if self._exiting:
                return
            self._gesture_fps_var.set(f"FPS: {fps:.1f}")

        try:
            self.root.after(0, u)
        except Exception:
            pass

    def _gesture_send_text_dialog(self):
        from tkinter import simpledialog

        def ask():
            if self._exiting:
                return
            text = simpledialog.askstring("发文本", "输入要发送到前台的文本：", parent=self.root)
            if text:
                dispatch_remote_command({"cmd": "SEND_TEXT", "text": text}, "gesture")

        try:
            self.root.after(0, ask)
        except Exception:
            pass

    def _gesture_start_pairing(self):
        self._var_gesture_operator.set("dual")
        self._gesture_save_options()
        try:
            eng = self._ensure_gesture_engine()
            if not eng.running:
                err = eng.start()
                if err:
                    self._gesture_status_var.set(err)
                    return
            eng.start_pairing()
            self._gesture_status_var.set("双人配对：请左侧协作者竖食指 1 秒")
        except Exception as e:
            self._gesture_status_var.set(str(e))

    def _gesture_reset_pairing(self):
        if self._gesture_engine:
            self._gesture_engine.reset_pairing()
        self._gesture_status_var.set("已重置配对")

    def _gesture_swap_roles(self):
        swapped = bool(self._var_gesture_swapped.get())
        try:
            from pc_gesture.config import load_gesture_config, save_gesture_config

            cfg = load_gesture_config()
            cfg.raw["dual_roles_swapped"] = swapped
            save_gesture_config(cfg)
            if self._gesture_engine:
                self._gesture_engine.cfg = cfg
                self._gesture_engine._semantics.reload_config(cfg)
        except ImportError:
            pass
        self._gesture_status_var.set("已交换 A/B 职责" if swapped else "已恢复默认职责（左指控右导航）")

    def _persist_settings_from_widgets(self):
        if self._gui_settings_pause or self._exiting:
            return
        set_client_settings(
            screenshot_open_folder=self._var_screenshot.get(),
            transfer_open_folder=self._var_transfer_folder.get(),
            transfer_open_ppt=self._var_transfer_ppt.get(),
            ppt_notes_enabled=self._var_ppt_notes.get(),
            open_ppt_path=self._var_open_ppt_path.get().strip(),
        )
        broadcast_client_settings_to_mobile()
        _ppt_notes_on_settings_changed()

    def _sync_settings_vars_from_model(self):
        if self._exiting or not hasattr(self, "_var_screenshot"):
            return
        self._gui_settings_pause = True
        try:
            s = get_settings_snapshot()
            self._var_screenshot.set(bool(s.get("screenshot_open_folder")))
            self._var_transfer_folder.set(bool(s.get("transfer_open_folder")))
            self._var_transfer_ppt.set(bool(s.get("transfer_open_ppt")))
            if hasattr(self, "_var_ppt_notes"):
                self._var_ppt_notes.set(bool(s.get("ppt_notes_enabled")))
            self._var_open_ppt_path.set(str(s.get("open_ppt_path") or ""))
        finally:
            self._gui_settings_pause = False

    def _browse_open_ppt_path(self):
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择「启动 PPT」默认打开的演示文稿",
            filetypes=[
                ("演示文稿", "*.ppt *.pptx *.pptm *.pps *.ppsx *.pot *.potx"),
                ("全部文件", "*.*"),
            ],
        )
        if path:
            self._var_open_ppt_path.set(path)
            set_client_settings(open_ppt_path=path)

    def _clear_open_ppt_path(self):
        self._var_open_ppt_path.set("")
        set_client_settings(open_ppt_path="")

    def _refresh_downloads_list(self):
        if self._exiting or not hasattr(self, "_downloads_listbox"):
            return
        self._downloads_listbox.delete(0, tk.END)
        records = load_download_records()
        self._downloads_paths = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            p = rec.get("path") or ""
            name = rec.get("name") or os.path.basename(p) or "—"
            ts = rec.get("ts")
            try:
                tstr = time.strftime("%m-%d %H:%M", time.localtime(float(ts))) if ts else "—"
            except Exception:
                tstr = "—"
            self._downloads_listbox.insert(tk.END, f"{tstr}  {name}")
            self._downloads_paths.append(p)

    def _downloads_reveal_selected(self):
        sel = self._downloads_listbox.curselection()
        if not sel:
            self._status("请先在列表中选择一条传输记录")
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self._downloads_paths):
            return
        p = self._downloads_paths[idx]
        if p and os.path.isfile(p):
            explorer_select_file(p)
        else:
            self._status("文件已不存在，可打开保存目录查看")

    def _open_save_dir(self):
        d = os.path.abspath(SAVE_DIR)
        if os.path.isdir(d):
            explorer_open_folder(d)
        else:
            self._status("保存目录不存在")

    def refresh_service_button(self):
        if self._exiting or not hasattr(self, "_toggle_btn"):
            return
        alive = self._ws_thread is not None and self._ws_thread.is_alive()
        if alive:
            self._toggle_btn.configure(
                text="停止服务",
                fg=_UI["stop"],
                bg=_UI["surface"],
                activeforeground=_UI["stop_active"],
                activebackground=_UI["secondary_hover"],
                highlightthickness=1,
                highlightbackground=_UI["stop_muted"],
                highlightcolor=_UI["stop"],
            )
        else:
            self._toggle_btn.configure(
                text="启动服务",
                fg="#ffffff",
                bg=_UI["primary"],
                activeforeground="#ffffff",
                activebackground=_UI["primary_active"],
                highlightthickness=0,
            )

    def _on_toggle_service(self):
        alive = self._ws_thread is not None and self._ws_thread.is_alive()
        if alive:
            self.stop_service()
        else:
            self.start_service()

    def _make_qr_pil(self):
        if not _HAS_PIL:
            return None
        qr = qrcode.QRCode(version=1, box_size=6, border=2)
        qr.add_data(self.room_id)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        return img.resize((268, 268), _LANCZOS)

    def _refresh_qr_display_once(self):
        """仅按当前 room_id 生成本地图一次并显示；room_id 来自磁盘缓存，不会每次启动换新。"""
        if not _HAS_PIL:
            self.qr_label.configure(text="请安装 Pillow：pip install pillow")
            return
        self._qr_pil = self._make_qr_pil()
        self._qr_photo = ImageTk.PhotoImage(self._qr_pil)
        self.qr_label.configure(image=self._qr_photo, text="")

    def _ensure_tray(self):
        if not _HAS_PYSTRAY:
            self.root.iconify()
            self._status("未安装 pystray，已最小化到任务栏（pip install pystray pillow）")
            return

        if self._tray_icon is not None:
            return

        menu = pystray.Menu(
            item("显示主窗口", self._tray_show_window),
            item("退出", self._tray_quit),
        )
        self._tray_icon = pystray.Icon(
            "ppt_pc_client",
            _tray_icon_image(),
            "PPT 遥控",
            menu,
        )

        def run_tray():
            self._tray_icon.run()

        self._tray_thread = threading.Thread(target=run_tray, daemon=True)
        self._tray_thread.start()

    def _tray_show_window(self, icon=None, item=None):
        self.root.after(0, self._show_main_window)

    def _restore_main_window(self):
        if self._exiting:
            return
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def _show_main_window(self):
        self._restore_main_window()

    def _tray_quit(self, icon=None, item=None):
        self.root.after(0, self._quit_app)

    def minimize_to_tray(self):
        self._ensure_tray()
        if _HAS_PYSTRAY:
            self.root.withdraw()

    def _on_user_close(self):
        self._quit_app()

    def _on_unmap_maybe_tray(self, event):
        if self._exiting:
            return
        if event.widget != self.root:
            return
        try:
            if self.root.state() == "iconic" and _HAS_PYSTRAY:
                self.root.after(100, self._withdraw_if_still_iconic)
        except tk.TclError:
            pass

    def _withdraw_if_still_iconic(self):
        if self._exiting:
            return
        try:
            if self.root.state() == "iconic":
                self._ensure_tray()
                self.root.withdraw()
        except tk.TclError:
            pass

    def _run_ws_in_thread(self):
        self._async_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._async_loop)

        async def main():
            await websocket_client_loop(self.room_id, self._ws_holder, self._status)

        try:
            self._async_loop.run_until_complete(main())
        finally:
            self._async_loop.close()
            self._async_loop = None
            self.root.after(0, self.refresh_service_button)

    def start_service(self):
        if self._ws_thread is not None and self._ws_thread.is_alive():
            self._status("连接服务已在运行")
            return
        self._ws_holder["ws"] = None
        self._ws_thread = Thread(target=self._run_ws_in_thread, daemon=True)
        self._ws_thread.start()
        self._status("正在连接服务器…")
        self.refresh_service_button()

    def stop_service(self):
        ws = self._ws_holder.get("ws")
        loop = self._async_loop
        if ws is not None and loop is not None and loop.is_running():

            def close_ws():
                fut = asyncio.run_coroutine_threadsafe(ws.close(), loop)
                try:
                    fut.result(timeout=5)
                except Exception:
                    pass

            Thread(target=close_ws, daemon=True).start()
        self._status("正在断开…")

    def _quit_app(self):
        global _ppt_app_instance
        self._exiting = True
        if self._gesture_engine is not None:
            try:
                self._gesture_engine.stop()
            except Exception:
                pass
        self._dispose_all_overlays()
        _ppt_app_instance = None
        self.stop_service()
        time.sleep(0.3)
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
        self.root.quit()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    if tk is None:
        room_id = load_or_create_room_id()
        print(f"\nPC号：{room_id}")
        qr = qrcode.QRCode()
        qr.add_data(room_id)
        print("=== 扫码小程序配对 ===")
        qr.print_ascii(invert=True)
        asyncio.run(websocket_client_loop(room_id, {}, None))
        return

    if not _HAS_PIL:
        print("建议安装：pip install pillow（用于显示二维码）")

    app = PptDesktopApp()
    app.run()


if __name__ == "__main__":
    main()
