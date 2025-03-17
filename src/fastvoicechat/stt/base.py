from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseAudioCapture(ABC):
    """音声キャプチャの基本クラス"""

    @abstractmethod
    async def astart(self):
        """音声キャプチャを開始"""
        pass

    @abstractmethod
    async def astop(self):
        """音声キャプチャを停止"""
        pass

    @abstractmethod
    async def arun(self):
        """メインの処理ループ"""
        pass


class BaseVAD(ABC):
    """Voice Activity Detection（発話区間検出）の基本クラス"""

    @abstractmethod
    async def process_audio(self, audio_data: bytes) -> bool:
        """音声データを処理し、発話区間かどうかを判定"""
        pass

    @abstractmethod
    async def reset(self):
        """状態をリセット"""
        pass


class BaseSTT(ABC):
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
