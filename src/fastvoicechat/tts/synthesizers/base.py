from abc import ABC, abstractmethod


class BaseSynthesizer(ABC):
    """音声合成の抽象基底クラス"""

    @abstractmethod
    async def asynthesize(self, text: str, **kwargs) -> bytes:
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
    async def aclose(self):
        """リソースの解放"""
        pass
