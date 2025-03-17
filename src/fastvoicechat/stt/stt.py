import asyncio
import logging
import signal
import sys
from typing import Any, Dict, Literal

from fastvoicechat.stt.capture import PyAudioCapture
from fastvoicechat.stt.recognition import (
    BaseRecognition,
    GoogleSpeechRecognition,
    VoskRecognition,
)
from fastvoicechat.stt.vad import BaseVAD, WebRTCVAD

# 元コードと互換性のある定数
RATE = 16000
BASE_CHUNK = 160
STT_CHUNK = 1600
VAD_CHUNK = 160
BYTE_PER_SAMPLE = 2  # 16bit


class STT:
    """
    STTとVADを統合する非同期クラス
    """

    def __init__(
        self,
        *,
        recognition: BaseRecognition,
        vad: BaseVAD,
    ):
        # 各コンポーネントを設定
        self.recognition = recognition
        self.vad = vad

        # AudioCaptureが指定されていない場合は新規作成
        self.audio_capture = PyAudioCapture(
            [self.recognition.audio_queue, self.vad.audio_queue]
        )

    async def astart(self):
        """
        全コンポーネントを開始
        """
        await self.audio_capture.astart()
        await self.recognition.astart()
        await self.vad.astart()

    async def astop(self):
        """
        全コンポーネントを停止
        """
        await self.audio_capture.astop()
        await self.recognition.astop()
        await self.vad.astop()

    @property
    def is_speech_ended(self) -> bool:
        """
        音声入力が終了したかどうか
        """
        return self.vad.silence_count > 10 and self.recognition.text != ""

    @property
    def is_speech_started(self) -> bool:
        """
        音声入力が開始されたかどうか
        """
        return self.vad.speech_count > 10

    @property
    def text(self) -> str:
        """
        認識されたテキスト
        """
        return self.recognition.text


def create_stt(
    *,
    recognition_type: Literal["googlespeech", "vosk"],
    vad_type: Literal["webrtcvad", "silero"],
    recognition_kwargs: Dict[str, Any] = {},
    vad_kwargs: Dict[str, Any] = {},
) -> STT:
    if recognition_type == "googlespeech":
        recognition = GoogleSpeechRecognition(**recognition_kwargs)
    elif recognition_type == "vosk":
        recognition = VoskRecognition(**recognition_kwargs)
    else:
        raise ValueError(f"Invalid recognition type: {recognition_type}")

    if vad_type == "webrtcvad":
        vad = WebRTCVAD(**vad_kwargs)
    elif vad_type == "silero":
        # vad = SileroVAD(**vad_kwargs)
        pass
    else:
        raise ValueError(f"Invalid vad type: {vad_type}")

    return STT(recognition=recognition, vad=vad)


if __name__ == "__main__":
    from fastvoicechat.stt.recognition import VoskRecognition
    from fastvoicechat.stt.vad import WebRTCVAD

    async def async_recognition_callback(result):
        """非同期STTコールバック"""
        logging.info("[Async Recognition Callback]: %s", result)

    async def async_vad_callback(is_speech):
        """非同期VADコールバック"""
        logging.info("[Async VAD Callback]: %s", is_speech)

    async def async_main_with_monitoring():
        """状態モニタリング付きの非同期メイン関数"""
        # ロギング設定
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )

        # 終了シグナル用イベント
        stop_event = asyncio.Event()

        # シグナルハンドラ設定
        def signal_handler():
            logging.info("終了シグナルを受信しました")
            stop_event.set()

        # Ctrl+C (SIGINT) のハンドラを設定
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)

        logging.info("非同期FastSTTインスタンスを作成中...")

        # FastSTTインスタンスを作成
        faststt = create_stt(
            recognition_type="vosk",
            vad_type="webrtcvad",
            recognition_kwargs={
                "model_path": "model",
                "callback": async_recognition_callback,
            },
            vad_kwargs={"callback": async_vad_callback},
        )
        # 開始
        await faststt.astart()
        logging.info("音声認識を開始しました。Ctrl+Cで停止します。")

        # モニタリングタスク
        async def amonitor_state():
            while not stop_event.is_set():
                logging.info(f"状態: text='{faststt.recognition.text}'")
                await asyncio.sleep(1)

        # モニタリングタスクを開始
        monitor_task = asyncio.create_task(amonitor_state())

        # 終了イベントが設定されるまで待機
        await stop_event.wait()

        # タスクをキャンセル
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

        # 停止処理
        logging.info("停止処理を実行中...")
        await faststt.astop()

        logging.info("正常に終了しました")
        return 0

    # モニタリング付きの音声認識を実行
    exit_code = asyncio.run(async_main_with_monitoring())
    sys.exit(exit_code)
