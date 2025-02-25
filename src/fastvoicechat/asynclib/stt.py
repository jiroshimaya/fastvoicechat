import asyncio
import logging
import queue
import signal
import sys
import threading
import time
import traceback
from typing import Any, Callable, Coroutine, Dict, List, Optional

import pyaudio
import webrtcvad
from google.cloud import speech

# 元コードと互換性のある定数
RATE = 16000
BASE_CHUNK = 160
STT_CHUNK = 1600
VAD_CHUNK = 160
BYTE_PER_SAMPLE = 2  # 16bit


class AsyncGoogleSpeechRecognition:
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
        self.audio_queue = audio_queue or asyncio.Queue()
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

    async def run(self):
        """
        非同期のメインループ
        """
        while not self.stop_event.is_set():
            try:
                self.reset_event.clear()
                await self.pause_event.wait()

                # ウォッチドッグタスクを開始（認識が止まったら再起動する）
                watchdog_task = asyncio.create_task(self._recognition_watchdog())

                # 音声認識タスク
                await self._run_recognition_session()

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

    async def _recognition_watchdog(self):
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

    async def _run_recognition_session(self):
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
        async def audio_collector():
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
        collector_task = asyncio.create_task(audio_collector())

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
                            transcript = result.alternatives[0].transcript
                            result_type = "final" if result.is_final else "interim"
                            result_dict = {"type": result_type, "text": transcript}

                            await self._update_state(result_dict)

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

    def start(self):
        """
        非同期タスクを開始
        """
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run())

    async def stop(self):
        """
        非同期タスクを停止
        """
        self.stop_event.set()
        self.reset_event.set()
        self.pause_event.set()  # pauseイベントも設定して待機状態を解除
        if self._task is not None and not self._task.done():
            await self._task

    async def start_new_session(self):
        """
        新しいセッションを開始
        """
        await self.clear_audio_queue()
        self.reset_event.set()
        self.pause_event.set()
        await self.reset_state()

    async def pause(self):
        """
        音声認識を一時停止
        """
        self.pause_event.clear()
        self.reset_event.set()

    async def clear_audio_queue(self):
        """
        オーディオキューをクリア
        """
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def resume(self):
        """
        音声認識を再開
        """
        await self.clear_audio_queue()
        self.pause_event.set()

    async def _update_state(self, result_dict):
        """
        状態を更新
        """
        async with self._lock:
            previous_text = self._state.get("result", {}).get("text", "")
            text = result_dict.get("text", "")
            delta = text[len(previous_text) :]
            self._state["delta"] = delta
            self._state["result"] = result_dict

    async def reset_state(self):
        """
        状態をリセット
        """
        async with self._lock:
            self._state.clear()

    @property
    def result(self):
        return self._state.get("result", {})

    @property
    def text(self):
        return self.result.get("text", "")

    @property
    def delta(self):
        return self._state.get("delta", "")


class AsyncWebRTCVAD:
    """
    WebRTCVADの非同期ラッパークラス
    """

    def __init__(
        self,
        *,
        audio_queue: Optional[asyncio.Queue] = None,
        callback: Optional[Callable[[bool], None | Coroutine[Any, Any, None]]] = None,
        rate: int = RATE,
        chunk: int = VAD_CHUNK,
        max_buffer_size: Optional[int] = None,
    ):
        self.audio_queue = audio_queue or asyncio.Queue()
        self.callback = callback
        self.rate = rate
        self.chunk = chunk
        self.chunk_bytes = chunk * BYTE_PER_SAMPLE
        self.max_buffer_size = max_buffer_size or chunk * 10

        # VADの設定
        self.vad = webrtcvad.Vad()
        self.vad.set_mode(3)

        # 非同期制御
        self.stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._state: Dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def run(self):
        """
        非同期のメインループ
        """
        loop = asyncio.get_running_loop()
        buffer = b""

        try:
            while not self.stop_event.is_set():
                try:
                    # 非同期キューからデータを取得
                    base_frame = await asyncio.wait_for(
                        self.audio_queue.get(), timeout=0.1
                    )

                    buffer += base_frame
                    # バッファが大きくなりすぎないよう制限
                    if len(buffer) > self.max_buffer_size:
                        buffer = buffer[-self.max_buffer_size :]

                    if len(buffer) >= self.chunk_bytes:
                        # VAD処理は同期APIなのでrun_in_executorで実行
                        is_speech = await loop.run_in_executor(
                            None,
                            lambda: self.vad.is_speech(
                                buffer[: self.chunk_bytes], self.rate
                            ),
                        )

                        # 状態を更新
                        await self._update_state(is_speech)

                        if self.callback:
                            try:
                                # コールバックが非同期関数か確認
                                if asyncio.iscoroutinefunction(self.callback):
                                    await self.callback(is_speech)
                                else:
                                    await loop.run_in_executor(
                                        None, self.callback, is_speech
                                    )
                            except Exception as cb_err:
                                logging.error(f"VAD callback error: {cb_err}")

                        buffer = buffer[self.chunk_bytes :]
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logging.error(f"Error in VAD processing: {e}")
                    logging.error(traceback.format_exc())
                    await asyncio.sleep(0.1)  # エラー時に少し待機
        except Exception as e:
            logging.error(f"Error in VAD main loop: {e}")
            logging.error(traceback.format_exc())

    def start(self):
        """
        非同期タスクを開始
        """
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run())

    async def stop(self):
        """
        非同期タスクを停止
        """
        self.stop_event.set()
        if self._task is not None and not self._task.done():
            await self._task

    @property
    def is_speech(self) -> bool:
        return self._state.get("is_speech", False)

    @property
    def silence_count(self) -> int:
        return self._state.get("silence_count", 0)

    @property
    def speech_count(self) -> int:
        return self._state.get("speech_count", 0)

    async def _update_state(self, is_speech):
        """
        状態を更新
        """
        async with self._lock:
            self._state["is_speech"] = is_speech
            if is_speech:
                self._state["silence_count"] = 0
                self._state["speech_count"] = self._state.get("speech_count", 0) + 1
            else:
                self._state["silence_count"] = self._state.get("silence_count", 0) + 1
                self._state["speech_count"] = 0

    async def reset_state(self):
        """
        状態をリセット
        """
        async with self._lock:
            self._state.clear()


