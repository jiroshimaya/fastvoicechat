import logging
import threading
import time
from typing import Literal

from fastvoicechat.thread.base import CallbackLoop
from fastvoicechat.thread.llm import LLM
from fastvoicechat.thread.stt import FastSTT
from fastvoicechat.thread.tts import TTS
from fastvoicechat.voicevox import VoiceVoxClient

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
        self.speaker = speaker
        self.allow_interrupt = allow_interrupt

        self.faststt: FastSTT
        self.llm_backchannel: LLM
        self.llm_answer: LLM
        self.voicevox_client: VoiceVoxClient
        self.tts: TTS
        self.interrupt_event: threading.Event = threading.Event()
        self.interruption_observer: CallbackLoop

        self.backchannel_system_prompt = backchannel_system_prompt
        self.answer_system_prompt = answer_system_prompt
        self.backchannel_model = backchannel_model
        self.answer_model = answer_model

        logging.debug("Initializing FastChat...")

        def stt_callback(result: dict):
            user_input = result.get("text", "")
            print(f"[STT]: {user_input}")
            if self.llm_backchannel.should_generate(user_input):
                print(f"[STT]: generation start: {user_input}")
                self.llm_backchannel.start_generate_thread(user_input)
            # TTSが再生中で、ユーザが新たな発話(STT入力)を検知したらTTSを停止
            # if tts.is_playing and stt.delta:
            #    interrupt_event.set()  # 割り込みセット
            #    print("[TTS]: stop due to user interruption")

        def interruption_observer_callback():
            # print(f"[Observer]: {vad.speech_count}, {tts.is_playing}")
            previous_result = self.interruption_observer.get("previous_result")
            interrupted = self.faststt.is_speech_started and self.tts.is_playing
            self.interruption_observer.set("previous_result", interrupted)
            if interrupted:
                if self.allow_interrupt:
                    self.interrupt_event.set()
                    if not previous_result:
                        print("[Observer]: interruption detected. ")
                else:
                    if not previous_result:
                        print("[Observer]: interruption detected. but not allowed.")

        logging.debug("Setting up FastSTT...")
        self.faststt = FastSTT(stt_callback=stt_callback)

        logging.debug("Setting up CallbackLoop for interruption observer...")
        self.interruption_observer = CallbackLoop(
            callback=interruption_observer_callback,
            interval=0.01,
            name="InterruptionObserver",
        )

        logging.debug("Initializing LLM for backchannel and answer...")
        self.llm_backchannel = LLM(
            system_prompt=self.backchannel_system_prompt,
            model=self.backchannel_model,
            separator="、、。！？!?",
        )
        self.llm_answer = LLM(
            system_prompt=self.answer_system_prompt, model=self.answer_model
        )

        logging.debug("Initializing TTS...")
        self.tts = TTS(speaker=self.speaker, voicevox_host=voicevox_host)

    def play_voice(
        self,
        text: str,
        pause_stt: bool = True,
        restart_stt: bool = True,
        interrupt_event: threading.Event | None = None,
    ):
        if pause_stt:
            self.faststt.stt.pause()
        self.tts.play_voice(text, interrupt_event=interrupt_event)
        if restart_stt:
            self.faststt.stt.start_new_session()

    def utter_after_listening(
        self, *, add_history: bool = True, additional_utterance: str = ""
    ) -> list[tuple[str, str]]:
        wait_time = 0.01
        while not self.faststt.is_speech_ended:
            time.sleep(wait_time)

        # 新たな返答生成前にイベントをクリア
        self.interrupt_event.clear()

        backchannel_text = self.llm_backchannel.previous_user_input
        backchannel_queue = self.llm_backchannel.answer_queue

        while backchannel_queue.empty():
            time.sleep(wait_time)

        backchannel_answer = backchannel_queue.get()

        def generate_answer_with_backchannel():
            user_input = self.faststt.stt.text
            additional_messages = None
            if backchannel_answer:
                additional_messages = [("assistant", backchannel_answer)]
            if self.llm_answer.should_generate(user_input):
                self.llm_answer.start_generate_thread(
                    user_input, additional_messages=additional_messages
                )

        print(f"[LLM Backchannel]: {backchannel_text} -> {backchannel_answer}")
        self.faststt.stt.pause()
        llm_answer_loop = CallbackLoop(
            callback=generate_answer_with_backchannel, interval=0.1
        )
        llm_answer_loop.start()

        self.tts.play_voice(backchannel_answer)
        # タイムアウト付きでllm_answerが生成され始めるのを待機する
        timeout = 2  # タイムアウト時間（秒）
        start_time = time.time()
        while self.llm_answer.answer_queue.empty():
            if time.time() - start_time > timeout:
                # print("[LLM Answer]: タイムアウトしました。")
                break
            time.sleep(0.1)
        # time.sleep(1)
        # time.sleep(2)
        self.interrupt_event.clear()
        detail_answer = ""
        detail_full_answer = ""
        while not self.llm_answer.answer_queue.empty():
            if self.interrupt_event.is_set() and self.allow_interrupt:
                # 割り込みがあった場合は即時終了（ここでdetail_answerが残っていても無視するなど必要）
                print("[LLM Answer]: Interrupted during answer synthesis.")
                break

            detail_answer = self.llm_answer.answer_queue.get()
            if detail_answer == "NA":
                print(
                    f"[LLM Answer]: {self.llm_answer.previous_user_input} -> {backchannel_answer} -> {detail_answer}"
                )
                break
            print(
                f"[LLM Answer]: {self.llm_answer.previous_user_input} -> {backchannel_answer} -> {detail_answer}"
            )
            self.tts.play_voice(detail_answer, interrupt_event=self.interrupt_event)
            if self.interrupt_event.is_set() and self.allow_interrupt:
                print("[TTS]: stop due to user interruption")
                # 再生中にユーザ割り込みがあれば中断
                break
            detail_full_answer += detail_answer

        llm_answer_loop.stop()
        llm_answer_loop.join()

        uttered_additional_utterance = ""
        if additional_utterance:
            self.tts.play_voice(
                additional_utterance, interrupt_event=self.interrupt_event
            )
            if self.interrupt_event.is_set() and self.allow_interrupt:
                pass
            else:
                uttered_additional_utterance = additional_utterance

        previous_user_input = self.llm_answer.previous_user_input
        new_history = [
            ("user", previous_user_input),
            ("assistant", backchannel_answer),
        ]
        if detail_full_answer:
            new_history.append(("assistant", detail_full_answer))
        if uttered_additional_utterance:
            new_history.append(("assistant", uttered_additional_utterance))
        if add_history:
            self.llm_backchannel.add_history(new_history)
            self.llm_answer.add_history(new_history)

        self.llm_backchannel.reset()
        self.llm_answer.reset()
        self.faststt.stt.start_new_session()
        self.interrupt_event.clear()

        return new_history

    def start(self):
        logging.debug("Starting FastChat components...")
        self.faststt.start()
        self.interruption_observer.start()

    def stop(self):
        logging.debug("Stopping FastChat components...")
        self.faststt.stop()
        self.interruption_observer.stop()
        self.llm_backchannel.stop_all()
        self.llm_answer.stop_all()

    def join(self):
        logging.debug("Joining FastChat components...")
        self.faststt.join()
        self.llm_backchannel.join_all()
        self.llm_answer.join_all()
        self.interruption_observer.join()
