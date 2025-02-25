import asyncio
import io
import wave
from abc import ABC, abstractmethod
from typing import Literal, Optional

import aiohttp
import simpleaudio


async def calculate_duration(content: bytes) -> float:
    """音声データの再生時間を計算する"""
    wav_io = io.BytesIO(content)
    with wave.open(wav_io, "rb") as wf:
        frame_rate = wf.getframerate()
        duration = wf.getnframes() / float(frame_rate)
    return duration


class AsyncBasePlayer(ABC):
    """音声再生の抽象基底クラス"""

    def __init__(self, interval: float = 0.01):
        self.interval = interval

    async def play_voice(
        self, content: bytes, interrupt_event: Optional[asyncio.Event] = None
    ) -> bool:
        """
        音声再生を行い、終了または中断まで待機する

        Args:
            content: WAV音声のバイト列
            interrupt_event: 再生を中断するためのイベント

        Returns:
            bool: 正常終了したかどうか（Falseなら中断された）
        """
        await self._play_voice(content)

        if interrupt_event:
            while self.is_playing:
                if interrupt_event.is_set():
                    await self.stop()
                    return False
                await asyncio.sleep(self.interval)
        else:
            while self.is_playing:
                await asyncio.sleep(self.interval)

        return True

    @abstractmethod
    async def _play_voice(self, content: bytes):
        """音声再生の実装（サブクラスで実装）"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """再生停止の実装（サブクラスで実装）"""
        pass

    @property
    @abstractmethod
    def is_playing(self) -> bool:
        """再生中かどうかを返す"""
        return False


class AsyncSimpleAudioPlayer(AsyncBasePlayer):
    """simpleaudioを使った非同期プレイヤー"""

    def __init__(self, interval: float = 0.01):
        super().__init__(interval)
        self.play_obj: Optional[simpleaudio.PlayObject] = None
        self._playing = False

    async def _play_voice(self, content: bytes):
        """音声を再生する"""
        loop = asyncio.get_running_loop()

        def _play():
            wav_io = io.BytesIO(content)
            with wave.open(wav_io, "rb") as wf:
                audio_data = wf.readframes(wf.getnframes())
                return simpleaudio.play_buffer(
                    audio_data, wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
                )

        # 同期的なsimpleaudioの処理を別スレッドで実行
        self.play_obj = await loop.run_in_executor(None, _play)
        self._playing = True

        # 再生終了を監視する非同期タスク
        async def monitor_playback():
            while self.play_obj and self.play_obj.is_playing():
                await asyncio.sleep(self.interval)
            self._playing = False

        asyncio.create_task(monitor_playback())

    @property
    def is_playing(self) -> bool:
        """再生中かどうかを返す"""
        if self.play_obj is None:
            return False
        else:
            return self._playing and self.play_obj.is_playing()

    async def stop(self) -> None:
        """再生を停止する"""
        play_obj = (
            self.play_obj
        )  # pylanceの警告を消すため。self.play_objのままだと警告になってしまう。
        if play_obj:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: play_obj.stop())
            self.play_obj = None
            self._playing = False


class AsyncVoiceVoxClient:
    """VoiceVoxのHTTP APIを非同期で扱うクラス"""

    def __init__(self, host="http://localhost:50021"):
        self.host = host if host.startswith("http") else f"http://{host}"
        self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """HTTPセッションを取得（必要なら作成）"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def get_content(self, text: str, speaker: int = 0) -> bytes:
        """
        テキストからVoiceVox APIを使って音声を生成

        Args:
            text: 読み上げるテキスト
            speaker: 話者ID

        Returns:
            bytes: WAV形式の音声データ
        """
        session = await self._get_session()

        # 音声合成クエリを作成
        params = {"text": text, "speaker": speaker}
        async with session.post(f"{self.host}/audio_query", params=params) as response:
            response.raise_for_status()
            query_data = await response.json()

        # 音声合成を実行
        headers = {"Content-Type": "application/json"}
        async with session.post(
            f"{self.host}/synthesis", headers=headers, params=params, json=query_data
        ) as response:
            response.raise_for_status()
            return await response.read()

    async def close(self):
        """HTTPセッションを閉じる"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None


class AsyncTTS:
    """非同期テキスト読み上げクラス"""

    def __init__(
        self,
        voicevox_host: str = "localhost:50021",
        speaker: Literal["pc"] = "pc",
    ):
        self.voicevox_client = AsyncVoiceVoxClient(voicevox_host)
        self.speaker = speaker
        self.text = ""

        # スピーカー設定
        if speaker == "pc":
            self.player = AsyncSimpleAudioPlayer()
        else:
            # 他のプレイヤー実装をここに追加
            self.player = AsyncSimpleAudioPlayer()

    async def play_voice(
        self, text: str, interrupt_event: Optional[asyncio.Event] = None
    ) -> bool:
        """
        テキストを音声に変換して再生

        Args:
            text: 読み上げるテキスト
            interrupt_event: 再生を中断するためのイベント

        Returns:
            bool: 正常終了したかどうか（Falseなら中断された）
        """
        if not text:
            return True

        self.text = text
        content = await self.voicevox_client.get_content(text)
        result = await self.player.play_voice(content, interrupt_event)
        await self.stop()
        return result

    async def stop(self) -> None:
        """再生を停止"""
        await self.player.stop()
        self.text = ""

    @property
    def is_playing(self) -> bool:
        """再生中かどうか"""
        return self.player.is_playing

    async def close(self):
        """リソースの解放"""
        await self.voicevox_client.close()


# 使用例
async def main():
    # 環境変数からVoiceVoxのホストを取得
    import os

    from dotenv import load_dotenv

    load_dotenv()

    voicevox_host = os.getenv("VOICEVOX_HOST", "localhost:50021")
    tts = AsyncTTS(voicevox_host)

    print("音声再生を開始します...")
    await tts.play_voice("こんにちは、世界！これは非同期TTSのテストです。")
    print("音声再生が完了しました")

    # リソースの解放
    await tts.close()


if __name__ == "__main__":
    asyncio.run(main())
