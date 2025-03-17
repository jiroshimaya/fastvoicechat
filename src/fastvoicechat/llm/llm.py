import asyncio
import logging
import signal
import sys
import time
import traceback
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple

from openai import AsyncOpenAI


@dataclass
class TaskInfo:
    """非同期タスク情報を保持するデータクラス"""

    task: asyncio.Task
    stop_event: asyncio.Event
    start_time: float
    user_input: str
    additional_messages: List[Tuple[str, str]]


class LLM:
    """
    LLMをasyncioで並列実行する非同期クラス

    元のマルチスレッドバージョンをasyncio対応に変更
    """

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        system_prompt: str = "",
        separator: str = "。！？!?",
    ):
        self.model = model
        self.system_prompt = system_prompt
        self.client = AsyncOpenAI()
        self._state: Dict[str, Any] = {}
        self.answer_queue = asyncio.Queue()
        self.tasks: List[TaskInfo] = []
        self.separator = separator
        self._lock = asyncio.Lock()

    def should_generate(self, user_input: str) -> bool:
        """
        ユーザー入力に対して生成すべきかどうかを判断

        Args:
            user_input: ユーザーの入力テキスト

        Returns:
            bool: 生成すべきならTrue
        """
        if not user_input:
            return False

        if user_input and not self.tasks:
            return True

        if self.tasks:
            latest_task = self.tasks[-1]
            if not latest_task.task.done() and latest_task.user_input == user_input:
                return False

        previous_user_input = self.previous_user_input
        if user_input == previous_user_input:
            return False

        return True

    async def astop_old_tasks(self, current_time: float):
        """
        指定した時間より前に開始されたタスクを停止

        Args:
            current_time: 基準となる時間
        """
        for task_info in self.tasks:
            if task_info.start_time < current_time:
                task_info.stop_event.set()

    async def acancel_old_tasks(self, current_time: float):
        """
        指定した時間より前に開始されたタスクをキャンセルして終了を待機

        Args:
            current_time: 基準となる時間
        """
        for task_info in self.tasks:
            if task_info.start_time < current_time:
                if not task_info.task.done():
                    task_info.stop_event.set()
                    task_info.task.cancel()
                    try:
                        await task_info.task
                    except asyncio.CancelledError:
                        pass

    async def acleanup_done_tasks(self):
        """終了したタスクをリストから削除"""
        self.tasks = [
            task_info for task_info in self.tasks if not task_info.task.done()
        ]

    async def _agenerate(
        self,
        user_input: str,
        stop_event: asyncio.Event,
        additional_messages: List[Tuple[str, str]],
    ) -> AsyncGenerator[str, None]:
        """
        テキスト生成の内部実装

        Args:
            user_input: ユーザー入力
            stop_event: 停止イベント
            additional_messages: 追加メッセージ

        Yields:
            生成されたテキストチャンク
        """
        # メッセージの準備
        messages_tuple = []
        if self.system_prompt:
            messages_tuple.append(("system", self.system_prompt))

        if "history" in self._state:
            messages_tuple.extend(self._state["history"])

        messages_tuple.append(("user", user_input))

        if additional_messages:
            messages_tuple.extend(additional_messages)

        messages = self.tuples_to_messages(messages_tuple)

        # APIリクエスト
        response = await self.client.chat.completions.create(
            messages=messages,
            model=self.model,
            stream=True,
        )

        # レスポンス処理
        answer = ""
        async for chunk in response:
            if stop_event.is_set():
                break

            content = chunk.choices[0].delta.content
            if not content:
                continue

            answer += content

            # 句点、！、？、!、?が見つかった場合、現在の文を返す
            if content[-1] in self.separator:
                yield answer
                answer = ""

        if answer:
            yield answer

    async def agenerate(
        self,
        user_input: str,
        stop_event: asyncio.Event,
        start_time: float,
        additional_messages: Optional[List[Tuple[str, str]]] = None,
        progress_callback: Optional[Callable[[str], Any]] = None,
        completion_callback: Optional[Callable[[str], Any]] = None,
    ):
        """
        テキスト生成を実行

        Args:
            user_input: ユーザー入力
            stop_event: 停止イベント
            start_time: 開始時間
            additional_messages: 追加メッセージ
            progress_callback: 進捗コールバック
            completion_callback: 完了時コールバック
        """
        if additional_messages is None:
            additional_messages = []

        try:
            is_first = True
            answer = ""

            async for chunk in self._agenerate(
                user_input, stop_event, additional_messages
            ):
                if stop_event.is_set():
                    break

                # 進捗コールバックの呼び出し
                if progress_callback:
                    if asyncio.iscoroutinefunction(progress_callback):
                        await progress_callback(chunk)
                    else:
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(None, progress_callback, chunk)

                # 最初のチャンクが来たら古いタスクを停止
                if is_first:
                    await self.astop_old_tasks(start_time)
                    await self.acancel_old_tasks(start_time)
                    await self.acleanup_done_tasks()

                    async with self._lock:
                        self._state["previous_user_input"] = user_input

                    # 回答キューをクリア
                    while not self.answer_queue.empty():
                        try:
                            self.answer_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break

                    is_first = False

                # 回答キューに追加
                await self.answer_queue.put(chunk)
                answer += chunk

            # 完了コールバックの呼び出し
            if completion_callback and not stop_event.is_set():
                if asyncio.iscoroutinefunction(completion_callback):
                    await completion_callback(answer)
                else:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, completion_callback, answer)

        except Exception as e:
            logging.error(f"Error in generate: {e}")
            logging.error(traceback.format_exc())

    async def astart_generate_task(
        self,
        user_input: str,
        *,
        additional_messages: Optional[List[Tuple[str, str]]] = None,
        progress_callback: Optional[Callable[[str], Any]] = None,
        completion_callback: Optional[Callable[[str], Any]] = None,
    ):
        """
        テキスト生成タスクを開始

        Args:
            user_input: ユーザー入力
            additional_messages: 追加メッセージ
            progress_callback: 進捗コールバック
            completion_callback: 完了時コールバック
        """

        stop_event = asyncio.Event()
        start_time = time.time()

        # 非同期タスクを作成
        task = asyncio.create_task(
            self.agenerate(
                user_input,
                stop_event,
                start_time,
                additional_messages,
                progress_callback,
                completion_callback,
            )
        )

        if additional_messages is None:
            additional_messages = []

        # タスク情報を保存
        task_info = TaskInfo(
            task=task,
            stop_event=stop_event,
            start_time=start_time,
            user_input=user_input,
            additional_messages=additional_messages,
        )

        self.tasks.append(task_info)

    @property
    def previous_user_input(self) -> str:
        """前回のユーザー入力"""
        return self._state.get("previous_user_input", "")

    @property
    def history(self) -> List[Tuple[str, str]]:
        """会話履歴"""
        return self._state.get("history", [])

    async def aadd_history(self, value: List[Tuple[str, str]]) -> None:
        """
        会話履歴に追加

        Args:
            value: 追加する会話履歴
        """
        async with self._lock:
            if "history" not in self._state:
                self._state["history"] = []
            self._state["history"] += value

    def tuples_to_messages(self, value: List[Tuple[str, str]]) -> list:
        """
        タプルのリストをAPIに送るメッセージ形式に変換

        Args:
            value: (role, content)形式のタプル

        Returns:
            OpenAI APIメッセージ形式
        """
        return [{"role": role, "content": content} for role, content in value]

    async def astop_all(self):
        """すべてのタスクを停止"""
        for task_info in self.tasks:
            task_info.stop_event.set()

    async def acancel_all(self):
        """すべてのタスクをキャンセル"""
        for task_info in self.tasks:
            task_info.stop_event.set()
            if not task_info.task.done():
                task_info.task.cancel()
                try:
                    await task_info.task
                except asyncio.CancelledError:
                    pass

    async def areset(self):
        """状態をリセット"""
        await self.astop_all()
        await self.acancel_all()
        await self.acleanup_done_tasks()

        async with self._lock:
            self._state["previous_user_input"] = ""

        # 回答キューをクリア
        while not self.answer_queue.empty():
            try:
                self.answer_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def aclose(self):
        """クライアントリソースを解放"""
        await self.areset()
        if hasattr(self, "client") and self.client:
            await self.client.close()


