import threading


class Notifier:
    def __init__(self):
        self.condition = threading.Condition()
        self.version = 0

    def notify(self) -> None:
        with self.condition:
            self.version += 1
            self.condition.notify_all()

    def wait(self, version: int, timeout: float) -> bool:
        with self.condition:
            return self.condition.wait_for(lambda: self.version != version, timeout)
