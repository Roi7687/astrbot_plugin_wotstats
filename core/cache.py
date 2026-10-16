# -*- coding: utf-8 -*-
"""极简进程内 TTL 缓存（**不落盘**，进程重启即失效）。

用途只有一个：缓解偶游盒子站点对单 IP 的严格请求配额（403 限流）。
- `CAMP_CACHE_TTL = 0`（默认）→ 查询数据完全不缓存，严格遵守"运行时零缓存"约定。
- `WGID_CACHE_TTL > 0` → 仅缓存"昵称 → wgid"这一 ID 映射（不是战绩数据），
  让 `/wot 营地 <昵称>` 在盒子被限流时仍可用。

线程/协程安全：AstrBot 单事件循环内使用，dict 操作本身原子；这里不额外加锁。
"""
import time

__all__ = ["TTLCache"]


class TTLCache:
    """带过期时间的字典。ttl<=0 时退化为"永远不命中"。"""

    def __init__(self, ttl: float = 0.0, maxsize: int = 512):
        self.ttl = float(ttl)
        self.maxsize = int(maxsize)
        self._data: dict = {}

    def get(self, key):
        if self.ttl <= 0:
            return None
        item = self._data.get(key)
        if not item:
            return None
        value, expire_at = item
        if expire_at < time.time():
            self._data.pop(key, None)
            return None
        return value

    def set(self, key, value) -> None:
        if self.ttl <= 0:
            return
        if len(self._data) >= self.maxsize:
            # 简单淘汰：清掉已过期的，仍满则清空（聊天场景容量极小，不做 LRU）
            now = time.time()
            expired = [k for k, (_, exp) in self._data.items() if exp < now]
            for k in expired:
                self._data.pop(k, None)
            if len(self._data) >= self.maxsize:
                self._data.clear()
        self._data[key] = (value, time.time() + self.ttl)

    def clear(self) -> None:
        self._data.clear()
