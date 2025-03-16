import asyncio
import io
import wave
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from fastvoicechat.tts.players import PyAudioPlayer

# WIP
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
    pyaudioモジュールのモックを作成する関数
    Returns:
        dict: pyaudioモジュールのモック。
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
    def write_behavior(*args, **kwargs):
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
        "write": write_behavior,
        "stop": stop_behavior,
    }


class TestPyAudioPlayer:
    @pytest.mark.asyncio
    @patch("pyaudio.PyAudio")
    async def test_aplay_voice_normal_completion(self, mock_pyaudio_cls, test_wav_data):
        """正常に再生完了する場合のテスト"""
        # PyAudioのモックセットアップ
        mock_pyaudio = mock_pyaudio_cls.return_value
        mock_stream = MagicMock()
        mock_pyaudio.open.return_value = mock_stream
        mock_pyaudio.get_format_from_width.return_value = 8  # 適当なフォーマット値

        # is_activeの動作をシミュレート（最初はTrue、その後Falseを返す）
        is_active_values = [True, True, False]
        mock_stream.is_active.side_effect = (
            lambda: is_active_values.pop(0) if is_active_values else False
        )

        # プレイヤーの作成と実行
        player = PyAudioPlayer()
        result = await player.aplay_voice(test_wav_data)

        # 検証
        assert result is True
        mock_pyaudio.open.assert_called_once()
        mock_stream.write.assert_called_once()
        mock_stream.stop_stream.assert_called_once()
        # 正常系ではcloseは呼ばれない
        mock_stream.close.assert_not_called()
        mock_pyaudio.terminate.assert_not_called()  # terminateは__del__で呼ばれる

    @pytest.mark.asyncio
    @patch("pyaudio.PyAudio")
    async def test_aplay_voice_with_interrupt(self, mock_pyaudio_cls, test_wav_data):
        """割り込みイベントによって再生が中断される場合のテスト"""
        # PyAudioのモックセットアップ
        mock_pyaudio = mock_pyaudio_cls.return_value
        mock_stream = MagicMock()
        mock_pyaudio.open.return_value = mock_stream
        mock_pyaudio.get_format_from_width.return_value = 8

        # ストリームを常にアクティブに設定
        mock_stream.is_active.return_value = True

        # プレイヤーの作成
        player = PyAudioPlayer()
        interrupt_event = asyncio.Event()

        # 非同期で再生を開始
        play_task = asyncio.create_task(
            player.aplay_voice(test_wav_data, interrupt_event)
        )

        # 少し待ってから割り込みイベントを発生
        await asyncio.sleep(0.01)
        interrupt_event.set()

        # 結果の検証
        result = await play_task
        assert result is False
        # mock_stream.stop_stream.assert_called_once()
        # mock_stream.close.assert_called_once()
        # mock_pyaudio.terminate.assert_not_called()
