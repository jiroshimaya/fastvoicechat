import asyncio
import logging
import traceback
from typing import Any, Callable, Coroutine, Dict, Optional

import webrtcvad

from fastvoicechat.stt.vad.base import BaseVAD

# 定数
RATE = 16000
VAD_CHUNK = 160
BYTE_PER_SAMPLE = 2  # 16bit


class WebRTCVAD(BaseVAD):
    """WebRTCVADの非同期ラッパークラス"""

    def __init__(
        self,
        *,
        audio_queue: Optional[asyncio.Queue] = None,
        callback: Optional[Callable[[bool], None | Coroutine[Any, Any, None]]] = None,
        rate: int = RATE,
        chunk: int = VAD_CHUNK,
        max_buffer_size: Optional[int] = None,
        aggressiveness: int = 3,
        padding_duration: float = 0.5,  # 秒
    ):
        self._audio_queue = audio_queue or asyncio.Queue()
        self.callback = callback
        self.rate = rate
        self.chunk = chunk
        self.chunk_bytes = chunk * BYTE_PER_SAMPLE
        self.max_buffer_size = max_buffer_size or chunk * 10
        self.padding_duration = padding_duration

        # VADの設定
        self.vad = webrtcvad.Vad()
        self.vad.set_mode(aggressiveness)

        # パディングフレーム数の計算
        self.padding_frames = int(padding_duration * 1000 / (chunk / rate * 1000))

        # 非同期制御
        self.stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._state: Dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def arun(self):
        """非同期のメインループ"""
        loop = asyncio.get_running_loop()
        buffer = b""

        try:
            while not self.stop_event.is_set():
                try:
                    # 非同期キューからデータを取得
                    base_frame = await asyncio.wait_for(
                        self.audio_queue.get(), timeout=0.1
                    )

                    buffer += base_frame
                    # バッファが大きくなりすぎないよう制限
                    if len(buffer) > self.max_buffer_size:
                        buffer = buffer[-self.max_buffer_size :]

                    if len(buffer) >= self.chunk_bytes:
                        # VAD処理は同期APIなのでrun_in_executorで実行
                        is_speech = await loop.run_in_executor(
                            None,
                            lambda: self.vad.is_speech(
                                buffer[: self.chunk_bytes], self.rate
                            ),
                        )

                        # 状態を更新
                        await self._aupdate_state(is_speech)

                        if self.callback:
                            try:
                                # コールバックが非同期関数か確認
                                if asyncio.iscoroutinefunction(self.callback):
                                    await self.callback(is_speech)
                                else:
                                    await loop.run_in_executor(
                                        None, self.callback, is_speech
                                    )
                            except Exception as cb_err:
                                logging.error(f"VAD callback error: {cb_err}")

                        buffer = buffer[self.chunk_bytes :]
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logging.error(f"Error in VAD processing: {e}")
                    logging.error(traceback.format_exc())
                    await asyncio.sleep(0.1)  # エラー時に少し待機
        except Exception as e:
            logging.error(f"Error in VAD main loop: {e}")
            logging.error(traceback.format_exc())

    async def astart(self):
        """非同期タスクを開始"""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.arun())

    async def astop(self):
        """非同期タスクを停止"""
        self.stop_event.set()
        if self._task is not None and not self._task.done():
            await self._task

    async def process_audio(self, audio_data: bytes) -> bool:
        """音声データを処理し、発話区間かどうかを判定"""
        try:
            # フレームサイズに合わせてデータを処理
            if len(audio_data) != self.chunk_bytes:
                return self.is_speech

            # VAD判定
            is_speech = self.vad.is_speech(audio_data, self.rate)

            # 状態更新
            await self._aupdate_state(is_speech)

            return is_speech

        except Exception as e:
            logging.error(f"Error in VAD process_audio: {e}")
            return self.is_speech

    @property
    def is_speech(self) -> bool:
        return self._state.get("is_speech", False)

    @property
    def silence_count(self) -> int:
        return self._state.get("silence_count", 0)

    @property
    def speech_count(self) -> int:
        return self._state.get("speech_count", 0)

    async def _aupdate_state(self, is_speech):
        """状態を更新"""
        async with self._lock:
            self._state["is_speech"] = is_speech
            if is_speech:
                self._state["silence_count"] = 0
                self._state["speech_count"] = self._state.get("speech_count", 0) + 1
            else:
                self._state["silence_count"] = self._state.get("silence_count", 0) + 1
                if self._state["silence_count"] > self.padding_frames:
                    self._state["speech_count"] = 0

    async def reset(self):
        """状態をリセット"""
        async with self._lock:
            self._state.clear()

    @property
    def audio_queue(self) -> asyncio.Queue:
        return self._audio_queue


if __name__ == "__main__":
    from fastvoicechat.stt.capture import PyAudioCapture

    async def async_vad_callback(is_speech):
        print(is_speech)

    async def async_main_with_monitoring():
        vad = WebRTCVAD(callback=async_vad_callback)
        capture = PyAudioCapture([vad.audio_queue])
        await capture.astart()
        await vad.astart()
        print("capture started")

        try:
            # プログラムを実行し続ける
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            # Ctrl+Cで終了時の処理
            await vad.astop()
            await capture.astop()

    asyncio.run(async_main_with_monitoring())
