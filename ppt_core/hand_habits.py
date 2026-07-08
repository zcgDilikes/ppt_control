from collections import Counter
import time

# 不计入推荐的"系统命令"(避免推 OPEN_PPT/SCREENSHOT 干扰)
EXCLUDED_FROM_RECOMMEND = frozenset({"OPEN_PPT", "SCREENSHOT"})

# 习惯数据时间窗(30 天)
_HABIT_WINDOW_DAYS = 30
_HABIT_WINDOW_SECONDS = _HABIT_WINDOW_DAYS * 86400


class HabitAnalyzer:
    """统计最近 30 天内的 action 调用频次,输出 top-N 候选。"""

    def __init__(self, history: list[tuple[str, float]]):
        # 过滤掉过期动作(>30 天)
        now = time.time()
        self._history = [
            (action, ts) for action, ts in history
            if (now - ts) <= _HABIT_WINDOW_SECONDS
        ]

    def top_n_actions(self, n: int = 3) -> list[str]:
        """返回 top-N 高频动作(不含系统命令)。

        多个动作同频次时,按最近时间降序(更新的优先)。
        """
        freq = Counter(a for a, _ in self._history)
        if not freq:
            return []
        # 按频次降序,同频次按时间降序
        latest_ts = {a: max(t for act, t in self._history if act == a)
                     for a in freq}
        sorted_actions = sorted(
            freq.keys(),
            key=lambda a: (-freq[a], -latest_ts[a]),
        )
        return [a for a in sorted_actions
                if a not in EXCLUDED_FROM_RECOMMEND][:n]