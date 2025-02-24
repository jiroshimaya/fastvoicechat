import queue
import threading
import time
from dataclasses import dataclass
from multiprocessing import Manager
from typing import Callable, Generator

from openai import OpenAI


@dataclass
class ThreadInfo:
    thread: threading.Thread
    stop_event: threading.Event
    start_time: float
    user_input: str
    additional_messages: list[tuple[str, str]]


class LLM:
    """LLMをスレッドで並列実行する"""

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        system_prompt: str = "",
        separator: str = "。！？!?",
    ):
        self.model = model
        self.system_prompt = system_prompt
        self.client: OpenAI = OpenAI()
        self._state = Manager().dict()
        self.answer_queue = queue.Queue()
        self.threads: list[ThreadInfo] = []
        self.separator = separator

    def should_generate(self, user_input: str) -> bool:
        if not user_input:
            return False

        if user_input and not self.threads:
            return True

        latest_thread = self.threads[-1]
        if latest_thread.thread.is_alive() and latest_thread.user_input == user_input:
            return False

        previous_user_input = self.previous_user_input
        if user_input == previous_user_input:
            return False

        return True

    def stop_old_threads(self, current_time: float):
        for thread_info in self.threads:
            if thread_info.start_time < current_time:
                thread_info.stop_event.set()

    def join_old_threads(self, current_time: float):
        for thread_info in self.threads:
            if thread_info.start_time < current_time:
                thread_info.thread.join()

    def cleanup_dead_threads(self):
        """終了したスレッドを削除する"""
        self.threads[:] = [
            thread_info for thread_info in self.threads if thread_info.thread.is_alive()
        ]

    def _generate(
        self,
        user_input: str,
        stop_event: threading.Event,
        additional_messages: list[tuple[str, str]],
    ) -> Generator[str, None, None]:
        # メッセージの準備
        messages_tuple = []
        if self.system_prompt:
            messages_tuple.append(("system", self.system_prompt))
        history = self.history
        if history:
            messages_tuple.extend(history)
        messages_tuple.append(("user", user_input))
        if additional_messages:
            messages_tuple.extend(additional_messages)
        messages = self.tuples_to_messages(messages_tuple)

        # APIリクエスト
        response = self.client.chat.completions.create(
            messages=messages,
            model=self.model,
            stream=True,
        )

        # レスポンス処理
        answer = ""
        for chunk in response:
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

    def generate(
        self,
        user_input: str,
        stop_event: threading.Event,
        start_time: float,
        additional_messages: list[tuple[str, str]] | None = None,
        progress_callback: Callable[[str], None] | None = None,
        completion_callback: Callable[[str], None] | None = None,
    ):
        if additional_messages is None:
            additional_messages = []
        response = self._generate(user_input, stop_event, additional_messages)

        is_first = True
        answer = ""
        for chunk in response:
            if stop_event.is_set():
                break
            if progress_callback:
                progress_callback(chunk)
            if is_first:
                self.stop_old_threads(start_time)
                self.join_old_threads(start_time)
                self.cleanup_dead_threads()
                self.previous_user_input = user_input
                while not self.answer_queue.empty():
                    self.answer_queue.get()
                is_first = False
            self.answer_queue.put(chunk)
            answer += chunk
        if completion_callback and not stop_event.is_set():
            completion_callback(answer)

    def start_generate_thread(
        self,
        user_input: str,
        *,
        additional_messages: list[tuple[str, str]] | None = None,
        progress_callback: Callable[[str], None] | None = None,
        completion_callback: Callable[[str], None] | None = None,
    ):
        stop_event = threading.Event()
        start_time = time.time()
        thread = threading.Thread(
            target=self.generate,
            args=(
                user_input,
                stop_event,
                start_time,
                additional_messages,
                progress_callback,
                completion_callback,
            ),
        )
        thread.start()
        if additional_messages is None:
            additional_messages = []
        thread_info = ThreadInfo(
            thread=thread,
            stop_event=stop_event,
            start_time=start_time,
            user_input=user_input,
            additional_messages=additional_messages,
        )
        self.threads.append(thread_info)

    @property
    def previous_user_input(self) -> str:
        return self._state.get("previous_user_input", "")

    @previous_user_input.setter
    def previous_user_input(self, value: str) -> None:
        self._state["previous_user_input"] = value

    @property
    def history(self) -> list[tuple[str, str]]:
        return self._state.get("history", [])

    def add_history(self, value: list[tuple[str, str]]) -> None:
        if "history" not in self._state:
            self._state["history"] = []
        self._state["history"] += value

    def tuples_to_messages(self, value: list[tuple[str, str]]) -> list:
        return [{"role": role, "content": content} for role, content in value]

    def stop_all(self):
        for thread_info in self.threads:
            thread_info.stop_event.set()

    def join_all(self):
        for thread_info in self.threads:
            thread_info.thread.join()

    def reset(self):
        self.stop_all()
        self.join_all()
        self.cleanup_dead_threads()

        self.previous_user_input = ""
        while not self.answer_queue.empty():
            self.answer_queue.get()


