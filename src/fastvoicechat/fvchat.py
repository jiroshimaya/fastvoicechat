import asyncio
import logging
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

from fastvoicechat.base import CallbackLoop
from fastvoicechat.llm import LLM
from fastvoicechat.stt import STT, create_stt
from fastvoicechat.tts import TTS

# スレッド版と同じシステムプロンプトを使用
BACKCHANNEL_SYSTEM_PROMPT = (
    "対話履歴を踏まえて適切な相槌を生成してください。"
    "ユーザの発話は音声認識の途中である可能性があります。"
    "相手が発話途中である可能性が高い場合はリスクを避け「うん」「うんうん」「あー」「えーっと」「うーん」など無難な相槌を出力してください。"
)
ANSWER_SYSTEM_PROMPT = (
    "以下の会話履歴を参考に、適切な回答を生成してください。"
    "ただし、あなた（アシスタント）はすでに一言目（対話履歴の末尾に付与されている）を発話していますので"
    "自然につながるように二言目以降を生成してください。"
    "例えば一言目と全く同じことを生成することは基本的に避けてください。"
    "対話の流れを踏まえ二言目以降を生成する必要がなければ`NA`とだけ出力してください。"
    "また、これは音声対話であるため、回答はなるべく短く簡潔にしてください。"
)


