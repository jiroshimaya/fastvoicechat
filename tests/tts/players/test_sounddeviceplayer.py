import asyncio
import io
import wave
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from fastvoicechat.tts.players import SoundDevicePlayer

# --- テスト用ヘルパー関数群 ---


def create_test_wav_data(duration_sec=0.5, sample_rate=44100, frequency=440.0):
    """
    テスト用のWAVデータを生成する関数
    """
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


@pytest.fixture
def test_wav_data():
    """テスト用のWAVデータをフィクスチャとして提供"""
    return create_test_wav_data()


def stream_constructor(*args, **kwargs):
    """
    sd.OutputStream をモックするためのヘルパー関数。

    コンストラクタで渡された finished_callback を属性として保持し、
    start() が呼ばれた際にその callback を実行する（※テストによっては上書きして
    自動終了を防ぐことも可能）side_effect を設定します。
    """
    stream = MagicMock()
    stream.finished_callback = kwargs.get("finished_callback")

    def start_side_effect():
        if stream.finished_callback:
            stream.finished_callback()

    stream.start.side_effect = start_side_effect
    return stream


# --- テストケース ---


class TestSoundDevicePlayer:
    @pytest.mark.asyncio
    @patch("sounddevice.OutputStream", side_effect=stream_constructor)
    async def test_play_voice_normal_completion(
        self, mock_output_stream, test_wav_data
    ):
        """
        正常に再生完了する場合のテスト。
        モックの start() が呼ばれると finished_callback が自動実行され、
        _play_event がセットされることをシミュレート。
        """
        # コンテキストマネージャとしての __enter__ 呼び出し時も stream_constructor を利用
        mock_output_stream.return_value.__enter__.side_effect = (
            lambda: stream_constructor()
        )

        player = SoundDevicePlayer()
        result = await player.play_voice(test_wav_data)

        assert result is True  # 正常終了
        mock_output_stream.assert_called_once()

    @pytest.mark.asyncio
    @patch("sounddevice.OutputStream", side_effect=stream_constructor)
    async def test_play_voice_with_interrupt(self, mock_output_stream, test_wav_data):
        """
        割り込みイベントによって再生が中断される場合のテスト。
        """
        # WAV データの長さを計算
        with wave.open(io.BytesIO(test_wav_data), "rb") as wf:
            sample_rate = wf.getframerate()
            frames = wf.getnframes()
            audio_length_sec = (
                frames / sample_rate
            )  # 再生時間 = 総フレーム数 / サンプリングレート

        # モックの設定
        stream_instance = stream_constructor()
        stream_instance.audio_length_sec = audio_length_sec  # 再生時間を設定
        stream_instance.abort.side_effect = (
            lambda: stream_instance.finished_callback()
        )  # 中断時に終了処理を実行
        stream_instance.start.side_effect = lambda: None  # 自動終了しないようにする
        mock_output_stream.return_value.__enter__.return_value = stream_instance

        player = SoundDevicePlayer()
        interrupt_event = asyncio.Event()

        async def set_interrupt():
            await asyncio.sleep(0.1)
            interrupt_event.set()

        asyncio.create_task(set_interrupt())

        result = await player.play_voice(test_wav_data, interrupt_event=interrupt_event)

        assert result is False  # 割り込みによる中断の場合は False
        stream_instance.abort.assert_called_once()  # abort() が呼ばれたことを確認    @pytest.mark.asyncio

    @patch("sounddevice.OutputStream", side_effect=stream_constructor)
    async def test_stop_method(self, mock_output_stream, test_wav_data):
        """
        stop() メソッドによる再生停止のテスト。
        再生中に stop() を呼び出した際に、モックの abort() と close() が呼ばれることを検証します。
        """
        # コンテキストマネージャ対応
        mock_output_stream.return_value.__enter__.side_effect = (
            lambda: stream_constructor()
        )
        # 自動終了させず、stop() による中断を検証するため stream_instance を用意
        stream_instance = stream_constructor()
        stream_instance.start.side_effect = lambda: None
        mock_output_stream.return_value.__enter__.return_value = stream_instance

        player = SoundDevicePlayer()
        play_task = asyncio.create_task(player.play_voice(test_wav_data))

        await asyncio.sleep(0.1)
        await player.stop()

        await play_task

        stream_instance.abort.assert_called_once()  # stop() で abort() が呼ばれる
        stream_instance.close.assert_called_once()  # stop() で close() が呼ばれる
        assert player.is_playing is False
