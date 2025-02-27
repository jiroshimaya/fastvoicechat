import asyncio
import io
import wave
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from fastvoicechat.tts.players.sounddeviceplayer import SoundDevicePlayer

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


# --- テストケース ---


def create_mock_behavior():
    """
    sounddeviceモジュールのモックを作成する関数
    Returns:
        dict: sounddeviceモジュールのモック。
        play, get_stream, stopなどの主要な関数を含みます。
    """
    is_play_called = False
    mock_stream = MagicMock()

    # get_streamの動作設定
    def get_stream_behavior():
        nonlocal is_play_called
        nonlocal mock_stream

        if not is_play_called:
            raise RuntimeError("No active stream")
        return mock_stream

    # playの動作設定
    def play_behavior(*args, **kwargs):
        nonlocal is_play_called
        nonlocal mock_stream

        stream_active = [True, True, False]  # 待機ループの３回目で終了する動作を模倣
        is_play_called = True
        # ストリームのactiveプロパティを設定
        type(mock_stream).active = property(
            lambda self: stream_active.pop(0) if stream_active else False
        )

    # stopの動作設定
    def stop_behavior():
        nonlocal mock_stream

        type(mock_stream).active = False

    return {
        "get_stream": get_stream_behavior,
        "play": play_behavior,
        "stop": stop_behavior,
    }


class TestSoundDevicePlayer:
    @pytest.mark.asyncio
    @patch("sounddevice.play")
    @patch("sounddevice.get_stream")
    async def test_play_voice_normal_completion(
        self, mock_get_stream, mock_play, test_wav_data
    ):
        mock_behavior = create_mock_behavior()
        mock_get_stream.side_effect = mock_behavior["get_stream"]
        mock_play.side_effect = mock_behavior["play"]

        """
        正常に再生完了する場合のテスト。
        """
        player = SoundDevicePlayer()
        result = await player.play_voice(test_wav_data)

        assert result is True  # 正常終了
        mock_play.assert_called_once()
        # 再生が完了するまでget_streamが複数回呼ばれることを確認
        assert mock_get_stream.call_count > 1

    @pytest.mark.asyncio
    @patch("sounddevice.play")
    @patch("sounddevice.get_stream")
    @patch("sounddevice.stop")
    async def test_play_voice_with_interrupt(
        self, mock_stop, mock_get_stream, mock_play, test_wav_data
    ):
        """
        割り込みイベントによって再生が中断される場合のテスト。
        """
        mock_behavior = create_mock_behavior()
        mock_get_stream.side_effect = mock_behavior["get_stream"]
        mock_play.side_effect = mock_behavior["play"]
        mock_stop.side_effect = mock_behavior["stop"]

        interrupt_event = asyncio.Event()

        player = SoundDevicePlayer()
        play_task = asyncio.create_task(
            player.play_voice(test_wav_data, interrupt_event)
        )

        await asyncio.sleep(0.01)
        interrupt_event.set()

        result = await play_task

        assert result is False  # 中断されたのでFalseが返される

    @pytest.mark.asyncio
    @patch("sounddevice.get_stream")
    @patch("sounddevice.stop")
    @patch("sounddevice.play")
    async def test_stop_method(
        self, mock_play, mock_stop, mock_get_stream, test_wav_data
    ):
        """
        stop() メソッドによる再生停止のテスト。
        """
        mock_behavior = create_mock_behavior()
        mock_get_stream.side_effect = mock_behavior["get_stream"]
        mock_play.side_effect = mock_behavior["play"]
        mock_stop.side_effect = mock_behavior["stop"]

        player = SoundDevicePlayer()
        play_task = asyncio.create_task(player.play_voice(test_wav_data))

        await asyncio.sleep(0.01)
        await player.stop()
        result = await play_task

        assert player.is_playing is False
        mock_stop.assert_called_once()
