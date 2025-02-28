import asyncio
import io
import wave
from typing import Optional

from fastvoicechat.tts.players import SoundDevicePlayer
from fastvoicechat.tts.synthesizers import VoiceVoxSynthesizer


async def calculate_duration(content: bytes) -> float:
    """音声データの再生時間を計算する"""
    wav_io = io.BytesIO(content)
    with wave.open(wav_io, "rb") as wf:
        frame_rate = wf.getframerate()
        duration = wf.getnframes() / float(frame_rate)
    return duration


# AsyncTTSクラスを拡張して、さまざまなプレイヤーを選択できるようにする例
class TTS:
    """非同期テキスト読み上げクラス"""

    def __init__(self, voicevox_host: str = "localhost:50021"):
        self.synthesizer = VoiceVoxSynthesizer(voicevox_host)
        self.text = ""

        # プレイヤータイプに応じたプレイヤーを選択
        self.player = SoundDevicePlayer()

    async def play_voice(
        self, text: str, interrupt_event: Optional[asyncio.Event] = None
    ) -> bool:
        """
        テキストを音声に変換して再生

        Args:
            text: 読み上げるテキスト
            interrupt_event: 再生を中断するためのイベント

        Returns:
            bool: 正常終了したかどうか（Falseなら中断された）
        """
        if not text:
            return True

        self.text = text
        try:
            content = await self.synthesizer.synthesize(text)
            result = await self.player.play_voice(content, interrupt_event)
            await self.stop()
            return result
        except Exception as e:
            print(f"Error playing voice: {e}")
            await self.stop()
            return False

    async def stop(self) -> None:
        """再生を停止"""
        await self.player.stop()
        self.text = ""

    @property
    def is_playing(self) -> bool:
        """再生中かどうか"""
        return self.player.is_playing

    async def close(self):
        """リソースの解放"""
        await self.synthesizer.close()


# 使用例
async def main():
    # 環境変数からVoiceVoxのホストを取得
    import os

    from dotenv import load_dotenv

    load_dotenv()

    voicevox_host = os.getenv("VOICEVOX_HOST", "localhost:50021")
    tts = TTS(voicevox_host)

    print("音声再生を開始します...")
    await tts.play_voice("こんにちは、世界！これは非同期TTSのテストです。")
    print("音声再生が完了しました")

    # リソースの解放
    await tts.close()


if __name__ == "__main__":
    asyncio.run(main())
