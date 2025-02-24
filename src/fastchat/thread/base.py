import threading
import time
import traceback


class CallbackLoop(threading.Thread):
    def __init__(
        self, callback=None, *, interval: float = 0.1, name: str = "", **kwargs
    ):
        super().__init__(daemon=False)
        self.name = name or self.__class__.__name__
        self.callback = callback
        self.stop_event = threading.Event()
        self.interval = interval
        self._state = {}
        self._lock = threading.Lock()
        for k, v in kwargs.items():
            self.set(k, v)

    def get(self, key):
        with self._lock:
            return self._state.get(key)

    def set(self, key, value):
        with self._lock:
            self._state[key] = value

    def run(self):
        try:
            while not self.stop_event.is_set():
                if self.callback:
                    self.callback()
                time.sleep(self.interval)
        except Exception as e:
            print(f"[{self.name}] Error:", e)
            traceback.print_exc()

    def stop(self):
        self.stop_event.set()
