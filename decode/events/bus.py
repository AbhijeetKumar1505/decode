"""A minimal async publish/subscribe event bus.

Subscribers may be sync or async. A broken subscriber never breaks emission or
the other subscribers — the runtime must not be destabilized by a UI callback.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, List

from .types import Event

Subscriber = Callable[[Event], Any]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: List[Subscriber] = []

    def subscribe(self, callback: Subscriber) -> Callable[[], None]:
        """Register a subscriber; returns an unsubscribe callable."""
        self._subscribers.append(callback)

        def _unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return _unsubscribe

    async def emit(self, event: Event) -> None:
        for callback in list(self._subscribers):
            try:
                result = callback(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                continue
