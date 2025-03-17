import asyncio
import io
import wave
from typing import Any, Dict, Literal, Optional

from fastvoicechat.tts.players import (
    BasePlayer,
    PyAudioPlayer,
    SimpleAudioPlayer,
    SoundDevicePlayer,
)
from fastvoicechat.tts.synthesizers import (
    BaseSynthesizer,
    PyOpenJTalkSynthesizer,
    VoiceVoxSynthesizer,
)


def calculate_duration(content: bytes) -> float:
    """音声データの再生時間を計算する"""
    wav_io = io.BytesIO(content)
    with wave.open(wav_io, "rb") as wf:
        frame_rate = wf.getframerate()
        duration = wf.getnframes() / float(frame_rate)
    return duration


# AsyncTTSクラスを拡張して、さまざまなプレイヤーを選択できるようにする例
class TTS:
    """非同期テキスト読み上げクラス"""

    def __init__(self, synthesizer: BaseSynthesizer, player: BasePlayer):
        # self.synthesizer = VoiceVoxSynthesizer(voicevox_host)
        self.synthesizer = synthesizer
        self.text = ""

        # プレイヤータイプに応じたプレイヤーを選択
        self.player = player

    async def aplay_voice(
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
            content = await self.synthesizer.asynthesize(text)
            result = await self.player.aplay_voice(content, interrupt_event)
            await self.astop()
            return result
        except Exception as e:
            print(f"Error playing voice: {e}")
            await self.astop()
            return False

    async def astop(self) -> None:
        """再生を停止"""
        await self.player.astop()
        self.text = ""

    @property
    def is_playing(self) -> bool:
        """再生中かどうか"""
        return self.player.is_playing

    async def aclose(self):
        """リソースの解放"""
        await self.synthesizer.aclose()


def create_tts(
    *,
    synthesizer_type: Literal["voicevox", "pyopenjtalsynthesizer"],
    synthesizer_kwargs: Dict[str, Any] = {},
    player_type: Literal["simpleaudio", "pyaudio", "sounddevice"],
    player_kwargs: Dict[str, Any] = {},
) -> TTS:
    if synthesizer_type == "voicevox":
        synthesizer = VoiceVoxSynthesizer(**synthesizer_kwargs)
    elif synthesizer_type == "pyopenjtalsynthesizer":
        synthesizer = PyOpenJTalkSynthesizer(**synthesizer_kwargs)
    else:
        raise ValueError(f"Invalid synthesizer type: {synthesizer_type}")

    if player_type == "simpleaudio":
        player = SimpleAudioPlayer(**player_kwargs)
    elif player_type == "pyaudio":
        player = PyAudioPlayer(**player_kwargs)
    elif player_type == "sounddevice":
        player = SoundDevicePlayer(**player_kwargs)
    else:
        raise ValueError(f"Invalid player type: {player_type}")

    return TTS(synthesizer, player)


if __name__ == "__main__":
    # 使用例
    async def amain():
        # 環境変数からVoiceVoxのホストを取得

        import os

        from dotenv import load_dotenv

        load_dotenv()

        tts = create_tts(
            synthesizer_type="voicevox",
            synthesizer_kwargs={
                "host": os.getenv("VOICEVOX_HOST", "http://localhost:50021")
            },
            player_type="simpleaudio",
        )

        print("音声再生を開始します...")
        await tts.aplay_voice("こんにちは、世界！これは非同期TTSのテストです。")
        print("音声再生が完了しました")

        # リソースの解放
        await tts.aclose()

    asyncio.run(amain())
