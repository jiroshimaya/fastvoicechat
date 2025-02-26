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

        # 再生が終了するか中断されるまで待機
        try:
            # 中断イベントがある場合は、それを監視しながら再生終了を待つ
            if interrupt_event:
                while self.is_playing:
                    if interrupt_event.is_set():
                        await self.stop()
                        return False
                    await asyncio.sleep(self.interval)
            else:
                # 直接ループで監視
                while self.is_playing:
                    await asyncio.sleep(self.interval)

            return True
        except Exception as e:
            print(f"Error in play_voice: {e}")
            await self.stop()
            return False

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