class AsyncAudioCapture:
    """
    PyAudioの非同期ラッパークラス
    """

    def __init__(self, queue_list: List[asyncio.Queue], rate: int = RATE):
        self.queue_list = queue_list
        self.rate = rate
        self.audio_interface = pyaudio.PyAudio()

        self.read_frame_count = BASE_CHUNK
        self.audio_stream = self.audio_interface.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.rate,
            input=True,
            frames_per_buffer=self.read_frame_count,
        )

        self.stop_event = asyncio.Event()
        self._task = None

    async def run(self):
        """
        非同期のメインループ
        """
        loop = asyncio.get_running_loop()

        try:
            while not self.stop_event.is_set():
                # PyAudioは同期APIなのでrun_in_executorで実行
                audio_data = await loop.run_in_executor(
                    None,
                    lambda: self.audio_stream.read(
                        self.read_frame_count, exception_on_overflow=False
                    ),
                )

                # 各キューにデータを送信
                for queue in self.queue_list:
                    await queue.put(audio_data)

                # CPU使用率を下げるために少し待機
                await asyncio.sleep(0.001)

        except Exception as e:
            logging.error(f"Error in AudioCapture: {e}")
            logging.error(traceback.format_exc())
        finally:
            # クリーンアップ
            self.audio_stream.stop_stream()
            self.audio_stream.close()
            self.audio_interface.terminate()

    def start(self):
        """
        非同期タスクを開始
        """
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run())

    async def stop(self):
        """
        非同期タスクを停止
        """
        self.stop_event.set()
        if self._task is not None and not self._task.done():
            await self._task


class AsyncFastSTT:
    """
    STTとVADを統合する非同期クラス
    """

    def __init__(
        self,
        *,
        stt_callback: Optional[
            Callable[[Dict[str, Any]], None | Coroutine[Any, Any, None]]
        ] = None,
        vad_callback: Optional[
            Callable[[bool], None | Coroutine[Any, Any, None]]
        ] = None,
    ):
        # 各キューを作成
        self.stt_queue = asyncio.Queue()
        self.vad_queue = asyncio.Queue()

        # 各コンポーネントを初期化
        self.stt = AsyncGoogleSpeechRecognition(
            audio_queue=self.stt_queue, callback=stt_callback
        )
        self.vad = AsyncWebRTCVAD(audio_queue=self.vad_queue, callback=vad_callback)
        self.audio_capture = AsyncAudioCapture([self.stt_queue, self.vad_queue])

    def start(self):
        """
        全コンポーネントを開始
        """
        self.audio_capture.start()
        self.stt.start()
        self.vad.start()

    async def stop(self):
        """
        全コンポーネントを停止
        """
        await self.audio_capture.stop()
        await self.stt.stop()
        await self.vad.stop()

    @property
    def is_speech_ended(self) -> bool:
        """
        音声入力が終了したかどうか
        """
        return self.vad.silence_count > 10 and self.stt.text != ""

    @property
    def is_speech_started(self) -> bool:
        """
        音声入力が開始されたかどうか
        """
        return self.vad.speech_count > 10


if __name__ == "__main__":

    async def async_stt_callback(result):
        """非同期STTコールバック"""
        logging.info("[Async STT Callback]: %s", result)

    async def async_vad_callback(is_speech):
        """非同期VADコールバック"""
        logging.info("[Async VAD Callback]: %s", is_speech)

    # 同期コールバック関数を使う場合の例
    def sync_stt_callback(result):
        """同期STTコールバック"""
        logging.info("[Sync STT Callback]: %s", result)

    def sync_vad_callback(is_speech):
        """同期VADコールバック"""
        logging.info("[Sync VAD Callback]: %s", is_speech)

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
        # 非同期コールバック関数を渡す
        faststt = AsyncFastSTT(
            stt_callback=sync_stt_callback,  # 同期コールバックでもOK
            vad_callback=sync_vad_callback,
        )

        # 開始
        faststt.start()
        logging.info("音声認識を開始しました。Ctrl+Cで停止します。")

        # モニタリングタスク
        async def monitor_state():
            while not stop_event.is_set():
                logging.info(
                    f"状態: speech_started={faststt.is_speech_started}, "
                    f"speech_ended={faststt.is_speech_ended}, "
                    f"text='{faststt.stt.text}', "
                    f"speech_count={faststt.vad.speech_count}, "
                    f"silence_count={faststt.vad.silence_count}"
                )
                await asyncio.sleep(1)

        # モニタリングタスクを開始
        monitor_task = asyncio.create_task(monitor_state())

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
        await faststt.stop()

        logging.info("正常に終了しました")
        return 0

    # モニタリング付きの音声認識を実行
    exit_code = asyncio.run(async_main_with_monitoring())
    sys.exit(exit_code)
