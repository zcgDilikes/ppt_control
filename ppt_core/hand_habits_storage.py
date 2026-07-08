import json
import os
import time

STORAGE_VERSION = 1
STORAGE_FILENAME = "habits.json"
MAX_ACTIONS = 100  # RingBuffer 限


def load_habits(user_data_dir: str) -> list[tuple[str, float]]:
    """从 user_data/habits.json 读动作历史。

    返回 list of (action, ts)。文件不存在或解析失败返空 list。
    自动 prune >30 天的记录。
    """
    path = os.path.join(user_data_dir, STORAGE_FILENAME)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("version") != STORAGE_VERSION:
        return []
    raw = data.get("actions", [])
    if not isinstance(raw, list):
        return []
    result = []
    now = time.time()
    for item in raw:
        if not isinstance(item, list) or len(item) != 2:
            continue
        action, ts = item
        if not isinstance(action, str) or not isinstance(ts, (int, float)):
            continue
        if (now - ts) > 30 * 86400:
            continue
        result.append((action, float(ts)))
    return result


def save_habits(user_data_dir: str, actions: list[tuple[str, float]]) -> None:
    """写动作历史到 user_data/habits.json。

    自动 prune 旧记录,限最近 100 条。
    """
    os.makedirs(user_data_dir, exist_ok=True)
    now = time.time()
    # prune 旧 + 限 100 条
    fresh = [(a, t) for a, t in actions if (now - t) <= 30 * 86400]
    fresh = fresh[-MAX_ACTIONS:]
    path = os.path.join(user_data_dir, STORAGE_FILENAME)
    payload = {
        "version": STORAGE_VERSION,
        "actions": [[a, t] for a, t in fresh],
        "last_updated": now,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)