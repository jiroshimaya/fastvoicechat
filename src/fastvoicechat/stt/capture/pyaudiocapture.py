import asyncio
import logging
from typing import List

import pyaudio

from fastvoicechat.stt.capture.base import BaseCapture

# 定数
RATE = 16000
BASE_CHUNK = 160
BYTE_PER_SAMPLE = 2  # 16bit


class PyAudioCapture(BaseCapture):
    """
    PyAudioの非同期ラッパークラス
    """

    def __init__(self, queue_list: List[asyncio.Queue], rate: int = RATE):
        self.queue_list = queue_list
        self.rate = rate
        self.audio_interface = pyaudio.PyAudio()

        self.read_frame_count = BASE_CHUNK
        self.audio_stream = self.audio_interface.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.rate,
            input=True,
            frames_per_buffer=self.read_frame_count,
        )

        self.stop_event = asyncio.Event()
        self._task = None

    async def arun(self):
        """
        非同期のメインループ
        """
        loop = asyncio.get_running_loop()

        try:
            while not self.stop_event.is_set():
                # PyAudioは同期APIなのでrun_in_executorで実行
                audio_data = await loop.run_in_executor(
                    None,
                    lambda: self.audio_stream.read(
                        self.read_frame_count, exception_on_overflow=False
                    ),
                )

                # 各キューにデータを送信
                for queue in self.queue_list:
                    await queue.put(audio_data)

                # CPU使用率を下げるために少し待機
                await asyncio.sleep(0.001)

        except Exception as e:
            logging.error(f"Error in AudioCapture: {e}")
        finally:
            # クリーンアップ
            self.audio_stream.stop_stream()
            self.audio_stream.close()
            self.audio_interface.terminate()

    async def astart(self):
        """
        非同期タスクを開始
        """
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.arun())

    async def astop(self):
        """
        非同期タスクを停止
        """
        self.stop_event.set()
        if self._task is not None and not self._task.done():
            await self._task
