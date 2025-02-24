import io
import os
import threading
import time
import wave
from abc import ABC, abstractmethod
from typing import Literal

import simpleaudio

from fastchat.voicevox import VoiceVoxClient


def calculate_duration(content: bytes) -> float:
    wav_io = io.BytesIO(content)
    with wave.open(wav_io, "rb") as wf:
        frame_rate = wf.getframerate()
        duration = wf.getnframes() / float(frame_rate)
    return duration


class BasePlayer(ABC):
    def __init__(self, interval: float = 0.01):
        self.interval = interval

    def play_voice(
        self, content: bytes, interrupt_event: threading.Event | None = None
    ) -> bool:
        """_summary_
        - 音声再生を行う。
        - 終了まで待機する。
        - interrupt_eventがNoneでなく、途中でsetされた場合は再生を中止する。

        Args:
            content (bytes): wav音声のbyte列
            duration (float): 再生時間
            interrupt_event (threading.Event, optional): 再生を中断するためのイベント。 Defaults to None.

        Returns:
            bool: 再生が中断されたかどうか
        """
        self._play_voice(content)
        if interrupt_event:
            while self.is_playing:
                if interrupt_event.is_set():
                    self.stop()
                    break
                time.sleep(self.interval)
        else:
            while self.is_playing:
                time.sleep(self.interval)
        return interrupt_event.is_set() if interrupt_event else True

    @abstractmethod
    def _play_voice(self, content: bytes):
        """_summary_
        音声再生のための抽象メソッド。以下の条件を満たすこと。
        - 音声再生を行う。
        - 再生中はis_playingはTrueになる。
        - 再生終了後、is_playingはFalseになる。
        - waitはせず結果は即座に返す。

        Args:
            content (bytes): wav音声のbyte列

        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """_summary_
        再生を停止するための抽象メソッド。
        - 再生を停止する。
        - is_playingをFalseにする
        """
        pass

    @property
    @abstractmethod
    def is_playing(self) -> bool:
        """_summary_
        再生中かどうかを返すプロパティ。
        """
        return False

    def calculate_duration(self, content: bytes) -> float:
        """_summary_
        再生時間を計算する。
        """
        return 0


class SimpleAudioPlayer(BasePlayer):
    def __init__(self, interval: float = 0.01):
        super().__init__(interval)
        self.play_obj = None

    def _play_voice(self, content: bytes):
        wav_io = io.BytesIO(content)
        with wave.open(wav_io, "rb") as wf:
            audio_data = wf.readframes(wf.getnframes())
            self.play_obj = simpleaudio.play_buffer(
                audio_data, wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
            )

    @property
    def is_playing(self) -> bool:
        return self.play_obj.is_playing() if self.play_obj else False

    def stop(self) -> None:
        if self.play_obj:
            self.play_obj.stop()
            self.play_obj = None


class TTS:
    def __init__(
        self,
        voicevox_host: str = "localhost:50021",
        speaker: Literal["pc"] = "pc",
    ):
        self.voicevox_client = VoiceVoxClient(voicevox_host)
        self.speaker = speaker
        if speaker == "pc":
            self.player = SimpleAudioPlayer()
        self.interval = 0.01

    def play_voice(
        self, text: str, interrupt_event: threading.Event | None = None
    ) -> bool:
        content = self.voicevox_client.get_content(text)
        interrupted = self.player.play_voice(content, interrupt_event)
        self.stop()
        return interrupted

    def stop(self) -> None:
        self.player.stop()
        self.text = ""

    @property
    def is_playing(self) -> bool:
        return self.player.is_playing


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    if os.getenv("VOICEVOX_HOST"):
        tts = TTS(os.environ["VOICEVOX_HOST"])
    else:
        tts = TTS()

    tts.play_voice("こんにちは、世界！")
