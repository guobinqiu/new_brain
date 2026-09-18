import pytest


pytestmark = pytest.mark.unit


def test_selects_cuda_when_torch_reports_cuda(monkeypatch):
    import shared.device as device

    class FakeCuda:
        @staticmethod
        def is_available():
            return True

    class FakeTorch:
        cuda = FakeCuda()

    monkeypatch.setattr(device, "_load_torch", lambda: FakeTorch())

    assert device.auto_device() == "cuda"


def test_falls_back_to_cpu_when_cuda_is_not_available(monkeypatch):
    import shared.device as device

    class FakeCuda:
        @staticmethod
        def is_available():
            return False

    class FakeTorch:
        cuda = FakeCuda()

    monkeypatch.setattr(device, "_load_torch", lambda: FakeTorch())

    assert device.auto_device() == "cpu"


def test_falls_back_to_cpu_when_torch_cannot_be_loaded(monkeypatch):
    import shared.device as device

    def fail():
        raise ImportError("torch unavailable")

    monkeypatch.setattr(device, "_load_torch", fail)

    assert device.auto_device() == "cpu"


def test_release_memory_clears_cuda_cache_when_available(monkeypatch):
    import shared.device as device

    calls = []

    class FakeCuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def empty_cache():
            calls.append("empty_cache")

    class FakeTorch:
        cuda = FakeCuda()

    monkeypatch.setattr(device, "_load_torch", lambda: FakeTorch())

    device.release_memory()

    assert calls == ["empty_cache"]


def test_release_memory_ignores_missing_torch(monkeypatch):
    import shared.device as device

    def fail():
        raise ImportError("torch unavailable")

    monkeypatch.setattr(device, "_load_torch", fail)

    device.release_memory()
