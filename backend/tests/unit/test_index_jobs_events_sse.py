import asyncio
from dataclasses import replace

import pytest
import redis as redis_module

from auth import Principal
from schema import AdminAuthConfig, AuthConfig


pytestmark = pytest.mark.unit


def _fake_config(tmp_path) -> AuthConfig:
    return AuthConfig(
        admin=AdminAuthConfig(username="admin", password="admin123"),
        registry_file=str(tmp_path / "apps.json"),
    )


def _fake_application(auth_config):
    import main

    config = replace(main.application.config, auth=auth_config)

    class Application:
        def __init__(self):
            self.config = config
            self.ready = True

        def start(self):
            pass

        def stop(self):
            pass

    return Application()


class _FakePubSub:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.closed = False

    def subscribe(self, channel):
        pass

    def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
        if self.messages:
            return self.messages.pop(0)
        return None

    def close(self):
        self.closed = True


class _FakeRedis:
    @classmethod
    def from_url(cls, url):
        return cls()

    def pubsub(self):
        return _FakePubSub()

    def close(self):
        pass


class _FakeRedisWithBytesMessage(_FakeRedis):
    """pubsub 返回 bytes 消息体，复现 redis-py decode_responses=False 的真实场景。"""

    def pubsub(self):
        return _FakePubSub(
            messages=[{"type": "message", "data": b'{"app_id": "imsdom", "status": "started"}'}]
        )


class _DisconnectAfter:
    """前 n 次 is_disconnected() 返回 False（进入循环取帧），之后返回 True（退出循环）。"""

    def __init__(self, n):
        self._remaining = n

    async def is_disconnected(self):
        if self._remaining > 0:
            self._remaining -= 1
            return False
        return True


def test_index_jobs_stream_decodes_bytes_message_to_plain_json_frame(monkeypatch, tmp_path):
    """pubsub 消息体是 bytes（redis-py 默认 decode_responses=False）时，
    SSE 帧必须是纯 JSON 字符串，不能带 b' 前缀，否则前端 JSON.parse 会抛 SyntaxError。"""
    import main

    monkeypatch.setattr(main, "application", _fake_application(_fake_config(tmp_path)))
    monkeypatch.setattr(main, "STARTUP_IN_BACKGROUND", False)
    # stream() 内 `from redis import Redis` 运行时取模块属性，fake 掉避免真实连接
    monkeypatch.setattr(redis_module, "Redis", _FakeRedisWithBytesMessage)

    async def _collect_frames():
        response = await main.index_jobs_stream(
            _DisconnectAfter(n=1), app_id="imsdom", principal=Principal(type="admin", app_id="")
        )
        frames = []
        async for frame in response.body_iterator:
            frames.append(frame)
        return frames

    frames = asyncio.run(_collect_frames())

    assert frames == ['data: {"app_id": "imsdom", "status": "started"}\n\n']
