import logging
import time
from datetime import datetime, timedelta
from typing import Callable

Entry = tuple[datetime, Callable]


class Waiter:
    def __init__(self):
        self._tasks = []  # type: list[tuple[datetime, Callable]]
        self._cur = -1

        self._logger = logging.getLogger('waiter')

    def _reschedule(self, e: Entry, now: datetime) -> Entry:
        dt = e[0].replace(year=now.year, month=now.month, day=now.day)
        if e[0] < now:
            dt = e[0] + timedelta(days=1)
        return dt, e[1]

    def _init(self):
        now = datetime.now()

        self._tasks = [self._reschedule(t, now) for t in self._tasks]
        self._tasks.sort(key=lambda x: x[0])

        self._cur = 0

    def add(self, run: Callable, dt: datetime = None, **kwargs) -> Callable:
        if dt is None:
            dt = datetime.now()

        dt = dt.replace(**kwargs)

        if self._cur != -1:
            raise Exception('Cannot add tasks after initialization')
        self._tasks.append((dt, run))
        return run

    def remove(self, run: Callable) -> None:
        index = next((i for i, v in enumerate(self._tasks) if v[1] == run), -1)
        if index == -1:
            raise Exception('Cannot find task')
        self._tasks.pop(index)
        if self._cur > index:
            self._cur -= 1

    def run_pending(self):
        now = datetime.now()
        while self._tasks[self._cur][0] < now:
            while self._tasks[self._cur][0] < now:
                self._logger.info(f"Executing task!")
                try:
                    self._tasks[self._cur][1]()
                except Exception:
                    self._logger.exception("Error executing task")

                self._tasks[self._cur] = self._reschedule(self._tasks[self._cur], now)

                self._cur += 1
                if self._cur >= len(self._tasks):
                    self._cur = 0

            now = datetime.now()

        # Wait at most 10 minutes so if the local time changes we are notified
        wait_time = min((self._tasks[self._cur][0] - now).total_seconds(), 10 * 60)
        return wait_time

    def run_sync(self):
        self._init()
        while True:
            time.sleep(self.run_pending())


waiter = Waiter()


if __name__ == '__main__':
    w = Waiter()
    w.add(lambda: print("It works 1"), hour=19, minute=39, second=0, microsecond=0)
    w.add(lambda: print("It works 2"), hour=19, minute=40, second=15, microsecond=0)
    w.add(lambda: print("It works 3"), hour=19, minute=40, second=15, microsecond=1)
    w.add(lambda: print("It works 4"), hour=19, minute=39, second=30, microsecond=0)

    w.run_sync()
