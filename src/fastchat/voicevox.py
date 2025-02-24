import io
import json
import wave

import pyaudio
import requests
import simpleaudio


class VoiceVoxClient:
    def __init__(self, host="http://localhost:50021"):
        self.host = host

    def get_content(self, text: str, speaker: int = 0) -> bytes:
        params = (
            ("text", text),
            ("speaker", speaker),
        )
        response1 = requests.post(f"{self.host}/audio_query", params=params)
        headers = {
            "Content-Type": "application/json",
        }
        response2 = requests.post(
            f"{self.host}/synthesis",
            headers=headers,
            params=params,
            data=json.dumps(response1.json()),
        )

        return response2.content

    def generate_wav(self, text, speaker=0, filepath=None) -> tuple[bytes, float]:
        content = self.get_content(text, speaker)

        if filepath:
            with open(filepath, "wb") as f:
                f.write(content)

        wav_io = io.BytesIO(content)
        with wave.open(wav_io, "rb") as wf:
            frame_rate = wf.getframerate()
            duration = wf.getnframes() / float(frame_rate)

        return content, duration

    # pyaudioを使用して再生
    # 音声末尾にプツッというノイズが入るので、simpleaudioを使用したplay_voiceがおすすめ
    def play_voice_pyaudio(self, text, speaker=8) -> tuple[None, float]:
        content = self.get_content(text, speaker)

        # WAVデータをメモリ上で読み込み
        wav_io = io.BytesIO(content)

        with wave.open(wav_io, "rb") as wf:
            p = pyaudio.PyAudio()
            stream = p.open(
                format=p.get_format_from_width(wf.getsampwidth()),
                channels=wf.getnchannels(),
                rate=wf.getframerate(),
                output=True,
            )

            buffer_size = 1024
            data = wf.readframes(buffer_size)
            while data:
                stream.write(data)
                data = wf.readframes(buffer_size)

            stream.stop_stream()
            stream.close()
            # p.get_default_output_device_info()
            p.terminate()

            duration = wf.getnframes() / float(wf.getframerate())
            return None, duration

    def play_voice(
        self, text, speaker=8, *, wait=False
    ) -> tuple[simpleaudio.PlayObject, float]:
        content = self.get_content(text, speaker)

        # WAVデータをメモリ上で読み込み
        wav_io = io.BytesIO(content)

        with wave.open(wav_io, "rb") as wf:
            audio_data = wf.readframes(wf.getnframes())
            play_obj = simpleaudio.play_buffer(
                audio_data, wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
            )

            # 再生が終了するまで待機
            if wait:
                play_obj.wait_done()

            duration = wf.getnframes() / float(wf.getframerate())
            return play_obj, duration


if __name__ == "__main__":
    voicevox_client = VoiceVoxClient("jiro-FRONTIER.local:50021")
    voicevox_client.play_voice("こんにちはー、今日は来てくれてありがとうね", 8)

    # content, duration = voicevox_client.generate_wav("こんにちはー、今日は来てくれてありがとうね")
    # robotop.play_wav(config.robot_ip, config.robot_port, content)
    # voicevox_client.generate_wav2("こんにちはー、今日は来てくれてありがとうね", filepath="tmp.wav")
    # import os
    # os.system(f"afplay tmp.wav")
