import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

HookFn = Callable[["Event"], Any]


@dataclass
class Event:
    name: str
    data: dict[str, Any] = field(default_factory=dict)


class EventBus:
    def __init__(self):
        self._hooks: dict[str, list[HookFn]] = {}

    def on(self, event_name: str, hook: HookFn):
        self._hooks.setdefault(event_name, []).append(hook)

    async def fire(self, event: Event):
        for hook in self._hooks.get(event.name, []):
            result = hook(event)
            if inspect.isawaitable(result):
                await result


# 全局事件总线
bus = EventBus()
