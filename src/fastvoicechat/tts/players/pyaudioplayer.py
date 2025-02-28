import asyncio
import io
import wave
from typing import Optional

import numpy as np
import pyaudio

from fastvoicechat.tts.base import BasePlayer


class PyAudioPlayer(BasePlayer):
    """PyAudioを使った非同期オーディオプレイヤー"""

    def __init__(self, interval: float = 0.01):
        super().__init__(interval)
        self._lock = asyncio.Lock()
        self._pyaudio = pyaudio.PyAudio()
        self._stream = None

    async def play_voice(
        self, content: bytes, interrupt_event: Optional[asyncio.Event] = None
    ) -> bool:
        """
        音声を再生し、終了または中断まで待機する。

        Args:
            content: WAV音声のバイト列
            interrupt_event: 再生を中断するためのイベント

        Returns:
            bool: 正常終了したかどうか（Falseなら中断された）
        """
        async with self._lock:
            # 既存の再生があれば停止
            if self.is_playing:
                await self.stop()

            try:
                # WAVデータを解析
                wav_io = io.BytesIO(content)
                with wave.open(wav_io, "rb") as wf:
                    channels = wf.getnchannels()
                    sample_width = wf.getsampwidth()
                    sample_rate = wf.getframerate()
                    frames = wf.readframes(wf.getnframes())

                # ストリームを開く
                self._stream = self._pyaudio.open(
                    format=self._pyaudio.get_format_from_width(sample_width),
                    channels=channels,
                    rate=sample_rate,
                    output=True,
                )

                # 音声データを書き込む
                async def _play():
                    loop = asyncio.get_event_loop()
                    if self._stream is not None:
                        await loop.run_in_executor(None, self._stream.write, frames)
                        self._stream.stop_stream()

                asyncio.create_task(_play())

                # 再生が終了するまで待機
                while self._stream.is_active():
                    print("is_active", self._stream.is_active())
                    if interrupt_event is not None and interrupt_event.is_set():
                        await self.stop()
                        return False
                    await asyncio.sleep(self.interval)

                return True

            except Exception as e:
                print(f"Error in play_voice: {e}")
                await self.stop()
                return False

    async def stop(self) -> None:
        """再生を停止する"""
        async with self._lock:
            if self._stream is not None:
                self._stream.stop_stream()
                self._stream.close()
                self._stream = None

    @property
    def is_playing(self) -> bool:
        """再生中かどうかを返す"""
        return self._stream is not None and self._stream.is_active()

    def __del__(self):
        """PyAudioインスタンスを終了する"""
        if hasattr(self, "_pyaudio"):
            self._pyaudio.terminate()


if __name__ == "__main__":
    player = PyAudioPlayer()

    def create_test_wav_data(duration_sec=0.5, sample_rate=44100, frequency=440.0):
        """テスト用WAVデータ生成"""
        t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), False)
        samples = np.sin(2 * np.pi * frequency * t) * 32767
        audio_data = samples.astype(np.int16)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_data.tobytes())
        buffer.seek(0)
        return buffer.read()

    test_wav_data = create_test_wav_data()
    asyncio.run(player.play_voice(test_wav_data))
