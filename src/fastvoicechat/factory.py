from typing import Any, Dict, Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from fastvoicechat.fvchat import FastVoiceChat
from fastvoicechat.tts import TTS
from fastvoicechat.tts.players import (
    PyAudioPlayer,
    SimpleAudioPlayer,
    SoundDevicePlayer,
)
from fastvoicechat.tts.synthesizers import PyOpenJTalkSynthesizer, VoiceVoxSynthesizer


class FastVoiceChatConfig(BaseSettings):
    """FastVoiceChatの設定

    環境変数:
        FVC_SYNTHESIZER_TYPE: 音声合成エンジンの種類
        FVC_PLAYER_TYPE: 音声再生エンジンの種類
        FVC_SYNTHESIZER_VOICEVOX_HOST: VoiceVoxサーバーのホスト
        FVC_SYNTHESIZER_VOICEVOX_SPEAKER_ID: VoiceVoxの話者ID
        FVC_RECOGNITION_TYPE: 音声認識エンジンの種類
        FVC_VAD_TYPE: 音声区間検出エンジンの種類
        FVC_RECOGNITION_MODEL_PATH: Voskモデルのパス
        FVC_ALLOW_INTERRUPT: 割り込みを許可するかどうか

    CLI引数:
        --synthesizer_type: 音声合成エンジンの種類
        --player_type: 音声再生エンジンの種類
        --synthesizer_voicevox_host: VoiceVoxサーバーのホスト
        --synthesizer_voicevox_speaker_id: VoiceVoxの話者ID
        --recognition_type: 音声認識エンジンの種類
        --vad_type: 音声区間検出エンジンの種類
        --recognition_model_path: Voskモデルのパス
        --allow_interrupt: 割り込みを許可するかどうか
    """

    # TTS関連
    synthesizer_type: Literal["voicevox", "pyopenjtalk"] = Field(
        default="voicevox",
        description="音声合成エンジンの種類",
    )
    player_type: Literal["simpleaudio", "pyaudio", "sounddevice"] = Field(
        default="simpleaudio",
        description="音声再生エンジンの種類",
    )
    synthesizer_voicevox_host: str = Field(
        default="http://localhost:50021",
        description="VoiceVoxサーバーのホスト（synthesizer_type='voicevox'の場合のみ使用）",
    )
    synthesizer_voicevox_speaker_id: int = Field(
        default=0,
        description="VoiceVoxの話者ID（synthesizer_type='voicevox'の場合のみ使用）",
    )

    # STT関連
    recognition_type: Literal["googlespeech", "vosk"] = Field(
        default="googlespeech",
        description="音声認識エンジンの種類",
    )
    vad_type: Literal["webrtcvad", "silero"] = Field(
        default="webrtcvad",
        description="音声区間検出エンジンの種類",
    )
    recognition_model_path: Optional[str] = Field(
        default=None,
        description="Voskモデルのパス（recognition_type='vosk'の場合のみ使用）",
    )

    # その他の設定
    allow_interrupt: bool = Field(
        default=False,
        description="割り込みを許可するかどうか",
    )

    # 追加の設定
    extra_kwargs: Dict[str, Any] = Field(
        default_factory=dict,
        description="FastVoiceChatクラスに直接渡される追加の設定",
    )

    model_config = SettingsConfigDict(
        env_prefix="FVC_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        # CLI引数のサポートを追加
        cli_parse_args=True,
        # 未定義のフィールドを許可
        extra="allow",
    )


def create_fastvoicechat(
    config: Optional[FastVoiceChatConfig] = None, **kwargs
) -> FastVoiceChat:
    """FastVoiceChatインスタンスを作成

    Args:
        config: FastVoiceChatの設定。Noneの場合はデフォルト値が使用されます。
        **kwargs: 設定を上書きするための追加の引数

    Returns:
        FastVoiceChat: 作成されたFastVoiceChatインスタンス

    Raises:
        ValueError: 無効な設定が指定された場合
    """
    # 設定の読み込み
    if config is None:
        config = FastVoiceChatConfig(**kwargs)
    elif kwargs:
        # 既存の設定をkwargsで上書き
        config = FastVoiceChatConfig(**{**config.model_dump(), **kwargs})

    # シンセサイザーの作成
    if config.synthesizer_type == "voicevox":
        synthesizer = VoiceVoxSynthesizer(
            host=config.synthesizer_voicevox_host,
            speaker_id=config.synthesizer_voicevox_speaker_id,
        )
    elif config.synthesizer_type == "pyopenjtalk":
        synthesizer = PyOpenJTalkSynthesizer()
    else:
        raise ValueError(f"Invalid synthesizer type: {config.synthesizer_type}")

    # プレイヤーの作成
    if config.player_type == "simpleaudio":
        player = SimpleAudioPlayer()
    elif config.player_type == "pyaudio":
        player = PyAudioPlayer()
    elif config.player_type == "sounddevice":
        player = SoundDevicePlayer()
    else:
        raise ValueError(f"Invalid player type: {config.player_type}")

    # TTSインスタンスを作成
    tts = TTS(synthesizer=synthesizer, player=player)

    # STTの設定を作成
    recognition_kwargs = {}
    if config.recognition_type == "vosk" and config.recognition_model_path:
        recognition_kwargs["model_path"] = config.recognition_model_path

    stt_kwargs = {
        "recognition_type": config.recognition_type,
        "vad_type": config.vad_type,
        "recognition_kwargs": recognition_kwargs,
    }

    # FastVoiceChatインスタンスを作成
    return FastVoiceChat(
        tts=tts,
        stt_kwargs=stt_kwargs,
        allow_interrupt=config.allow_interrupt,
        **config.extra_kwargs,
    )


if __name__ == "__main__":
    import asyncio
    import logging

    from dotenv import load_dotenv

    load_dotenv(override=True)

    logging.basicConfig(level=logging.INFO)

    async def main():
        fastvoicechat = create_fastvoicechat()

        await fastvoicechat.astart()

        print("Press Ctrl+C to stop.")
        try:
            while True:
                await fastvoicechat.autter_after_listening()
        except asyncio.CancelledError:
            print("Task cancelled. Stopping...")
        finally:
            await fastvoicechat.astop()

        print("Main thread exiting.")
        return 0

    asyncio.run(main())
