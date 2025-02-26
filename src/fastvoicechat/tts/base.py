import asyncio
from abc import ABC, abstractmethod
from typing import Optional


class BasePlayer(ABC):
    """音声再生の抽象基底クラス"""

    def __init__(self, interval: float = 0.01):
        self.interval = interval

    async def play_voice(
        self, content: bytes, interrupt_event: Optional[asyncio.Event] = None
    ) -> bool:
        """
        音声再生を行い、終了または中断まで待機する

        Args:
            content: WAV音声のバイト列
            interrupt_event: 再生を中断するためのイベント

        Returns:
            bool: 正常終了したかどうか（Falseなら中断された）
        """
        await self._play_voice(content)

        if interrupt_event:
            while self.is_playing:
                if interrupt_event.is_set():
                    await self.stop()
                    return False
                await asyncio.sleep(self.interval)
        else:
            while self.is_playing:
                await asyncio.sleep(self.interval)

        return True

    @abstractmethod
    async def _play_voice(self, content: bytes):
        """音声再生の実装（サブクラスで実装）"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """再生停止の実装（サブクラスで実装）"""
        pass

    @property
    @abstractmethod
    def is_playing(self) -> bool:
        """再生中かどうかを返す"""
        return False


class BaseSynthesizer(ABC):
    """音声合成の抽象基底クラス"""

    @abstractmethod
    async def synthesize(self, text: str, speaker_id: int = 0) -> bytes:
        """
        テキストから音声を合成する

        Args:
            text: 読み上げるテキスト
            speaker_id: 話者ID

        Returns:
            bytes: WAV形式の音声データ
        """
        pass

    @abstractmethod
    async def get_available_speakers(self) -> list:
        """
        利用可能な話者リストを取得する

        Returns:
            list: 話者情報のリスト
        """
        pass

    @abstractmethod
    async def close(self):
        """リソースを解放する"""
        pass
