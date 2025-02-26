import asyncio
import logging
import time
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastvoicechat.base import CallbackLoop
from fastvoicechat.llm import LLM
from fastvoicechat.stt import FastSTT
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
    """音声対話を高速に行うための非同期クラス"""

    def __init__(
        self,
        *,
        speaker: Literal["pc"] = "pc",
        voicevox_host: str = "localhost:50021",
        allow_interrupt: bool = True,
        backchannel_system_prompt: str = BACKCHANNEL_SYSTEM_PROMPT,
        answer_system_prompt: str = ANSWER_SYSTEM_PROMPT,
        backchannel_model: str = "gpt-4o-mini",
        answer_model: str = "gpt-4o",
    ):
        self.speaker: Literal["pc"] = speaker
        self.voicevox_host = voicevox_host
        self.allow_interrupt = allow_interrupt

        self.backchannel_system_prompt = backchannel_system_prompt
        self.answer_system_prompt = answer_system_prompt
        self.backchannel_model = backchannel_model
        self.answer_model = answer_model

        # 各コンポーネントの初期化
        self.faststt: FastSTT
        self.llm_backchannel: LLM
        self.llm_answer: LLM
        self.tts: TTS

        # 割り込み制御
        self.interrupt_event = asyncio.Event()
        self.interruption_observer: CallbackLoop

        # 処理ロック
        self.processing_lock = asyncio.Lock()

        # 初期化フラグ
        self._initialized = False
        self._running = False

    async def initialize(self):
        """コンポーネントを初期化"""
        if self._initialized:
            return

        logging.debug("Initializing AsyncFastVoiceChat components...")

        # STT用コールバック関数
        async def stt_callback(result: Dict[str, Any]):
            user_input = result.get("text", "")
            logging.info(f"[STT]: {user_input}")

            # 相槌生成が必要かを判断
            if self.llm_backchannel and self.llm_backchannel.should_generate(
                user_input
            ):
                logging.info(f"[STT]: generation start: {user_input}")
                self.llm_backchannel.start_generate_task(user_input)

        # 割り込み検出用コールバック関数
        async def interruption_observer_callback():
            previous_result = await self.interruption_observer.get("previous_result")

            # 割り込みを検出: ユーザが話し始めた & TTSが再生中
            interrupted = (
                self.faststt
                and self.faststt.is_speech_started
                and self.tts
                and self.tts.is_playing
            )

            await self.interruption_observer.set("previous_result", interrupted)

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
        self.faststt = FastSTT(stt_callback=stt_callback)

        logging.debug("Setting up AsyncCallbackLoop for interruption observer...")
        self.interruption_observer = CallbackLoop(
            callback=interruption_observer_callback,
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

        logging.debug("Initializing AsyncTTS...")
        self.tts = TTS(voicevox_host=self.voicevox_host)

        self._initialized = True
        logging.debug("AsyncFastVoiceChat initialization complete")

    def start(self):
        """非同期タスクを開始"""
        if not self._initialized:
            asyncio.create_task(self.initialize())

        self._running = True
        logging.debug("Starting AsyncFastVoiceChat components...")

        # 各コンポーネントを起動
        if self.faststt:
            self.faststt.start()

        if self.interruption_observer:
            self.interruption_observer.start()

    async def stop(self):
        """全コンポーネントを停止"""
        if not self._running:
            return

        logging.debug("Stopping AsyncFastVoiceChat components...")

        # 各コンポーネントの停止
        if self.faststt:
            await self.faststt.stop()

        if self.interruption_observer:
            await self.interruption_observer.stop()

        if self.llm_backchannel:
            await self.llm_backchannel.stop_all()
            await self.llm_backchannel.cancel_all()

        if self.llm_answer:
            await self.llm_answer.stop_all()
            await self.llm_answer.cancel_all()

        if self.tts:
            await self.tts.stop()

        self._running = False
        logging.debug("AsyncFastVoiceChat components stopped")

    async def join(self):
        """全コンポーネントの終了を待機"""
        # asyncioでは明示的なjoinは必要ないが、一貫性のためのメソッド
        await self.stop()

    async def play_voice(
        self,
        text: str,
        pause_stt: bool = True,
        restart_stt: bool = True,
        interrupt_event: Optional[asyncio.Event] = None,
    ) -> bool:
        """
        テキストを音声に変換して再生

        Args:
            text: 読み上げるテキスト
            pause_stt: 音声認識を一時停止するかどうか
            restart_stt: 再生後に音声認識を再開するかどうか
            interrupt_event: 再生を中断するためのイベント

        Returns:
            bool: 再生が完了したかどうか（Falseなら中断された）
        """
        if not self.tts:
            logging.error("TTS not initialized")
            return False

        # 音声認識の一時停止
        if pause_stt and self.faststt and self.faststt.stt:
            await self.faststt.stt.pause()

        # 音声再生
        result = await self.tts.play_voice(text, interrupt_event=interrupt_event)

        # 音声認識の再開
        if restart_stt and self.faststt and self.faststt.stt:
            await self.faststt.stt.start_new_session()

        return result

    async def utter_after_listening(
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
            await self.initialize()

        if not self._running:
            self.start()

        # 発話終了を待機
        while not self.faststt.is_speech_ended:
            await asyncio.sleep(0.01)

        # 処理の重複を防ぐためのロック取得
        async with self.processing_lock:
            # 割り込みイベントをクリア
            self.interrupt_event.clear()

            # 相槌処理
            backchannel_text = self.llm_backchannel.previous_user_input

            # 相槌キューが空なら少し待機
            while self.llm_backchannel.answer_queue.empty():
                await asyncio.sleep(0.01)

            # 相槌取得
            backchannel_answer = await self.llm_backchannel.answer_queue.get()
            logging.info(
                f"[LLM Backchannel]: {backchannel_text} -> {backchannel_answer}"
            )

            # 相槌再生前に音声認識を一時停止
            await self.faststt.stt.pause()

            # 本回答の生成に必要な情報を準備
            user_input = self.faststt.stt.text
            additional_messages = None
            if backchannel_answer:
                additional_messages = [("assistant", backchannel_answer)]

            # 本回答の生成を開始
            if self.llm_answer.should_generate(user_input):
                self.llm_answer.start_generate_task(
                    user_input, additional_messages=additional_messages
                )

            # 相槌の再生
            await self.play_voice(
                backchannel_answer,
                pause_stt=False,  # すでに一時停止している
                restart_stt=False,  # 応答後に再開
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
                await self.play_voice(
                    detail_answer,
                    pause_stt=False,
                    restart_stt=False,
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
                await self.play_voice(
                    additional_utterance,
                    pause_stt=False,
                    restart_stt=False,
                    interrupt_event=self.interrupt_event,
                )

                if not (self.interrupt_event.is_set() and self.allow_interrupt):
                    uttered_additional_utterance = additional_utterance

            # 会話履歴の作成
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
                await self.llm_backchannel.add_history(new_history)
                await self.llm_answer.add_history(new_history)

            # 状態のリセット
            await self.llm_backchannel.reset()
            await self.llm_answer.reset()
            await self.faststt.stt.start_new_session()
            self.interrupt_event.clear()

            return new_history
