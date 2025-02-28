import asyncio
import io
import wave
from typing import Optional

import numpy as np
import simpleaudio

from fastvoicechat.tts.base import BasePlayer


class SimpleAudioPlayer(BasePlayer):
    """simpleaudioを使った非同期プレイヤー"""

    def __init__(self, interval: float = 0.01):
        super().__init__(interval)
        self.play_obj: Optional[simpleaudio.PlayObject] = None
        self._lock = asyncio.Lock()

    async def aplay_voice(
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
            if self.play_obj is not None:
                await self.astop()

            # WAVデータをNumPy配列に変換
            wav_io = io.BytesIO(content)
            with wave.open(wav_io, "rb") as wf:
                channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                sample_rate = wf.getframerate()
                raw_data = wf.readframes(wf.getnframes())

            audio_data = np.frombuffer(raw_data, dtype=np.int16)

            # 再生開始
            self.play_obj = simpleaudio.play_buffer(
                audio_data, channels, sample_width, sample_rate
            )

        # 再生が終了するか中断されるまで待機
        try:
            # 中断イベントがある場合は、それを監視しながら再生終了を待つ
            while self.is_playing:
                if interrupt_event is not None and interrupt_event.is_set():
                    await self.astop()
                    return False
                await asyncio.sleep(self.interval)

            return True
        except Exception as e:
            print(f"Error in play_voice: {e}")
            await self.astop()
            return False

    @property
    def is_playing(self) -> bool:
        """再生中かどうかを返す"""
        return self.play_obj is not None and self.play_obj.is_playing()

    async def astop(self) -> None:
        """再生を停止する"""
        async with self._lock:
            if self.play_obj is not None:
                self.play_obj.stop()
                self.play_obj = None


if __name__ == "__main__":
    player = SimpleAudioPlayer()

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
    asyncio.run(player.aplay_voice(test_wav_data))
