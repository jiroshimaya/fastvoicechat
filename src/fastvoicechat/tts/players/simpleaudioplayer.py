import asyncio
import io
import wave
from typing import Optional

import simpleaudio

from fastvoicechat.tts.base import BasePlayer


class SimpleAudioPlayer(BasePlayer):
    """simpleaudioを使った非同期プレイヤー"""

    def __init__(self, interval: float = 0.01):
        super().__init__(interval)
        self.play_obj: Optional[simpleaudio.PlayObject] = None
        self._playing = False
        self._lock = asyncio.Lock()
        self._monitor_task: Optional[asyncio.Task] = None  # モニタリングタスクを保持

    async def _play_voice(self, content: bytes):
        """音声を再生する"""
        loop = asyncio.get_running_loop()

        async with self._lock:
            # 既存の再生があれば停止
            if self.play_obj:
                await self.stop()

            def _play():
                wav_io = io.BytesIO(content)
                with wave.open(wav_io, "rb") as wf:
                    audio_data = wf.readframes(wf.getnframes())
                    return simpleaudio.play_buffer(
                        audio_data,
                        wf.getnchannels(),
                        wf.getsampwidth(),
                        wf.getframerate(),
                    )

            # 同期的なsimpleaudioの処理を別スレッドで実行
            self.play_obj = await loop.run_in_executor(None, _play)
            self._playing = True

        # 再生終了を監視する非同期タスク
        async def monitor_playback():
            try:
                while self.play_obj and self.play_obj.is_playing():
                    await asyncio.sleep(self.interval)

                async with self._lock:
                    self._playing = False
            except Exception as e:
                print(f"Monitor playback error: {e}")
                self._playing = False

        # 既存のモニタリングタスクがあればキャンセル
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        self._monitor_task = asyncio.create_task(monitor_playback())

    @property
    def is_playing(self) -> bool:
        """再生中かどうかを返す"""
        if self.play_obj is None:
            return False
        return self._playing and self.play_obj.is_playing()

    async def stop(self) -> None:
        """再生を停止する"""
        async with self._lock:
            play_obj = self.play_obj
            if play_obj:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, lambda: play_obj.stop())
                self.play_obj = None
                self._playing = False

            # モニタリングタスクをキャンセル
            if self._monitor_task:
                self._monitor_task.cancel()
                try:
                    await self._monitor_task
                except asyncio.CancelledError:
                    pass


if __name__ == "__main__":
    import numpy as np

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
    asyncio.run(player.play_voice(test_wav_data))
