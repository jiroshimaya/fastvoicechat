import asyncio
import json
import logging
from typing import Any, Callable, Coroutine, Dict, Optional

from vosk import KaldiRecognizer, Model, SetLogLevel

from fastvoicechat.stt.recognition.base import BaseRecognition

# 定数
RATE = 16000
BASE_CHUNK = 160
STT_CHUNK = 1600
VAD_CHUNK = 160
BYTE_PER_SAMPLE = 2  # 16bit


class VoskRecognition(BaseRecognition):
    """
    Voskを使用したストリーミング音声認識クラス
    """

    def __init__(
        self,
        *,
        model_path: str = "model",
        audio_queue: Optional[asyncio.Queue] = None,
        callback: Optional[
            Callable[[Dict[str, Any]], None | Coroutine[Any, Any, None]]
        ] = None,
        chunk: int = STT_CHUNK,
        rate: int = RATE,
        single_utterance: bool = False,
        max_buffer_size: Optional[int] = None,
    ):
        self._audio_queue = audio_queue or asyncio.Queue()
        self.callback = callback
        self.rate = rate
        self.chunk = chunk
        self.chunk_bytes = chunk * 2  # 16bit = 2 bytes per sample
        self.max_buffer_size = max_buffer_size or chunk * 10
        self.single_utterance = single_utterance

        # Voskの設定
        SetLogLevel(-1)  # ログレベルを最小に
        self.model = Model(model_path)
        self.recognizer = KaldiRecognizer(self.model, self.rate)
        self.recognizer.SetWords(True)  # 単語ごとのタイミング情報を有効化

        # 非同期イベント
        self.stop_event = asyncio.Event()
        self.reset_event = asyncio.Event()
        self.pause_event = asyncio.Event()
        self.pause_event.set()

        # 状態管理
        self._state: Dict[str, Any] = {}
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def arun(self):
        """
        非同期のメインループ
        """
        while not self.stop_event.is_set():
            try:
                self.reset_event.clear()
                await self.pause_event.wait()

                # 音声認識セッション
                await self._arun_recognition_session()

                # セッションが終了または例外で中断された場合、少し待機してから次のセッションを開始
                await asyncio.sleep(0.5)
            except Exception as e:
                logging.error(f"Error in STT main loop: {e}")
                await asyncio.sleep(1)

    async def _arun_recognition_session(self):
        """音声認識の1セッションを実行"""

        try:
            while not self.stop_event.is_set() and not self.reset_event.is_set():
                try:
                    # 非同期キューからデータを取得
                    data = await asyncio.wait_for(self.audio_queue.get(), timeout=0.1)
                    previous_result = self.result
                    result = await self.process_audio(data)
                    if result and result != previous_result:
                        await self._acall_callback(result)

                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logging.error(f"Error in recognition session: {e}")
                    break

        except Exception as e:
            logging.error(f"Error in recognition session: {e}")

    async def process_audio(self, audio_data: bytes) -> Optional[Dict[str, Any]]:
        """音声データを処理し、認識結果を返す"""
        loop = asyncio.get_running_loop()
        result_dict = None

        # Vosk認識処理は同期的なので、別スレッドで実行
        is_accepted = await loop.run_in_executor(
            None, self.recognizer.AcceptWaveform, audio_data
        )

        if is_accepted:
            # 最終結果を取得
            result = json.loads(self.recognizer.Result())
            if result.get("text"):
                result_dict = {"type": "final", "text": result["text"]}
                await self._aupdate_state(result_dict)

        else:
            # 中間結果を取得
            partial = json.loads(self.recognizer.PartialResult())
            if partial.get("partial"):
                result_dict = {
                    "type": "interim",
                    "text": partial["partial"],
                }
                await self._aupdate_state(result_dict)

        return result_dict

    async def _acall_callback(self, result_dict: Dict[str, Any]):
        """コールバック関数を呼び出す"""
        if self.callback:
            try:
                if asyncio.iscoroutinefunction(self.callback):
                    await self.callback(result_dict)
                else:
                    await asyncio.get_running_loop().run_in_executor(
                        None, self.callback, result_dict
                    )
            except Exception as e:
                logging.error(f"Callback error: {e}")

    async def _aupdate_state(self, result_dict: Dict[str, Any]):
        """状態を更新"""
        async with self._lock:
            self._state["result"] = result_dict

    async def astart(self):
        """非同期タスクを開始"""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.arun())

    async def astop(self):
        """非同期タスクを停止"""
        self.stop_event.set()
        self.reset_event.set()
        self.pause_event.set()
        if self._task is not None and not self._task.done():
            await self._task

    async def reset(self):
        """状態をリセット"""
        await self.aclear_audio_queue()
        self.reset_event.set()
        self.pause_event.set()
        await self.areset_state()

    async def aclear_audio_queue(self):
        """オーディオキューをクリア"""
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def areset_state(self):
        """状態をリセット"""
        async with self._lock:
            self._state.clear()

    @property
    def result(self):
        return self._state.get("result", {})

    @property
    def text(self) -> str:
        """認識されたテキスト"""
        return self.result.get("text", "")

    @property
    def audio_queue(self) -> asyncio.Queue:
        return self._audio_queue

    async def astart_new_session(self):
        """新しい認識セッションを開始"""
        await self.aclear_audio_queue()
        self.reset_event.set()
        self.pause_event.set()
        await self.areset_state()

    async def apause(self):
        """現在の認識セッションを一時停止"""
        self.pause_event.set()

    async def aresume(self):
        """一時停止した認識セッションを再開"""
        self.pause_event.clear()


if __name__ == "__main__":
    from fastvoicechat.stt.capture import PyAudioCapture

    async def async_recognition_callback(result):
        """非同期STTコールバック"""
        print(result)

    async def async_main_with_monitoring():
        """非同期メイン関数"""
        recognition = VoskRecognition(
            callback=async_recognition_callback, model_path="model"
        )
        capture = PyAudioCapture([recognition.audio_queue])
        await capture.astart()
        await recognition.astart()
        print("capture started")

        try:
            # プログラムを実行し続ける
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            # Ctrl+Cで終了時の処理
            await recognition.astop()
            await capture.astop()

    asyncio.run(async_main_with_monitoring())
