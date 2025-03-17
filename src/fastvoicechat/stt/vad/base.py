import asyncio
from abc import ABC, abstractmethod


class BaseVAD(ABC):
    """Voice Activity Detection（発話区間検出）の基本クラス"""

    @abstractmethod
    async def astart(self):
        """VADを開始"""
        pass

    @abstractmethod
    async def astop(self):
        """VADを停止"""
        pass

    @abstractmethod
    async def process_audio(self, audio_data: bytes) -> bool:
        """音声データを処理し、発話区間かどうかを判定"""
        pass

    @abstractmethod
    async def reset(self):
        """状態をリセット"""
        pass

    @property
    @abstractmethod
    def speech_count(self) -> int:
        """発話フレームのカウント"""
        pass

    @property
    @abstractmethod
    def silence_count(self) -> int:
        """無音フレームのカウント"""
        pass

    @property
    @abstractmethod
    def audio_queue(self) -> asyncio.Queue:
        """音声データのキュー"""
        pass
