from abc import ABC, abstractmethod


class BaseCapture(ABC):
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
