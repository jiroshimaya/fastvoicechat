import logging
import queue
import sys
import threading
import time
import traceback
from multiprocessing import Manager
from typing import Callable

import pyaudio
import webrtcvad
from google.cloud import speech

RATE = 16000
# 最小単位を10msとする(10ms * 16000Hz = 160サンプル、16bit=2バイトなので320バイト)
BASE_CHUNK = 160
STT_CHUNK = 1600
VAD_CHUNK = 160

BYTE_PER_SAMPLE = 2  # 16bit


class GoogleSpeechRecognition(threading.Thread):
    def __init__(
        self,
        *,
        audio_queue: queue.Queue | None = None,
        callback: Callable[[dict], None] | None = None,
        chunk: int = STT_CHUNK,
        rate: int = RATE,
        single_utterance: bool = False,
        max_buffer_size: int | None = None,
        stop_event: threading.Event | None = None,
    ):
        super().__init__(daemon=False)
        self.audio_queue = audio_queue or queue.Queue()
        self.callback = callback
        self.rate = rate
        self.chunk = chunk
        self.chunk_bytes = chunk * BYTE_PER_SAMPLE
        self.max_buffer_size = max_buffer_size or chunk * 10
        self.single_utterance = single_utterance
        self.stop_event = stop_event or threading.Event()
        self.reset_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()  # setされるとwait()が即座に返る
        self._state = Manager().dict()

    def create_streaming_config(self) -> speech.StreamingRecognitionConfig:
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=self.rate,
            language_code="ja-JP",
        )
        streaming_config = speech.StreamingRecognitionConfig(
            config=config,
            interim_results=True,
            single_utterance=self.single_utterance,
        )
        return streaming_config

    def run(self):
        while not self.stop_event.is_set():
            self.reset_event.clear()
            # if not self.pause_event.is_set():
            #    logging.debug("pause_event is set")
            self.pause_event.wait()
            client = speech.SpeechClient()
            streaming_config = self.create_streaming_config()

            def request_generator():
                buffer = b""
                while not self.stop_event.is_set() and not self.reset_event.is_set():
                    try:
                        data = self.audio_queue.get(timeout=0.1)
                    except queue.Empty:
                        continue

                    # if data == "RESET":
                    #    # Signal that we want to end this streaming session
                    #    self.reset_event.set()
                    #    break

                    buffer += data
                    # Prevent buffer from growing too large
                    if len(buffer) > self.max_buffer_size:
                        buffer = buffer[-self.max_buffer_size :]
                    if len(buffer) >= self.chunk_bytes:
                        yield speech.StreamingRecognizeRequest(
                            audio_content=buffer[: self.chunk_bytes]
                        )
                        buffer = buffer[self.chunk_bytes :]
                return  # End of generator

            responses = client.streaming_recognize(
                config=streaming_config, requests=request_generator()
            )

            try:
                for response in responses:
                    if self.stop_event.is_set() or self.reset_event.is_set():
                        break
                    if not response.results:
                        continue
                    result = response.results[0]
                    if result.alternatives:
                        transcript = result.alternatives[0].transcript
                        result_type = "final" if result.is_final else "interim"
                        result_dict = {"type": result_type, "text": transcript}
                        self._update_state(result_dict)
                        if self.callback:
                            self.callback(result_dict)
                        if result.is_final and self.single_utterance:
                            # Single utterance mode: once we get a final result, end the session
                            break
            except Exception:
                logging.error("[STT] Traceback: %s", traceback.format_exc())
            # Loop back and start a new session if reset was requested and not stopping
        # End run method when stop_event is set

    def start_new_session(self):
        # Instead of stopping the thread, just send a reset command through the queue.
        self.clear_audio_queue()
        self.reset_event.set()
        self.pause_event.set()
        self.reset_state()

    def stop(self):
        self.stop_event.set()
        # Optionally, put some data in the queue to ensure request_generator stops.
        self.reset_event.set()

    def pause(self):
        self.pause_event.clear()
        self.reset_event.set()

    def clear_audio_queue(self):
        with self.audio_queue.mutex:
            self.audio_queue.queue.clear()

    def resume(self):
        self.clear_audio_queue()
        self.pause_event.set()

    def _update_state(self, result_dict):
        previous_text = self.text
        text = result_dict.get("text", "")
        delta = text[len(previous_text) :]
        self._state["delta"] = delta
        self._state["result"] = result_dict

    def reset_state(self):
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


