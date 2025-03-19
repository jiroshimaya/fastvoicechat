import asyncio
import logging
import queue
import threading
import time
import traceback
from typing import Any, Callable, Coroutine, Dict, Optional

from google.cloud import speech

from fastvoicechat.stt.recognition.base import BaseRecognition

# 定数
RATE = 16000
STT_CHUNK = 1600
BYTE_PER_SAMPLE = 2  # 16bit


class GoogleSpeechRecognition(BaseRecognition):
    """
    Google Speech-to-Textの非同期ラッパークラス
    """

    def __init__(
        self,
        *,
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
        self.chunk_bytes = chunk * BYTE_PER_SAMPLE
        self.max_buffer_size = max_buffer_size or chunk * 10
        self.single_utterance = single_utterance

        # 非同期イベント
        self.stop_event = asyncio.Event()
        self.reset_event = asyncio.Event()
        self.pause_event = asyncio.Event()
        self.pause_event.set()  # setされるとwait()が即座に返る

        # 状態管理
        self._state: Dict[str, Any] = {}
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        # 認識が継続しているか監視するためのタイムスタンプ
        self._last_activity = time.time()
        self._recognition_active = False

    def create_streaming_config(self) -> speech.StreamingRecognitionConfig:
        """
        Google STTの設定を作成
        """
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=self.rate,
            language_code="ja-JP",
            # 無音検出パラメータを調整
            speech_contexts=[
                speech.SpeechContext(
                    phrases=["あ", "い", "う", "え", "お"],  # 認識しやすい単語を追加
                )
            ],
            enable_automatic_punctuation=True,  # 自動句読点を有効化
        )
        streaming_config = speech.StreamingRecognitionConfig(
            config=config,
            interim_results=True,
            single_utterance=self.single_utterance,
        )
        return streaming_config

    async def arun(self):
        """
        非同期のメインループ
        """
        while not self.stop_event.is_set():
            try:
                self.reset_event.clear()
                await self.pause_event.wait()

                # ウォッチドッグタスクを開始（認識が止まったら再起動する）
                watchdog_task = asyncio.create_task(self._arecognition_watchdog())

                # 音声認識タスク
                await self._arun_recognition_session()

                # ウォッチドッグをキャンセル
                watchdog_task.cancel()
                try:
                    await watchdog_task
                except asyncio.CancelledError:
                    pass

                # セッションが終了または例外で中断された場合、少し待機してから次のセッションを開始
                await asyncio.sleep(0.5)
            except Exception as e:
                logging.error(f"Error in STT main loop: {e}")
                logging.error(traceback.format_exc())
                # エラーが発生しても続行するために少し待機
                await asyncio.sleep(1)

    async def _arecognition_watchdog(self):
        """認識が停止したら再起動するウォッチドッグ"""
        while not self.stop_event.is_set() and not self.reset_event.is_set():
            await asyncio.sleep(5)  # 5秒ごとにチェック

            current_time = time.time()
            if self._recognition_active and current_time - self._last_activity > 10:
                logging.warning(
                    "音声認識が10秒間活動していません。セッションを再起動します。"
                )
                self.reset_event.set()  # 現在のセッションをリセット
                break

    async def _arun_recognition_session(self):
        """音声認識の1セッションを実行"""
        loop = asyncio.get_running_loop()
        client = speech.SpeechClient()
        streaming_config = self.create_streaming_config()

        # 通常の同期キューを使用してイベントループ問題を回避
        audio_buffer = bytearray()
        audio_chunks = queue.Queue()

        # リクエスト生成のためのスレッド終了フラグとスレッド参照
        thread_stop = threading.Event()
        streaming_thread = None

        # AudioCollectorタスク - メインのイベントループで実行
        async def aaudio_collector():
            nonlocal audio_buffer
            try:
                while (
                    not self.stop_event.is_set()
                    and not self.reset_event.is_set()
                    and not thread_stop.is_set()
                ):
                    try:
                        # 非同期キューからデータを取得
                        data = await asyncio.wait_for(
                            self.audio_queue.get(), timeout=0.1
                        )

                        # アクティビティタイムスタンプを更新
                        self._last_activity = time.time()

                        audio_buffer.extend(data)
                        # バッファが大きくなりすぎないよう制限
                        if len(audio_buffer) > self.max_buffer_size:
                            del audio_buffer[: len(audio_buffer) - self.max_buffer_size]

                        # 十分なデータが溜まったらリクエストキューに追加
                        if len(audio_buffer) >= self.chunk_bytes:
                            # バッファの先頭からchunk_bytes分をコピー
                            chunk_data = bytes(audio_buffer[: self.chunk_bytes])
                            # 処理済みデータをバッファから削除
                            del audio_buffer[: self.chunk_bytes]
                            # 同期キューに追加 (イベントループをまたがない)
                            audio_chunks.put(chunk_data)
                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:
                        logging.error(f"Error in audio collector: {e}")
                        break
            finally:
                # コレクター終了時に同期キューを閉じる信号を送る
                audio_chunks.put(None)

        # 同期リクエストジェネレータ関数 (別スレッドで実行される)
        def request_generator():
            while not thread_stop.is_set():
                try:
                    # 同期的にキューからデータを取得
                    chunk = audio_chunks.get(timeout=1.0)

                    # None は終了信号
                    if chunk is None:
                        break

                    # チャンクからリクエストを生成
                    yield speech.StreamingRecognizeRequest(audio_content=chunk)
                except queue.Empty:
                    # タイムアウトは無視して続行
                    continue
                except Exception as e:
                    logging.error(f"Error in request_generator: {e}")
                    break

        # 別スレッドでストリーミング処理を実行
        def run_streaming():
            try:
                # このスレッド内で例外が発生してもプログラム全体が停止しないようにする
                responses = client.streaming_recognize(
                    config=streaming_config, requests=request_generator()
                )

                # レスポンスをメインスレッドに渡す
                for response in responses:
                    if thread_stop.is_set():
                        break

                    if not response.results:
                        continue

                    # レスポンスをキューに入れて、メインスレッドで処理
                    response_queue.put(response)
            except Exception as e:
                logging.error(f"Streaming thread error: {e}")
                logging.error(traceback.format_exc())
            finally:
                # スレッド終了のシグナルを送る
                response_queue.put(None)

        # ストリーミングレスポンスをやり取りするためのキュー
        response_queue = queue.Queue()

        # オーディオコレクタータスクを開始
        collector_task = asyncio.create_task(aaudio_collector())

        # 認識アクティブフラグをセット
        self._recognition_active = True
        self._last_activity = time.time()

        try:
            # ストリーミングスレッドを開始
            streaming_thread = threading.Thread(target=run_streaming)
            streaming_thread.daemon = True
            streaming_thread.start()

            # レスポンスを処理
            while not self.stop_event.is_set() and not self.reset_event.is_set():
                try:
                    # レスポンスキューから結果を取得
                    response = await loop.run_in_executor(
                        None, lambda: response_queue.get(timeout=2.0)
                    )

                    # None は終了シグナル
                    if response is None:
                        break

                    # アクティビティタイムスタンプを更新
                    self._last_activity = time.time()

                    # レスポンスを処理
                    for result in response.results:
                        if result.alternatives:
                            transcript = result.alternatives[0].transcript  # type: ignore
                            result_type = "final" if result.is_final else "interim"
                            result_dict = {"type": result_type, "text": transcript}

                            await self._aupdate_state(result_dict)

                            # コールバック呼び出し
                            if self.callback:
                                try:
                                    if asyncio.iscoroutinefunction(self.callback):
                                        await self.callback(result_dict)
                                    else:
                                        await loop.run_in_executor(
                                            None, self.callback, result_dict
                                        )
                                except Exception as cb_err:
                                    logging.error(f"Callback error: {cb_err}")

                            if result.is_final and self.single_utterance:
                                thread_stop.set()
                                break

                except queue.Empty:
                    # タイムアウトしたが続行
                    continue
                except Exception as e:
                    logging.error(f"Error processing response: {e}")
                    logging.error(traceback.format_exc())

        except Exception as e:
            logging.error(f"Error in recognition session: {e}")
            logging.error(traceback.format_exc())

        finally:
            # 認識非アクティブに設定
            self._recognition_active = False

            # スレッド停止フラグを設定
            thread_stop.set()

            # ストリーミングスレッドが存在する場合は待機
            if streaming_thread and streaming_thread.is_alive():
                streaming_thread.join(timeout=2.0)

            # タスクのクリーンアップ
            collector_task.cancel()
            try:
                await collector_task
            except asyncio.CancelledError:
                pass

    async def process_audio(self, audio_data: bytes) -> Optional[Dict[str, Any]]:
        """音声データを処理し、認識結果を返す"""
        # このメソッドは使用されません。処理は_arun_recognition_sessionで行われます。
        return None

    async def astart(self):
        """
        非同期タスクを開始
        """
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.arun())

    async def astop(self):
        """
        非同期タスクを停止
        """
        self.stop_event.set()
        self.reset_event.set()
        self.pause_event.set()  # pauseイベントも設定して待機状態を解除
        if self._task is not None and not self._task.done():
            await self._task

    async def astart_new_session(self):
        """
        新しいセッションを開始
        """
        await self.aclear_audio_queue()
        self.reset_event.set()
        self.pause_event.set()
        await self.areset_state()

    async def apause(self):
        """
        音声認識を一時停止
        """
        self.pause_event.clear()
        self.reset_event.set()

    async def aclear_audio_queue(self):
        """
        オーディオキューをクリア
        """
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def aresume(self):
        """
        音声認識を再開
        """
        await self.aclear_audio_queue()
        self.pause_event.set()

    async def _aupdate_state(self, result_dict):
        """
        状態を更新
        """
        async with self._lock:
            previous_text = self._state.get("result", {}).get("text", "")
            text = str(result_dict.get("text", ""))
            delta = text[len(previous_text) :]
            self._state["delta"] = delta
            self._state["result"] = result_dict

    async def reset(self):
        """
        状態をリセット
        """
        await self.aclear_audio_queue()
        self.reset_event.set()
        self.pause_event.set()
        await self.areset_state()

    async def areset_state(self):
        """
        状態をリセット
        """
        async with self._lock:
            self._state.clear()

    @property
    def result(self):
        return self._state.get("result", {})

    @property
    def text(self) -> str:
        """認識されたテキスト"""
        return self._state.get("result", {}).get("text", "")

    @property
    def delta(self):
        return self._state.get("delta", "")

    @property
    def audio_queue(self) -> asyncio.Queue:
        return self._audio_queue


if __name__ == "__main__":
    from fastvoicechat.stt.capture import PyAudioCapture

    async def async_recognition_callback(result):
        """非同期STTコールバック"""
        print(result)

    async def async_main_with_monitoring():
        """非同期メイン関数"""
        recognition = GoogleSpeechRecognition(callback=async_recognition_callback)
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
