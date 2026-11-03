"""
Connection bookkeeping for ONE process.

The service deliberately runs a single ASGI process on Render's free tier
(0.1 CPU / 512 MB), with Channels' in-memory channel layer — a portfolio
compromise: the Channels docs say "Do Not Use In Production" for that layer
because it cannot cross processes. With one process there is nothing to
cross. Scaling out means swapping in channels_redis; these counters would
then need to live in Redis too.

Caps start conservative (Codex review): raise only after a load test.
"""

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Registry:
    max_total: int
    max_per_user: int
    total: int = 0
    per_user: Counter = field(default_factory=Counter)

    def try_open(self) -> bool:
        """A new socket (not yet authenticated)."""
        if self.total >= self.max_total:
            return False
        self.total += 1
        return True

    def close(self) -> None:
        self.total = max(0, self.total - 1)

    def try_add_user(self, user_id: str) -> bool:
        if self.per_user[user_id] >= self.max_per_user:
            return False
        self.per_user[user_id] += 1
        return True

    def remove_user(self, user_id: str) -> None:
        self.per_user[user_id] -= 1
        if self.per_user[user_id] <= 0:
            del self.per_user[user_id]

    def snapshot(self) -> dict:
        return {"sockets": self.total, "users": len(self.per_user)}


_registry: Registry | None = None


def get_registry() -> Registry:
    global _registry
    if _registry is None:
        from django.conf import settings

        _registry = Registry(
            max_total=settings.CHAT_MAX_CONNECTIONS,
            max_per_user=settings.CHAT_MAX_CONNECTIONS_PER_USER,
        )
    return _registry


def reset_registry() -> None:
    """Tests only."""
    global _registry
    _registry = None


def user_group(user_id: str) -> str:
    """Channels group for one user's sockets (ASCII, < 100 chars)."""
    return f"user.{user_id}"