class GoogleWebRTCVAD(threading.Thread):
    def __init__(
        self,
        *,
        audio_queue: queue.Queue | None = None,
        callback: Callable[[bool], None] | None = None,
        rate: int = RATE,
        chunk: int = VAD_CHUNK,
        max_buffer_size: int | None = None,
        stop_event: threading.Event | None = None,
    ):
        super().__init__(daemon=False)
        self.audio_queue = audio_queue or queue.Queue()
        self.callback = callback
        self.rate = rate
        self.chunk = chunk
        self.chunk_bytes = chunk * BYTE_PER_SAMPLE
        self.max_buffer_size = max_buffer_size or chunk * 10
        self.vad = webrtcvad.Vad()
        self.vad.set_mode(3)
        self.chunk_bytes = self.chunk * BYTE_PER_SAMPLE
        self.stop_event = stop_event or threading.Event()
        self._state = Manager().dict()

    def run(self):
        # VADは10msごと（1フレーム）で判定
        buffer = b""
        try:
            while not self.stop_event.is_set():
                try:
                    base_frame = self.audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                buffer += base_frame
                # バッファが大きくなりすぎないようにクリア
                if len(buffer) > self.max_buffer_size:
                    buffer = buffer[-self.max_buffer_size :]
                if len(buffer) >= self.chunk_bytes:
                    is_speech = self.vad.is_speech(
                        buffer[: self.chunk_bytes], self.rate
                    )
                    # update local vad state
                    self._update_state(is_speech)
                    if self.callback:
                        self.callback(is_speech)
                    buffer = buffer[self.chunk_bytes :]
        except Exception:
            logging.error("[VAD] Traceback: %s", traceback.format_exc())

    def stop(self):
        self.stop_event.set()

    @property
    def is_speech(self) -> bool:
        return self._state.get("is_speech", False)

    @property
    def silence_count(self) -> int:
        return self._state.get("silence_count", 0)

    @property
    def speech_count(self) -> int:
        return self._state.get("speech_count", 0)

    def _update_state(self, is_speech) -> None:
        self._state["is_speech"] = is_speech
        if is_speech:
            self._state["silence_count"] = 0
            self._state["speech_count"] = self._state.get("speech_count", 0) + 1
        else:
            self._state["silence_count"] = self._state.get("silence_count", 0) + 1
            self._state["speech_count"] = 0

    def reset_state(self):
        self._state.clear()


class AudioCapture(threading.Thread):
    def __init__(self, queue_list: list[queue.Queue], rate: int = RATE):
        super().__init__(daemon=False)
        self.queue_list = queue_list
        self.rate = rate
        self.audio_interface = pyaudio.PyAudio()

        self.read_frame_count = BASE_CHUNK * BYTE_PER_SAMPLE
        self.audio_stream = self.audio_interface.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.rate,
            input=True,
            frames_per_buffer=self.read_frame_count,
        )
        self.stop_event = threading.Event()

    def run(self):
        try:
            while not self.stop_event.is_set():
                audio_data = self.audio_stream.read(
                    self.read_frame_count, exception_on_overflow=False
                )
                for queue in self.queue_list:
                    queue.put(audio_data)
        except Exception:
            logging.error("[AudioCapture] Traceback: %s", traceback.format_exc())
        finally:
            self.audio_stream.stop_stream()
            self.audio_stream.close()
            self.audio_interface.terminate()

    def stop(self):
        self.stop_event.set()


class FastSTT:
    def __init__(
        self,
        *,
        stt_callback: Callable[[dict], None] | None = None,
        vad_callback: Callable[[bool], None] | None = None,
    ):
        self.stt = GoogleSpeechRecognition(callback=stt_callback)
        self.vad = GoogleWebRTCVAD(callback=vad_callback)
        self.audio_capture = AudioCapture([self.stt.audio_queue, self.vad.audio_queue])

    def start(self):
        self.audio_capture.start()
        self.stt.start()
        self.vad.start()

    def stop(self):
        self.audio_capture.stop()
        self.stt.stop()
        self.vad.stop()

    def join(self):
        self.audio_capture.join()
        self.stt.join()
        self.vad.join()

    @property
    def is_speech_ended(self) -> bool:
        return self.vad.silence_count > 10 and self.stt.text

    @property
    def is_speech_started(self) -> bool:
        return self.vad.speech_count > 10


def main():
    logging.basicConfig(level=logging.DEBUG)

    def stt_callback(result):
        logging.info("[STT Callback]: %s", result)

    def vad_callback(is_speech):
        logging.info("[VAD Callback]: %s", is_speech)

    logging.debug("Creating FastSTT instance...")
    faststt = FastSTT(stt_callback=stt_callback, vad_callback=vad_callback)
    faststt.start()

    logging.info("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        logging.info("KeyboardInterrupt detected. Stopping...")
        faststt.stop()

    faststt.join()

    logging.info("Main thread exiting.")
    sys.exit(0)


if __name__ == "__main__":
    main()
