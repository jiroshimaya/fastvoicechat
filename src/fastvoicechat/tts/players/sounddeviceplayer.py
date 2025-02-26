import asyncio
import io
import wave
from typing import Optional

import numpy as np
import sounddevice as sd

from fastvoicechat.tts.base import BasePlayer


class SoundDevicePlayer(BasePlayer):
    """sounddeviceを使った非同期オーディオプレイヤー"""

    def __init__(self, interval: float = 0.01):
        super().__init__(interval)
        self._is_playing = False
        self._current_stream: Optional[sd.OutputStream] = None
        self._play_event = asyncio.Event()
        self._lock = asyncio.Lock()
        # 音声バッファ管理用
        self._audio_buffer: Optional[np.ndarray] = None
        self._audio_buffer_pos = 0

    def _finish_playback(self):
        """再生完了時のクリーンアップ処理"""
        self._is_playing = False
        self._play_event.set()
        self._current_stream = None

    async def _play_voice(self, content: bytes):
        async with self._lock:
            # 既存の再生があれば停止
            if self._is_playing:
                await self.stop()

            # WAVデータをNumPy配列に変換
            wav_io = io.BytesIO(content)
            with wave.open(wav_io, "rb") as wf:
                channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                sample_rate = wf.getframerate()
                frames = wf.getnframes()
                raw_data = wf.readframes(frames)

                if sample_width == 1:  # 8-bit
                    dtype = np.uint8
                elif sample_width == 2:  # 16-bit
                    dtype = np.int16
                elif sample_width == 4:  # 32-bit
                    dtype = np.int32
                else:
                    raise ValueError(f"Unsupported sample width: {sample_width}")

                audio_data = np.frombuffer(raw_data, dtype=dtype)
                # 1チャンネルの場合も2次元配列にする
                if channels > 1:
                    audio_data = audio_data.reshape(-1, channels)
                else:
                    audio_data = audio_data.reshape(-1, 1)

            # 再生開始前にバッファと再生位置を初期化
            self._play_event.clear()
            self._audio_buffer = audio_data
            self._audio_buffer_pos = 0

            # 現在のイベントループを取得（コールバックからの終了通知用）
            loop = asyncio.get_running_loop()

            def callback(outdata, frames, time, status):
                if status:
                    print(f"Status: {status}")
                if self._audio_buffer is None:
                    return
                available_frames = self._audio_buffer.shape[0] - self._audio_buffer_pos
                if available_frames >= frames:
                    outdata[:] = self._audio_buffer[
                        self._audio_buffer_pos : self._audio_buffer_pos + frames
                    ]
                    self._audio_buffer_pos += frames
                else:
                    if available_frames > 0:
                        outdata[:available_frames] = self._audio_buffer[
                            self._audio_buffer_pos :
                        ]
                    outdata[available_frames:] = 0
                    self._audio_buffer_pos += available_frames
                    # 再生終了を通知
                    raise sd.CallbackStop

            def finished_callback():
                loop.call_soon_threadsafe(self._finish_playback)

            # コールバックモードでストリーム作成
            self._current_stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype=audio_data.dtype,
                callback=callback,
                finished_callback=finished_callback,
            )
            self._current_stream.start()
            self._is_playing = True

        # ロックの外で待機
        try:
            await self._play_event.wait()
        except Exception as e:
            print(f"Error in _play_voice: {e}")
            self._is_playing = False
            self._current_stream = None
            self._play_event.set()

    async def stop(self) -> None:
        """再生を停止する"""
        async with self._lock:
            if self._current_stream:
                self._current_stream.abort()
                self._current_stream.close()
                self._current_stream = None
            self._is_playing = False
            self._play_event.set()  # 待機中のタスクを解放

    @property
    def is_playing(self) -> bool:
        """再生中かどうかを返す"""
        return self._is_playing


if __name__ == "__main__":
    player = SoundDevicePlayer()

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
