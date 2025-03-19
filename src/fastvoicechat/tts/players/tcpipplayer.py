"""
TCPIPPlayerは以下の仕様のサーバーと通信することを想定しています：

サーバープロトコル仕様:
1. データフォーマット
   - すべてのメッセージは [size(4bytes)] + [data(size bytes)] の形式
   - sizeはbig endianの32bit整数

2. コマンド
   a) play_wav
      - クライアント -> サーバー:
        1. [size(4bytes)] + ["play_wav"(UTF-8)]
        2. [size(4bytes)] + [WAVデータ(bytes)]
      - サーバーの動作:
        - 受信したWAVデータを再生

   b) stop_wav
      - クライアント -> サーバー:
        1. [size(4bytes)] + ["stop_wav"(UTF-8)]
      - サーバーの動作:
        - 現在再生中のWAVデータの再生を停止

3. エラー処理
   - 接続エラー: クライアントは再接続を試みる
   - 不正なデータ: サーバーは該当の接続を切断
"""

import asyncio
import io
import socket
import wave
from typing import Optional

import numpy as np

from fastvoicechat.tts.players.base import BasePlayer


class TCPIPPlayer(BasePlayer):
    """TCP/IPを使用した非同期プレイヤー（クライアント）"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 12345,
        interval: float = 0.01,
        **kwargs,
    ):
        super().__init__(interval)
        self.host = host
        self.port = port
        self._play_start_time: Optional[float] = None
        self._play_duration: Optional[float] = None

    def __connect(self) -> socket.socket:
        """サーバーに接続する"""
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.connect((self.host, self.port))
        return conn

    def __send(self, conn: socket.socket, data: bytes) -> None:
        """データを送信する"""
        size = len(data)
        conn.send(size.to_bytes(4, byteorder="big"))
        conn.send(data)

    def __close(self, conn: socket.socket) -> None:
        """接続を閉じる"""
        try:
            conn.shutdown(1)
            conn.close()
        except:
            pass

    async def aplay_voice(
        self, content: bytes, interrupt_event: Optional[asyncio.Event] = None
    ) -> bool:
        """
        音声データをサーバーに送信する

        Args:
            content: WAV音声のバイト列
            interrupt_event: 再生を中断するためのイベント

        Returns:
            bool: 正常終了したかどうか（Falseなら中断された）
        """
        try:
            # サーバーに接続して音声データを送信
            print("DEBUG: サーバーに接続して音声データを送信")
            conn = self.__connect()
            self.__send(conn, b"play_wav")  # コマンドを送信
            self.__send(conn, content)  # WAVデータを送信
            self.__close(conn)

            # WAVデータの長さを取得して、その時間分待機
            print("DEBUG: WAVデータの長さを取得")
            wav_io = io.BytesIO(content)
            with wave.open(wav_io, "rb") as wf:
                duration = wf.getnframes() / wf.getframerate()
            print(f"DEBUG: duration = {duration}")

            # 再生開始時刻と再生時間を記録
            self._play_start_time = asyncio.get_event_loop().time()
            self._play_duration = duration
            print(
                "DEBUG: 再生開始時刻と再生時間を記録",
                self._play_start_time,
                self._play_duration,
            )

            # 再生時間分待機（中断可能）
            while (asyncio.get_event_loop().time() - self._play_start_time) < duration:
                print(
                    f"DEBUG: 再生時間 = {asyncio.get_event_loop().time() - self._play_start_time}"
                )
                if interrupt_event is not None and interrupt_event.is_set():
                    print("DEBUG: 中断イベントを検出")
                    await self.astop()
                    return False
                await asyncio.sleep(self.interval)
                print("DEBUG: 待機中...")

            # 再生終了
            print("DEBUG: 再生終了")
            self._play_start_time = None
            self._play_duration = None
            return True

        except Exception as e:
            print(f"Error in play_voice: {e}")
            self._play_start_time = None
            self._play_duration = None
            return False

    async def astop(self) -> None:
        """再生を停止する"""
        try:
            conn = self.__connect()
            self.__send(conn, b"stop_wav")
            self.__close(conn)
            self._play_start_time = None
            self._play_duration = None
        except Exception as e:
            print(f"Error in stop: {e}")

    @property
    def is_playing(self) -> bool:
        """再生中かどうかを返す"""
        if self._play_start_time is None or self._play_duration is None:
            return False
        current_time = asyncio.get_event_loop().time()
        return (current_time - self._play_start_time) < self._play_duration


if __name__ == "__main__":

    async def main():
        # テスト用のTCPIPPlayerを作成
        player = TCPIPPlayer(host="localhost", port=12346)

        # テスト用の音声データを生成
        def create_test_wav_data(duration_sec=0.5, sample_rate=44100, frequency=440.0):
            t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), False)
            samples = np.sin(2 * np.pi * frequency * t) * 32767
            audio_data = samples.astype(np.int16)
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(audio_data.tobytes())
            buffer.seek(0)
            return buffer.read()

        try:
            # テスト音声を再生
            test_wav_data = create_test_wav_data()
            await player.aplay_voice(test_wav_data)
            await asyncio.sleep(0.3)  # 少し待機
            await player.astop()  # 停止をテスト
        except Exception as e:
            print(f"Error in main: {e}")

    asyncio.run(main())
