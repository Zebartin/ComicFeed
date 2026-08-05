import pytest
from datetime import datetime

from comicfeed.infrastructure.config import get_setting, set_setting
from comicfeed.infrastructure.database import create_tables, get_session, init_db
from comicfeed.models import DownloadEvent
from comicfeed.repositories.download_event import pending_since
from comicfeed.services import digest as digest_mod
from comicfeed.services.digest import build_digest, send_digest, webhook_payload


@pytest.fixture(autouse=True)
async def _db():
    init_db(":memory:")
    await create_tables()
    yield


async def _add_event(subscription_name="订阅A", status="success", title="Title", n=1):
    async with get_session() as s:
        for i in range(n):
            s.add(DownloadEvent(subscription_name=subscription_name, source_key="nhentai",
                                gallery_id=f"nhentai:{i}", title=f"{title}{i}",
                                page_count=10, status=status))
        await s.commit()


async def _all_events():
    async with get_session() as s:
        return await pending_since(s, datetime(1970, 1, 1))


async def test_build_digest_groups_and_caps():
    """按订阅分组、成功项限量 12、失败组内列出。"""
    await _add_event("订阅A", n=15)
    await _add_event("订阅B", status="failed", title="Fail")
    digest = build_digest(await _all_events())
    assert digest is not None
    subs = {g["name"]: g for g in digest["subscriptions"]}
    assert set(subs) == {"订阅A", "订阅B"}
    assert subs["订阅A"]["count"] == 15
    assert len(subs["订阅A"]["items"]) == 12
    assert subs["订阅B"]["count"] == 0
    assert subs["订阅B"]["failed_count"] == 1
    assert len(subs["订阅B"]["failed"]) == 1
    assert digest["total_count"] == 15
    assert digest["total_failed"] == 1


async def test_build_digest_empty_returns_none():
    assert build_digest([]) is None


async def test_webhook_payload_truncates_to_5():
    """webhook 负载每订阅只列 5 条，count 保留总数。"""
    await _add_event("订阅A", n=8)
    digest = build_digest(await _all_events())
    payload = webhook_payload(digest)
    sub = payload["subscriptions"][0]
    assert sub["count"] == 8
    assert len(sub["items"]) == 5


async def test_send_digest_skips_when_no_events(monkeypatch):
    """无新事件 → 跳过，不触任何通道，last_digest_at 不推进。"""
    calls = []
    monkeypatch.setattr(digest_mod, "send_digest_email", lambda c, d: calls.append("email"))
    monkeypatch.setattr(digest_mod, "send_webhook", lambda *a, **k: calls.append("webhook"))
    assert await send_digest() is False
    assert calls == []
    assert not (await get_setting("last_digest_at"))


async def test_send_digest_sends_and_advances(monkeypatch):
    """有事件 → 发送邮件+webhook，推进 last_digest_at。"""
    await _add_event("订阅A", n=2)
    sent = []

    async def fake_email(cfg, digest):
        sent.append(("email", digest["total_count"]))

    async def fake_webhook(url, event):
        sent.append(("webhook", event["name"]))

    monkeypatch.setattr(digest_mod, "send_digest_email", fake_email)
    monkeypatch.setattr(digest_mod, "send_webhook", fake_webhook)
    await set_setting("smtp_host", "smtp.example.com")
    await set_setting("smtp_to", "a@b.c")
    await set_setting("webhook_url", "https://hook")

    assert await send_digest() is True
    assert ("email", 2) in sent
    assert ("webhook", "digest") in sent
    assert await get_setting("last_digest_at")


async def test_send_digest_all_channels_fail_keeps_timestamp(monkeypatch):
    """全部通道失败 → 不推进 last_digest_at，下次重试。"""
    await _add_event("订阅A", n=1)

    async def fail_email(cfg, digest):
        raise RuntimeError("smtp down")

    async def fail_webhook(url, event):
        raise RuntimeError("hook down")

    monkeypatch.setattr(digest_mod, "send_digest_email", fail_email)
    monkeypatch.setattr(digest_mod, "send_webhook", fail_webhook)
    await set_setting("smtp_host", "smtp.example.com")
    await set_setting("smtp_to", "a@b.c")
    await set_setting("webhook_url", "https://hook")

    assert await send_digest() is False
    assert not (await get_setting("last_digest_at"))


