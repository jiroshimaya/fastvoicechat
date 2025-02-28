import asyncio
import logging
import traceback


class CallbackLoop:
    """AsyncCallbackLoopクラス - 非同期��ー����ンのCallbackLoop"""

    def __init__(
        self, callback=None, *, interval: float = 0.1, name: str = "", **kwargs
    ):
        self.name = name or self.__class__.__name__
        self.callback = callback
        self.stop_event = asyncio.Event()
        self.interval = interval
        self._state = {}
        self._lock = asyncio.Lock()
        self._task = None

        # 追加の状態をセット
        for k, v in kwargs.items():
            self.set(k, v)

    async def aget(self, key):
        """状態から値を取得"""
        async with self._lock:
            return self._state.get(key)

    async def aset(self, key, value):
        """状態に値をセット"""
        async with self._lock:
            self._state[key] = value

    def set(self, key, value):
        """状態に値をセット（同期版）"""
        # 初期化時はロックが必要ないので直接セット
        self._state[key] = value

    async def arun(self):
        """メインループ"""
        try:
            while not self.stop_event.is_set():
                if self.callback:
                    # コールバックが非同期関数か確認して適切に呼び出す
                    if asyncio.iscoroutinefunction(self.callback):
                        await self.callback()
                    else:
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(None, self.callback)
                await asyncio.sleep(self.interval)
        except Exception as e:
            logging.error(f"[{self.name}] Error: {e}")
            logging.error(traceback.format_exc())

    async def astart(self):
        """タスクを開始"""
        if self._task is None or self._task.done():
            self.stop_event.clear()
            self._task = asyncio.create_task(self.arun())

    async def astop(self):
        """タスクを停止"""
        self.stop_event.set()
        if self._task and not self._task.done():
            await self._task
