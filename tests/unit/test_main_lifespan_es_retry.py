from types import SimpleNamespace

import pytest

import src.main as main_module


class FakeScheduler:
    instances = []

    def __init__(self):
        self.started = False
        self.stopped = False
        self.__class__.instances.append(self)

    def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True


@pytest.mark.parametrize("mq_vendor", ["rabbitmq"])
async def test_lifespan_should_start_and_stop_es_retry_scheduler(monkeypatch, mq_vendor):
    FakeScheduler.instances = []
    monkeypatch.setattr(main_module.redis_client, "initialize", lambda: _async_noop())
    monkeypatch.setattr(main_module.redis_client, "close", lambda: _async_noop())
    monkeypatch.setattr(main_module, "init_database", _async_noop)
    monkeypatch.setattr(main_module, "close_database", _async_noop)
    monkeypatch.setattr(main_module, "start_parse_consumer", _async_noop)
    monkeypatch.setattr(main_module, "EsIndexRetryScheduler", FakeScheduler)
    monkeypatch.setattr(main_module, "MQFactory", lambda: SimpleNamespace(close_all=_async_noop))
    monkeypatch.setattr(main_module.settings, "MQ_VENDOR", mq_vendor)

    async with main_module.lifespan(main_module.app):
        assert FakeScheduler.instances[0].started is True

    assert FakeScheduler.instances[0].stopped is True


async def _async_noop(*args, **kwargs):
    return None
