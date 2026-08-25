from __future__ import annotations

from bootstrap import Application
from index.consumer import InlineIndexConsumer


class Runtime:
    def __init__(self, application: Application | None = None):
        self._application = application or Application()
        self.startup_in_background = True
        self.startup_retry_max_interval_seconds = 30
        self._index_consumer: InlineIndexConsumer | None = None

    @property
    def application(self) -> Application:
        return self._application

    @application.setter
    def application(self, application: Application) -> None:
        self._application = application

    def set_application(self, application: Application) -> None:
        self._application = application

    def start_index_consumer(self) -> None:
        self._index_consumer = InlineIndexConsumer(self._application)
        self._index_consumer.start()

    def stop_index_consumer(self) -> None:
        if self._index_consumer is not None:
            self._index_consumer.stop()
            self._index_consumer = None


runtime = Runtime()
