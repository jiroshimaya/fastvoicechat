import sys
from unittest.mock import patch

from fastvoicechat.factory import FastVoiceChatConfig, create_fastvoicechat
from fastvoicechat.fvchat import FastVoiceChat
from fastvoicechat.tts.players import (
    PyAudioPlayer,
    SimpleAudioPlayer,
    SoundDevicePlayer,
)
from fastvoicechat.tts.synthesizers import PyOpenJTalkSynthesizer, VoiceVoxSynthesizer


def test_create_fastvoicechat_default():
    """デフォルト設定でFastVoiceChatインスタンスが作成できることをテスト"""
    sys.argv = ["script.py"]
    with patch.dict("os.environ", {}, clear=True):  # 環境変数をクリア
        fvc = create_fastvoicechat()
        assert isinstance(fvc, FastVoiceChat)
        assert isinstance(fvc.tts.synthesizer, VoiceVoxSynthesizer)
        assert isinstance(fvc.tts.player, SimpleAudioPlayer)


def test_create_fastvoicechat_with_config():
    """設定を指定してFastVoiceChatインスタンスが作成できることをテスト"""
    sys.argv = ["script.py"]
    with patch.dict("os.environ", {}, clear=True):  # 環境変数をクリア
        config = FastVoiceChatConfig(
            synthesizer_type="pyopenjtalk",
            player_type="pyaudio",
        )
        fvc = create_fastvoicechat(config)
        assert isinstance(fvc, FastVoiceChat)
        assert isinstance(fvc.tts.synthesizer, PyOpenJTalkSynthesizer)
        assert isinstance(fvc.tts.player, PyAudioPlayer)


def test_create_fastvoicechat_with_kwargs():
    """キーワード引数で設定を上書きできることをテスト"""
    sys.argv = ["script.py"]
    with patch.dict("os.environ", {}, clear=True):  # 環境変数をクリア
        fvc = create_fastvoicechat(
            synthesizer_type="pyopenjtalk",
            player_type="sounddevice",
        )
        assert isinstance(fvc, FastVoiceChat)
        assert isinstance(fvc.tts.synthesizer, PyOpenJTalkSynthesizer)
        assert isinstance(fvc.tts.player, SoundDevicePlayer)


def test_fastvoicechat_config_from_cli():
    """CLI引数から設定を読み込めることをテスト"""
    test_args = [
        "script.py",
        "--synthesizer_type",
        "pyopenjtalk",
        "--player_type",
        "pyaudio",
        "--synthesizer_voicevox_host",
        "http://localhost:50022",
        "--synthesizer_voicevox_speaker_id",
        "1",
        "--allow_interrupt",
        "true",
    ]
    with patch.object(sys, "argv", test_args):
        config = FastVoiceChatConfig()
        assert config.synthesizer_type == "pyopenjtalk"
        assert config.player_type == "pyaudio"
        assert config.synthesizer_voicevox_host == "http://localhost:50022"
        assert config.synthesizer_voicevox_speaker_id == 1
        assert config.allow_interrupt is True


def test_fastvoicechat_config_from_cli_with_env():
    """環境変数とCLI引数の組み合わせで設定を読み込めることをテスト"""
    test_args = [
        "script.py",
        "--synthesizer_type",
        "pyopenjtalk",
        "--player_type",
        "pyaudio",
    ]
    with (
        patch.object(sys, "argv", test_args),
        patch.dict(
            "os.environ",
            {
                "FVC_PLAYER_TYPE": "sounddevice",  # CLIで上書きされる
                "FVC_SYNTHESIZER_TYPE": "voicevox",  # CLIで上書きされる
                "FVC_ALLOW_INTERRUPT": "true",  # 環境変数のみ
            },
        ),
    ):
        config = FastVoiceChatConfig()
        # CLI引数が環境変数より優先される
        assert config.synthesizer_type == "pyopenjtalk"
        assert config.player_type == "pyaudio"
        # 環境変数のみの設定は反映される
        assert config.allow_interrupt is True