async def test_send_digest_since_boundary(monkeypatch):
    """推进后二次运行无新事件 → 跳过。"""
    await _add_event("订阅A", n=1)
    sent = []

    async def fake_email(cfg, digest):
        sent.append(digest["total_count"])

    async def fake_webhook(url, event):
        pass

    monkeypatch.setattr(digest_mod, "send_digest_email", fake_email)
    monkeypatch.setattr(digest_mod, "send_webhook", fake_webhook)
    await set_setting("smtp_host", "h")
    await set_setting("smtp_to", "t")
    await set_setting("webhook_url", "u")

    assert await send_digest() is True
    assert sent == [1]
    sent.clear()
    assert await send_digest() is False
    assert sent == []


async def test_send_digest_advances_to_watermark(monkeypatch):
    """last_digest_at 推进到已消费事件的最大 created_at，而非发送时刻。"""
    await _add_event("订阅A", n=2)

    async def fake_email(cfg, digest):
        pass

    async def fake_webhook(url, event):
        pass

    monkeypatch.setattr(digest_mod, "send_digest_email", fake_email)
    monkeypatch.setattr(digest_mod, "send_webhook", fake_webhook)
    await set_setting("smtp_host", "h")
    await set_setting("smtp_to", "t")
    await set_setting("webhook_url", "u")

    digest = build_digest(await _all_events())
    await send_digest()
    assert await get_setting("last_digest_at") == digest["until"].isoformat()


async def test_setup_digest_job_empty_does_not_register():
    """空 notification_cron → 不注册 send_digest job。"""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from comicfeed.infrastructure.scheduler import setup_digest_job

    await set_setting("notification_cron", "")
    sched = AsyncIOScheduler()
    await setup_digest_job(sched)
    assert sched.get_job("send_digest") is None


async def test_setup_digest_job_valid_cron_registers():
    """合法 cron 表达式 → 注册 cron job。"""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from comicfeed.infrastructure.scheduler import setup_digest_job

    await set_setting("notification_cron", "0 8 * * *")
    sched = AsyncIOScheduler()
    await setup_digest_job(sched)
    job = sched.get_job("send_digest")
    assert job is not None
    assert isinstance(job.trigger, CronTrigger)


async def test_setup_digest_job_invalid_cron_skips():
    """非法 cron 表达式 → 不注册。"""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from comicfeed.infrastructure.scheduler import setup_digest_job

    await set_setting("notification_cron", "not a cron")
    sched = AsyncIOScheduler()
    await setup_digest_job(sched)
    assert sched.get_job("send_digest") is None


async def test_setup_digest_job_reschedules():
    """修改表达式 → 旧 job 被替换为新 cron。"""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from comicfeed.infrastructure.scheduler import setup_digest_job

    await set_setting("notification_cron", "0 8 * * *")
    sched = AsyncIOScheduler()
    await setup_digest_job(sched)
    assert sched.get_job("send_digest") is not None

    await set_setting("notification_cron", "0 9 * * *")
    await setup_digest_job(sched)
    job = sched.get_job("send_digest")
    assert job is not None
    assert "hour='9'" in str(job.trigger)


async def test_send_digest_email_groups_and_omits(monkeypatch):
    """摘要邮件按订阅分组，超限提示省略，失败项组内列出。"""
    from comicfeed.infrastructure import notifications as infra

    await _add_event("订阅A", n=15)
    await _add_event("订阅B", status="failed", title="Fail")
    digest = build_digest(await _all_events())

    captured = {}

    def fake_smtp(config, msg):
        captured["subject"] = msg["Subject"]
        captured["html"] = msg.get_payload()[0].get_payload(decode=True).decode("utf-8")

    monkeypatch.setattr(infra, "_smtp_send", fake_smtp)
    await infra.send_digest_email(
        {"host": "h", "port": 587, "user": "u", "password": "p", "to": "t"}, digest
    )
    html = captured["html"]
    assert "ComicFeed · 下载摘要" in html
    assert "订阅A · 15 个下载" in html
    assert "等共 15 个画廊" in html
    assert "订阅B" in html
    assert "Fail" in html  # 失败项标题在组内
    assert "统计范围：" in html  # until 有明确含义（窗口终点）
    assert "15 下载" in captured["subject"]
