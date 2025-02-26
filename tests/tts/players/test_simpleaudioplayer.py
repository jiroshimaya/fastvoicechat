import asyncio
import io
import wave
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from fastvoicechat.tts.players import SimpleAudioPlayer

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


def create_play_object_mock():
    """
    simpleaudio.PlayObject をモックするためのヘルパー関数。
    """
    play_obj = MagicMock()
    play_obj.is_playing.return_value = True
    return play_obj


# --- テストケース ---


class TestSimpleAudioPlayer:
    @pytest.mark.asyncio
    @patch("simpleaudio.play_buffer")
    async def test_play_voice_normal_completion(self, mock_play_buffer, test_wav_data):
        """
        正常に再生完了する場合のテスト。
        モックの is_playing() が最初は True を返し、その後 False を返すことで
        再生完了をシミュレート。
        """
        play_obj = create_play_object_mock()
        mock_play_buffer.return_value = play_obj

        # 再生完了をシミュレートするため、is_playing の戻り値を変更
        is_playing_values = [True, True, False]
        play_obj.is_playing.side_effect = (
            lambda: is_playing_values.pop(0) if is_playing_values else False
        )

        player = SimpleAudioPlayer(interval=0.01)
        result = await player.play_voice(test_wav_data)

        assert result is True  # 正常終了
        mock_play_buffer.assert_called_once()

    @pytest.mark.asyncio
    @patch("simpleaudio.play_buffer")
    async def test_play_voice_with_interrupt(self, mock_play_buffer, test_wav_data):
        """
        割り込みイベントによって再生が中断される場合のテスト。
        """
        play_obj = create_play_object_mock()
        mock_play_buffer.return_value = play_obj

        player = SimpleAudioPlayer(interval=0.01)
        interrupt_event = asyncio.Event()

        async def set_interrupt():
            await asyncio.sleep(0.1)
            interrupt_event.set()

        asyncio.create_task(set_interrupt())

        result = await player.play_voice(test_wav_data, interrupt_event=interrupt_event)

        assert result is False  # 割り込みによる中断の場合は False
        play_obj.stop.assert_called_once()  # 中断処理が呼ばれている

    @pytest.mark.asyncio
    @patch("simpleaudio.play_buffer")
    async def test_stop_method(self, mock_play_buffer, test_wav_data):
        """
        stop() メソッドによる再生停止のテスト。
        再生中に stop() を呼び出した際に、モックの stop() が呼ばれることを検証します。
        """
        play_obj = create_play_object_mock()
        mock_play_buffer.return_value = play_obj

        player = SimpleAudioPlayer(interval=0.01)
        play_task = asyncio.create_task(player.play_voice(test_wav_data))

        await asyncio.sleep(0.1)
        await player.stop()

        await play_task

        play_obj.stop.assert_called_once()  # stop() で stop() が呼ばれる
        assert player.is_playing is False
