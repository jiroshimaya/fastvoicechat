import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseRecognition(ABC):
    """音声認識の基本クラス"""

    @abstractmethod
    async def astart(self):
        """音声認識を開始"""
        pass

    @abstractmethod
    async def astop(self):
        """音声認識を停止"""
        pass

    @abstractmethod
    async def arun(self):
        """メインの処理ループ"""
        pass

    @abstractmethod
    async def process_audio(self, audio_data: bytes) -> Optional[Dict[str, Any]]:
        """音声データを処理し、認識結果を返す"""
        pass

    @abstractmethod
    async def reset(self):
        """状態をリセット"""
        pass

    @property
    @abstractmethod
    def text(self) -> str:
        """認識されたテキスト"""
        pass

    @property
    @abstractmethod
    def audio_queue(self) -> asyncio.Queue:
        """音声データのキュー"""
        pass

    @abstractmethod
    async def astart_new_session(self):
        """新しい認識セッションを開始"""
        pass

    @abstractmethod
    async def apause(self):
        """現在の認識セッションを一時停止"""
        pass

    @abstractmethod
    async def aresume(self):
        """一時停止した認識セッションを再開"""
        pass
