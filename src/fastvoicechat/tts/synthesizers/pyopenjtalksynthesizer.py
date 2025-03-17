import io

import numpy as np
import pyopenjtalk
from scipy.io import wavfile

from fastvoicechat.tts.synthesizers.base import BaseSynthesizer


class PyOpenJTalkSynthesizer(BaseSynthesizer):
    """pyopenjtalkを非同期で扱うクラス"""

    def __init__(self, **kwargs):
        pass

    async def asynthesize(self, text: str) -> bytes:
        """
        テキストからVoiceVox APIを使って音声を合成

        Args:
            text: 読み上げるテキスト

        Returns:
            bytes: WAV形式の音声データ
        """
        x, sr = pyopenjtalk.tts(text)
        # numpy配列をwavバイトに変換
        wav_buffer = io.BytesIO()
        wavfile.write(wav_buffer, sr, x.astype(np.int16))
        return wav_buffer.getvalue()

    async def aclose(self):
        """定義が必要なので何もしない処理を記述"""
        pass


if __name__ == "__main__":
    import asyncio
    import os

    async def amain():
        content = await PyOpenJTalkSynthesizer().asynthesize("こんにちは")
        with open("test.wav", "wb") as f:
            f.write(content)
        os.system("afplay test.wav")

    asyncio.run(amain())