def main():
    import os
    import sys

    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from fastchat.thread.base import CallbackLoop
    from fastchat.thread.stt import (
        AudioCapture,
        GoogleSpeechRecognition,
        GoogleWebRTCVAD,
    )

    # from thread.llm import LLMThread

    stt: GoogleSpeechRecognition
    vad: GoogleWebRTCVAD
    audio_capture: AudioCapture
    llm_backchannel: LLM
    llm_answer: LLM

    def stt_callback(result: dict):
        nonlocal llm_backchannel
        user_input = result.get("text", "")
        if llm_backchannel.should_generate(user_input):
            print(f"[STT]: generation start: {user_input}")

            llm_backchannel.start_generate_thread(user_input)

    def vad_callback(is_speech: bool):
        nonlocal stt, vad, llm_backchannel, llm_answer
        # print(f"[VAD]: {is_speech}, {vad.silence_count}")
        if vad.silence_count < 10:
            return

        if not stt.text:
            return

        backchannel_text = llm_backchannel.previous_user_input
        backchannel_queue = llm_backchannel.answer_queue
        if backchannel_queue.empty():
            return

        backchannel_answer = backchannel_queue.get()

        def generate_answer_with_backchannel():
            nonlocal stt, llm_answer, backchannel_answer
            user_input = stt.text
            additional_messages = None
            if backchannel_answer:
                additional_messages = [("assistant", backchannel_answer)]
            if llm_answer.should_generate(user_input):
                llm_answer.start_generate_thread(
                    user_input, additional_messages=additional_messages
                )

        print(f"[LLM Backchannel]: {backchannel_text} -> {backchannel_answer}")
        llm_answer_loop = CallbackLoop(
            callback=generate_answer_with_backchannel, interval=0.1
        )
        llm_answer_loop.start()
        time.sleep(2)
        detail_answer = ""
        while not llm_answer.answer_queue.empty():
            detail_answer += llm_answer.answer_queue.get()
            print(f"[LLM Answer]: {llm_answer.previous_user_input} -> {detail_answer}")
            time.sleep(2)
        llm_answer_loop.stop()
        llm_answer_loop.join()

        previous_user_input = llm_backchannel.previous_user_input
        llm_backchannel.add_history(
            [
                ("user", previous_user_input),
                ("assistant", backchannel_answer),
                ("assistant", detail_answer),
            ]
        )
        llm_backchannel.reset()
        llm_answer.add_history(
            [
                ("user", previous_user_input),
                ("assistant", backchannel_answer),
                ("assistant", detail_answer),
            ]
        )
        llm_answer.reset()
        stt.start_new_session()

    stt = GoogleSpeechRecognition(callback=stt_callback)
    vad = GoogleWebRTCVAD(callback=vad_callback)
    audio_capture = AudioCapture([stt.audio_queue, vad.audio_queue])

    backchannel_system_prompt = (
        "対話履歴を踏まえて適切な相槌を生成してください。"
        "ユーザの発話は音声認識の途中である可能性があります。"
        "どのような相槌が適切か判断が難しい場合は「へー」「うーん」など無難な相槌を出力してください。"
    )
    llm_backchannel = LLM(system_prompt=backchannel_system_prompt, model="gpt-4o")
    llm_answer = LLM()

    audio_capture.start()
    stt.start()
    vad.start()
    print("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("KeyboardInterrupt detected. Stopping...")
        audio_capture.stop()
        stt.stop()
        vad.stop()
        llm_backchannel.stop_all()
        llm_answer.stop_all()

    audio_capture.join()
    stt.join()
    vad.join()
    llm_backchannel.join_all()
    llm_answer.join_all()

    print("Main thread exiting.")
    sys.exit(0)


if __name__ == "__main__":
    main()
