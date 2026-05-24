from comicfeed.hooks import EventBus, Event


async def test_register_and_fire_event():
    """注册钩子后触发事件，钩子被执行。"""
    bus = EventBus()
    fired = []

    async def my_hook(event: Event):
        fired.append(event.name)

    bus.on("gallery.created", my_hook)
    await bus.fire(Event("gallery.created", {"gallery_id": "nhentai:123"}))
    assert fired == ["gallery.created"]


async def test_multiple_hooks_for_same_event():
    """同一事件可注册多个钩子。"""
    bus = EventBus()
    results = []

    bus.on("gallery.created", lambda e: results.append("a"))
    bus.on("gallery.created", lambda e: results.append("b"))
    await bus.fire(Event("gallery.created", {}))
    assert results == ["a", "b"]


async def test_hook_not_called_for_other_event():
    """钩子不会被其他事件触发。"""
    bus = EventBus()
    fired = []

    bus.on("gallery.created", lambda e: fired.append(True))
    await bus.fire(Event("source.error", {}))
    assert fired == []


async def test_event_carries_data():
    """事件携带数据可被钩子访问。"""
    bus = EventBus()
    captured = {}

    bus.on("gallery.created", lambda e: captured.update(e.data))
    await bus.fire(Event("gallery.created", {"gallery_id": "nh:456", "files": ["a.cbz"]}))
    assert captured == {"gallery_id": "nh:456", "files": ["a.cbz"]}