class FastVoiceChat:
    """音声対話を高速に行うための非同期クラス

    このクラスは音声認識（STT）、テキスト音声合成（TTS）、大規模言語モデル（LLM）を
    組み合わせて、自然な音声対話を実現します。以下の特徴があります：

    - 非同期処理による高速なレスポンス
    - 相槌生成による自然な対話
    - ユーザーの割り込み発話への対応
    - 音声認識結果のストリーミング処理

    Attributes:
        tts (TTS): テキスト音声合成エンジン
        stt (STT): 音声認識エンジン
        allow_interrupt (bool): ユーザーの割り込み発話を許可するかどうか
        llm_backchannel (LLM): 相槌生成用の言語モデル
        llm_answer (LLM): 応答生成用の言語モデル

    Example:
        >>> from fastvoicechat import FastVoiceChat
        >>> from fastvoicechat.tts import TTS
        >>> from fastvoicechat.tts.synthesizers import VoiceVoxSynthesizer
        >>> from fastvoicechat.tts.players import SimpleAudioPlayer
        >>>
        >>> # シンセサイザーとプレイヤーの初期化
        >>> synthesizer = VoiceVoxSynthesizer(host='http://localhost:50021', speaker_id=0)
        >>> player = SimpleAudioPlayer()
        >>>
        >>> # TTSエンジンの初期化
        >>> tts = TTS(synthesizer=synthesizer, player=player)
        >>>
        >>> # FastVoiceChatの初期化と開始
        >>> chat = FastVoiceChat(tts=tts)
        >>> await chat.astart()
        >>>
        >>> # 対話の実行
        >>> responses = await chat.utter_after_listening()
        >>>
        >>> # 終了処理
        >>> await chat.astop()
    """

    def __init__(
        self,
        *,
        tts: TTS,
        stt_kwargs: Dict[str, Any] = {},
        allow_interrupt: bool = True,
        backchannel_system_prompt: str = BACKCHANNEL_SYSTEM_PROMPT,
        answer_system_prompt: str = ANSWER_SYSTEM_PROMPT,
        backchannel_model: str = "gpt-4o-mini",
        answer_model: str = "gpt-4o",
    ):
        """FastVoiceChatの初期化

        Args:
            tts (TTS): テキスト音声合成エンジン
            stt_kwargs (Dict[str, Any]): 音声認識エンジンの設定パラメータ
            allow_interrupt (bool): ユーザーの割り込み発話を許可するかどうか
            backchannel_system_prompt (str): 相槌生成用のシステムプロンプト
            answer_system_prompt (str): 応答生成用のシステムプロンプト
            backchannel_model (str): 相槌生成に使用する言語モデル
            answer_model (str): 応答生成に使用する言語モデル
        """
        self.tts = tts
        self.allow_interrupt = allow_interrupt

        self.backchannel_system_prompt = backchannel_system_prompt
        self.answer_system_prompt = answer_system_prompt
        self.backchannel_model = backchannel_model
        self.answer_model = answer_model

        # 各コンポーネントの初期化
        self.stt: STT
        self.stt_kwargs = stt_kwargs
        self.llm_backchannel: LLM
        self.llm_answer: LLM

        # 割り込み制御
        self.interrupt_event = asyncio.Event()
        self.interruption_observer: CallbackLoop

        # 処理ロック
        self.processing_lock = asyncio.Lock()

        # 初期化フラグ
        self._initialized = False
        self._running = False

    async def ainitialize(self):
        """コンポーネントを非同期に初期化します。

        このメソッドは以下のコンポーネントを初期化します：
        - 音声認識エンジン（STT）
        - 割り込み検出オブザーバー
        - 相槌生成用言語モデル
        - 応答生成用言語モデル

        各コンポーネントは非同期に初期化され、必要なコールバック関数も設定されます。
        二重初期化を防ぐため、既に初期化済みの場合は何もせずに終了します。

        Note:
            このメソッドは`astart`メソッドから自動的に呼び出されるため、
            通常は直接呼び出す必要はありません。

        Raises:
            RuntimeError: コンポーネントの初期化に失敗した場合
        """
        if self._initialized:
            return

        logging.debug("Initializing FastVoiceChat components...")

        # STT用コールバック関数
        async def arecognition_callback(result: Dict[str, Any]):
            user_input = result.get("text", "")
            logging.info(f"[STT]: {user_input}")

            # 相槌生成が必要かを判断
            if self.llm_backchannel and self.llm_backchannel.should_generate(
                user_input
            ):
                logging.info(f"[STT]: generation start: {user_input}")
                await self.llm_backchannel.astart_generate_task(user_input)

        # 割り込み検出用コールバック関数
        async def ainterruption_observer_callback():
            previous_result = await self.interruption_observer.aget("previous_result")

            # 割り込みを検出: ユーザが話し始めた & TTSが再生中
            interrupted = (
                self.stt
                and self.stt.is_speech_started
                and self.tts
                and self.tts.is_playing
            )

            await self.interruption_observer.aset("previous_result", interrupted)

            if interrupted:
                if self.allow_interrupt:
                    self.interrupt_event.set()
                    if not previous_result:
                        logging.info("[Observer]: interruption detected.")
                else:
                    if not previous_result:
                        logging.info(
                            "[Observer]: interruption detected, but not allowed."
                        )

        # 各コンポーネントの初期化
        logging.debug("Setting up AsyncFastSTT...")
        stt_kwargs = self.stt_kwargs.copy()
        stt_kwargs["recognition_kwargs"] = {
            **stt_kwargs.get("recognition_kwargs", {}),
            "callback": arecognition_callback,
        }
        self.stt = create_stt(**stt_kwargs)

        logging.debug("Setting up AsyncCallbackLoop for interruption observer...")
        self.interruption_observer = CallbackLoop(
            callback=ainterruption_observer_callback,
            interval=0.01,
            name="InterruptionObserver",
            previous_result=False,
        )

        logging.debug("Initializing AsyncLLM for backchannel and answer...")
        self.llm_backchannel = LLM(
            system_prompt=self.backchannel_system_prompt,
            model=self.backchannel_model,
            separator="、、。！？!?",
        )

        self.llm_answer = LLM(
            system_prompt=self.answer_system_prompt, model=self.answer_model
        )

        # TTSの初期化部分を削除
        self._initialized = True
        logging.debug("AsyncFastVoiceChat initialization complete")

    async def astart(self):
        """音声対話システムの全コンポーネントを起動します。

        このメソッドは以下の処理を行います：
        1. 未初期化の場合は`ainitialize`を呼び出してコンポーネントを初期化
        2. 音声認識エンジン（STT）の起動
        3. 割り込み検出オブザーバーの起動

        Note:
            - このメソッドは非同期で実行されます
            - 音声対話を開始する前に必ず呼び出す必要があります
            - 既に起動している場合は安全に無視されます

        Example:
            >>> chat = FastVoiceChat(tts=tts)
            >>> await chat.astart()  # 音声対話システムを起動
            >>> # ここで音声対話の処理を実行
            >>> await chat.astop()   # 終了時に停止
        """
        if not self._initialized:
            await self.ainitialize()

        self._running = True
        logging.debug("Starting AsyncFastVoiceChat components...")

        # 各コンポーネントを起動
        if self.stt:
            await self.stt.astart()

        if self.interruption_observer:
            await self.interruption_observer.astart()

    async def astop(self):
        """音声対話システムの全コンポーネントを停止し、リソースを解放します。

        このメソッドは以下の処理を行います：
        1. 音声認識エンジン（STT）の停止
        2. 割り込み検出オブザーバーの停止
        3. 相槌生成タスクの停止とキャンセル
        4. 応答生成タスクの停止とキャンセル
        5. TTSエンジンの停止
        6. 各種リソース（TTSエンジン、LLMクライアント）の解放

        Note:
            - このメソッドは非同期で実行されます
            - 音声対話を終了する際に必ず呼び出す必要があります
            - 既に停止している場合は安全に無視されます
            - 一度停止したら、再度`astart`を呼び出すまで使用できません

        Example:
            >>> chat = FastVoiceChat(tts=tts)
            >>> await chat.astart()
            >>> # 音声対話の処理
            >>> await chat.astop()  # 終了時にリソースを解放
        """
        if not self._running:
            return

        logging.debug(
            "Stopping AsyncFastVoiceChat components and releasing resources..."
        )

        # 各コンポーネントの停止
        if self.stt:
            await self.stt.astop()

        if self.interruption_observer:
            await self.interruption_observer.astop()

        if self.llm_backchannel:
            await self.llm_backchannel.astop_all()
            await self.llm_backchannel.acancel_all()

        if self.llm_answer:
            await self.llm_answer.astop_all()
            await self.llm_answer.acancel_all()

        if self.tts:
            await self.tts.astop()

        # リソースの解放
        if self.tts:
            await self.tts.aclose()

        # LLMのクライアントを解放
        if self.llm_backchannel:
            await self.llm_backchannel.aclose()

        if self.llm_answer:
            await self.llm_answer.aclose()

        self._running = False
        logging.debug("AsyncFastVoiceChat components stopped and resources released")

    def stop(self):
        """同期版のstopメソッド"""
        # 既存のasyncioイベントループがあるかチェック
        try:
            loop = asyncio.get_running_loop()
            already_running = True
        except RuntimeError:
            already_running = False

        if already_running:
            # 既にイベントループが実行中の場合はエラー
            raise RuntimeError(
                "stop は既存の asyncio イベントループの中から呼び出せません。"
                "非同期コンテキスト内からは astop を直接使用してください。"
            )
        else:
            # 共有イベントループを使用
            if (
                hasattr(FastVoiceChat, "_shared_loop")
                and not FastVoiceChat._shared_loop.is_closed()
            ):
                loop = FastVoiceChat._shared_loop
                loop.run_until_complete(self.astop())
            else:
                # 共有ループがない場合は一時的なループを作成
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self.astop())
                finally:
                    # 一時的なループは閉じる
                    loop.close()

    async def aplay_voice(
        self,
        text: str,
        pause_stt: bool = True,
        restart_stt: bool = True,
        interrupt_event: Optional[asyncio.Event] = None,
    ) -> bool:
        """テキストを音声に変換して再生します。

        このメソッドは、指定されたテキストをTTSエンジンを使用して音声に変換し、
        再生します。音声認識との干渉を防ぐため、デフォルトでは再生中は音声認識を
        一時停止します。

        Args:
            text (str): 読み上げるテキスト
            pause_stt (bool, optional): 音声認識を一時停止するかどうか。デフォルトはTrue
            restart_stt (bool, optional): 再生後に音声認識を再開するかどうか。デフォルトはTrue
            interrupt_event (asyncio.Event, optional): 再生を中断するためのイベント。
                Noneの場合はデフォルトのinterrupt_eventが使用されます。

        Returns:
            bool: 再生が完了したかどうか（Falseなら中断された）

        Note:
            - このメソッドは非同期で実行されます
            - 音声認識を一時停止する場合、再生完了後に自動的に再開されます
            - interrupt_eventがセットされた場合、再生は即座に中断されます

        Example:
            >>> # 通常の再生
            >>> completed = await chat.aplay_voice("こんにちは")
            >>>
            >>> # 音声認識を維持したまま再生
            >>> completed = await chat.aplay_voice("こんにちは", pause_stt=False)
            >>>
            >>> # 中断可能な再生
            >>> event = asyncio.Event()
            >>> completed = await chat.aplay_voice("こんにちは", interrupt_event=event)
            >>> # 別のコルーチンでevent.set()を呼び出すと再生が中断されます
        """
        if not self.tts:
            logging.error("TTS not initialized")
            return False

        # 音声認識の一時停止
        if pause_stt and self.stt and self.stt.recognition:
            await self.stt.recognition.apause()

        # 音声再生
        result = await self.tts.aplay_voice(text, interrupt_event=interrupt_event)

        # 音声認識の再開
        if restart_stt and self.stt and self.stt.recognition:
            await self.stt.recognition.astart_new_session()

        return result

    async def autter_after_listening(
        self, *, add_history: bool = True, additional_utterance: str = ""
    ) -> List[Tuple[str, str]]:
        """
        ユーザの発話を聞いてから応答を生成して発話

        Args:
            add_history: 会話履歴に追加するかどうか
            additional_utterance: 応答後に追加で発話するテキスト

        Returns:
            List[Tuple[str, str]]: 生成された会話履歴
        """
        if not self._initialized:
            await self.ainitialize()

        if not self._running:
            await self.astart()

        # 発話終了を待機
        while not self.stt.is_speech_ended:
            await asyncio.sleep(0.01)

        # 割り込みイベントをクリア
        self.interrupt_event.clear()

        # 処理の重複を防ぐためのロック取得
        async with self.processing_lock:
            # 相槌処理
            backchannel_text = self.llm_backchannel.previous_user_input

        # 相槌キューが空なら少し待機
        while self.llm_backchannel.answer_queue.empty():
            await asyncio.sleep(0.01)

        # 相槌取得
        backchannel_answer = await self.llm_backchannel.answer_queue.get()
        logging.info(f"[LLM Backchannel]: {backchannel_text} -> {backchannel_answer}")

        # 相槌再生前に音声認識を一時停止
        await self.stt.recognition.apause()

        async with self.processing_lock:
            user_input = self.stt.recognition.text

        additional_messages = None
        if backchannel_answer:
            additional_messages = [("assistant", backchannel_answer)]

        # 本回答の生成を開始
        if self.llm_answer.should_generate(user_input):
            await self.llm_answer.astart_generate_task(
                user_input, additional_messages=additional_messages
            )

        # 相槌の再生
        await self.tts.aplay_voice(
            backchannel_answer,
            interrupt_event=self.interrupt_event,
        )

        # 本回答の生成を一定時間待機
        wait_timeout = 2  # 待機タイムアウト（秒）
        wait_start = time.time()
        while self.llm_answer.answer_queue.empty():
            if time.time() - wait_start > wait_timeout:
                logging.debug("[LLM Answer]: Timed out waiting for answer")
                break
            await asyncio.sleep(0.1)

        # 割り込みイベントをクリア
        self.interrupt_event.clear()

        # 本回答の再生
        detail_answer = ""
        detail_full_answer = ""

        while not self.llm_answer.answer_queue.empty():
            # 割り込みがあった場合は処理を中断
            if self.interrupt_event.is_set() and self.allow_interrupt:
                logging.info("[LLM Answer]: Interrupted during answer synthesis")
                break

            # 回答チャンクを取得
            detail_answer = await self.llm_answer.answer_queue.get()

            # "NA"はスキップフラグ
            if detail_answer == "NA":
                logging.info(
                    f"[LLM Answer]: {self.llm_answer.previous_user_input} -> {backchannel_answer} -> {detail_answer}"
                )
                break

            logging.info(
                f"[LLM Answer]: {self.llm_answer.previous_user_input} -> {backchannel_answer} -> {detail_answer}"
            )

            # 応答チャンクを再生
            await self.tts.aplay_voice(
                detail_answer,
                interrupt_event=self.interrupt_event,
            )

            # 割り込みがあれば中断
            if self.interrupt_event.is_set() and self.allow_interrupt:
                logging.info("[TTS]: stop due to user interruption")
                break

            detail_full_answer += detail_answer

        # 追加発話があれば再生
        uttered_additional_utterance = ""
        if additional_utterance:
            await self.tts.aplay_voice(
                additional_utterance,
                interrupt_event=self.interrupt_event,
            )

            if not (self.interrupt_event.is_set() and self.allow_interrupt):
                uttered_additional_utterance = additional_utterance

        # 会話履歴の作成
        async with self.processing_lock:
            previous_user_input = self.llm_backchannel.previous_user_input

        new_history = [
            ("user", previous_user_input),
            ("assistant", backchannel_answer),
        ]

        if detail_full_answer:
            new_history.append(("assistant", detail_full_answer))

        if uttered_additional_utterance:
            new_history.append(("assistant", uttered_additional_utterance))

        # 会話履歴の更新
        if add_history:
            await self.llm_backchannel.aadd_history(new_history)
            await self.llm_answer.aadd_history(new_history)

        await self.llm_backchannel.areset()
        await self.llm_answer.areset()
        await self.stt.recognition.astart_new_session()
        self.interrupt_event.clear()

        return new_history

    def utter_after_listening(
        self, *, add_history: bool = True, additional_utterance: str = ""
    ) -> List[Tuple[str, str]]:
        """
        ユーザの発話を聞いてから応答を生成して発話 (同期版)

        同期的なインターフェースを提供するラッパー関数です。
        内部では非同期処理を実行します。

        Args:
            add_history: 会話履歴に追加するかどうか
            additional_utterance: 応答後に追加で発話するテキスト

        Returns:
            List[Tuple[str, str]]: 生成された会話履歴
        """
        # 既存のasyncioイベントループがあるかチェック
        try:
            loop = asyncio.get_running_loop()
            already_running = True
        except RuntimeError:
            already_running = False

        if already_running:
            # 既にイベントループが実行中の場合はエラー
            raise RuntimeError(
                "utter_after_listening は既存の asyncio イベントループの中から呼び出せません。"
                "非同期コンテキスト内からは utter_after_listening を直接使用してください。"
            )
        else:
            # クラス変数として保持している単一のイベントループを使用または作成
            if not hasattr(FastVoiceChat, "_shared_loop"):
                FastVoiceChat._shared_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(FastVoiceChat._shared_loop)

            loop = FastVoiceChat._shared_loop

            # 前回の実行でイベントループが閉じられていたら再作成
            if loop.is_closed():
                FastVoiceChat._shared_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(FastVoiceChat._shared_loop)
                loop = FastVoiceChat._shared_loop

            try:
                # 非同期関数を実行
                return loop.run_until_complete(
                    self.autter_after_listening(
                        add_history=add_history,
                        additional_utterance=additional_utterance,
                    )
                )
            except Exception as e:
                logging.error(f"Error in utter_after_listening: {e}")
                logging.error(traceback.format_exc())
                # エラーが発生した場合でもイベントループは閉じない
                return []

    def __del__(self):
        """オブジェクトが破棄されるときにリソースを解放"""
        if self._initialized:
            try:
                # 既存のasyncioイベントループがあるかチェック
                try:
                    asyncio.get_running_loop()
                    already_running = True
                except RuntimeError:
                    already_running = False

                if (
                    not already_running
                    and hasattr(FastVoiceChat, "_shared_loop")
                    and not FastVoiceChat._shared_loop.is_closed()
                ):
                    # 共有ループを使用してリソースを解放
                    FastVoiceChat._shared_loop.run_until_complete(self.astop())
            except Exception as e:
                logging.error(f"Error in __del__: {e}")
                # デストラクタ内のエラーは無視