# AsyncSTTクラスをインポート（既存のファイルからインポートするように調整してください）
# from async_stt import AsyncGoogleSpeechRecognition, AsyncWebRTCVAD, AsyncAudioCapture, AsyncFastSTT
# 仮に上記のファイルがasync_stt.pyという名前だとします

# AsyncLLMクラスをインポート（既存のファイルからインポートするように調整してください）
# from async_llm import AsyncLLM
# 仮に上記のファイルがasync_llm.pyという名前だとします


async def main():
    """
    非同期メイン関数 - AsyncSTTとAsyncLLMを使用する音声対話システム
    コールバックループを使わないシンプルな実装
    """

    from fastvoicechat.stt import create_stt

    # ロギング設定
    logging.basicConfig(
        level=logging.INFO,
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

    # 処理の重複実行を防ぐためのロック
    processing_lock = asyncio.Lock()

    # 各コンポーネントの作成
    async def recognition_callback(result: Dict[str, Any]):
        """音声認識結果のコールバック"""
        user_input = result.get("text", "")
        logging.info(f"[STT]: {user_input}")

        if llm_backchannel.should_generate(user_input):
            logging.info(f"[STT]: generation start: {user_input}")
            # 相槌生成を開始
            await llm_backchannel.astart_generate_task(user_input)

    async def vad_callback(is_speech: bool):
        """音声活動検出のコールバック"""
        # 必要な場合のみ処理を実行（沈黙が10フレーム以上続き、テキストが存在する場合）
        if not is_speech and faststt.vad.silence_count >= 10 and faststt.text:
            # 沈黙検出時の処理
            await process_vad_silence()

    async def process_vad_silence():
        """
        沈黙検出時の処理 - 相槌と回答の生成
        元のスレッド版のvad_callbackと同様の処理だが非同期版
        """
        # 既に処理中なら重複実行を避ける
        if not processing_lock.locked():
            async with processing_lock:
                # 相槌の生成結果を取得
                backchannel_text = llm_backchannel.previous_user_input

                # 相槌キューが空なら処理しない
                if llm_backchannel.answer_queue.empty():
                    return

                backchannel_answer = await llm_backchannel.answer_queue.get()

                # 相槌表示
                logging.info(
                    f"[LLM Backchannel]: {backchannel_text} -> {backchannel_answer}"
                )

                # 本回答の生成 - スレッド版と同様に直接呼び出し
                user_input = faststt.text
                additional_messages = None
                if backchannel_answer:
                    additional_messages = [("assistant", backchannel_answer)]

                if llm_answer.should_generate(user_input):
                    # 直接start_generate_taskを呼び出し（コールバックループなし）
                    await llm_answer.astart_generate_task(
                        user_input, additional_messages=additional_messages
                    )

                # スレッド版と同様に少し待機（非同期版）
                await asyncio.sleep(2)

                # 本回答の取得と表示
                detail_answer = ""
                while not llm_answer.answer_queue.empty():
                    chunk = await llm_answer.answer_queue.get()
                    detail_answer += chunk
                    logging.info(
                        f"[LLM Answer]: {llm_answer.previous_user_input} -> {detail_answer}"
                    )
                    # 表示のためにわずかに待機
                    await asyncio.sleep(2)

                # 会話履歴の更新
                previous_user_input = llm_backchannel.previous_user_input
                await llm_backchannel.aadd_history(
                    [
                        ("user", previous_user_input),
                        ("assistant", backchannel_answer),
                        ("assistant", detail_answer),
                    ]
                )

                await llm_answer.aadd_history(
                    [
                        ("user", previous_user_input),
                        ("assistant", backchannel_answer),
                        ("assistant", detail_answer),
                    ]
                )

                # 状態のリセット
                await llm_backchannel.areset()
                await llm_answer.areset()
                await faststt.recognition.astart_new_session()

    logging.info("非同期音声対話システムを初期化中...")

    # FastSTTの作成
    faststt = create_stt(
        recognition_type="vosk",
        vad_type="webrtcvad",
        recognition_kwargs={"callback": recognition_callback},
        vad_kwargs={"callback": vad_callback},
    )

    # LLMの作成
    backchannel_system_prompt = (
        "対話履歴を踏まえて適切な相槌を生成してください。"
        "ユーザの発話は音声認識の途中である可能性があります。"
        "どのような相槌が適切か判断が難しい場合は「へー」「うーん」など無難な相槌を出力してください。"
    )

    llm_backchannel = LLM(system_prompt=backchannel_system_prompt, model="gpt-4o-mini")

    llm_answer = LLM(model="gpt-4o")

    # システム開始
    await faststt.astart()
    logging.info(
        "音声認識とLLMのインテグレーションを開始しました。話しかけてください..."
    )

    # モニタリングタスク
    async def monitor_state():
        """システムの状態を定期的に表示"""
        while not stop_event.is_set():
            logging.debug(
                f"状態: speech_started={faststt.is_speech_started}, "
                f"speech_ended={faststt.is_speech_ended}, "
                f"text='{faststt.text}'"
            )
            await asyncio.sleep(3)  # 3秒ごとに状態を表示

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

    # 終了処理
    logging.info("システムを停止中...")
    await faststt.astop()
    await llm_backchannel.areset()
    await llm_answer.areset()

    logging.info("正常に終了しました")
    return 0


if __name__ == "__main__":
    # 非同期プログラムを実行
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("KeyboardInterruptを検知しました。終了します...")
        sys.exit(1)
