import asyncio
from abc import ABC, abstractmethod
from typing import Optional


class BasePlayer(ABC):
    """音声再生の抽象基底クラス"""

    def __init__(self, interval: float = 0.01):
        self.interval = interval

    @abstractmethod
    async def aplay_voice(
        self, content: bytes, interrupt_event: Optional[asyncio.Event] = None
    ) -> bool:
        """
        音声再生を行い、終了または中断まで待機する。


        Args:
            content: WAV音声のバイト列
            interrupt_event: 再生を中断するためのイベント

        Returns:
            bool: 正常終了したかどうか（Falseなら中断された）
        """
        pass

    @abstractmethod
    async def astop(self) -> None:
        """再生停止の実装（サブクラスで実装）"""
        pass

    @property
    @abstractmethod
    def is_playing(self) -> bool:
        """再生中かどうかを返す"""
        return False
