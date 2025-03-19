import asyncio
import io
import socket
import wave
from typing import AsyncGenerator, Tuple

import numpy as np
import pytest
import pytest_asyncio

from fastvoicechat.tts.players.tcpipplayer import TCPIPPlayer


@pytest_asyncio.fixture
async def server() -> AsyncGenerator[
    Tuple[socket.socket, list[tuple[str, bytes]]], None
]:
    """テスト用のTCPサーバーを提供するフィクスチャ"""
    received_data: list[tuple[str, bytes]] = []
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("localhost", 12346))
    server_socket.listen(1)
    server_socket.settimeout(0.1)  # タイムアウトを1秒に延長

    async def handle_client():
        while True:
            try:
                print("DEBUG: サーバー: 接続待ち")
                client, _ = server_socket.accept()
                print("DEBUG: サーバー: 新しい接続を受け付け")
                # コマンドサイズを読み取り
                cmd_size = int.from_bytes(client.recv(4), byteorder="big")
                # コマンドを読み取り
                cmd = client.recv(cmd_size).decode("utf-8")
                print(f"DEBUG: サーバー: コマンド '{cmd}' を受信")

                if cmd == "stop_wav":
                    received_data.append((cmd, b""))
                    print("DEBUG: サーバー: stop_wavコマンドを処理")
                elif cmd == "play_wav":
                    # データサイズを読み取り
                    data_size = int.from_bytes(client.recv(4), byteorder="big")
                    print(f"DEBUG: サーバー: {data_size}バイトのデータを受信開始")
                    # データを読み取り
                    data = b""
                    while len(data) < data_size:
                        chunk = client.recv(min(4096, data_size - len(data)))
                        if not chunk:
                            break
                        data += chunk
                    received_data.append((cmd, data))
                    print("DEBUG: サーバー: play_wavコマンドを処理")

                client.close()
                print("DEBUG: サーバー: 接続を閉じました")
            except socket.timeout:
                # タイムアウトは正常なケース
                await asyncio.sleep(0.01)
            except Exception as e:
                print(f"DEBUG: サーバー: エラー発生 - {e}")
                await asyncio.sleep(0.01)

    server_task = asyncio.create_task(handle_client())

    try:
        yield server_socket, received_data
    finally:
        server_task.cancel()
        await asyncio.sleep(0.1)  # タスクのキャンセルを待つ
        server_socket.close()


def create_test_wav_data(duration_sec: float = 1.0) -> bytes:
    """テスト用のWAVデータを生成するフィクスチャ"""
    sample_rate = 44100
    frequency = 440.0
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


@pytest.mark.asyncio
@pytest.mark.timeout(5, method="thread")
async def test_play_voice(server: Tuple[socket.socket, list[tuple[str, bytes]]]):
    """音声送信のテスト"""
    print("1. テスト開始")
    server_socket, received_data = server
    print("2. サーバーフィクスチャ取得完了")
    player = TCPIPPlayer(host="localhost", port=12346)
    print("3. プレイヤー作成完了")

    # 音声データを送信
    print("4. 音声データ送信開始")
    test_wav_data = create_test_wav_data(0.5)
    result = await player.aplay_voice(test_wav_data)
    print("5. 音声データ送信完了")
    assert result is True

    # サーバーが受信したデータを確認
    print("6. sleep開始")
    await asyncio.sleep(0.02)  # 待機時間を短縮
    print("7. sleep完了")
    assert len(received_data) > 0
    print("8. データ受信確認完了")
    assert received_data[0][0] == "play_wav"
    assert received_data[0][1] == test_wav_data
    print("9. テスト完了")


@pytest.mark.asyncio
@pytest.mark.timeout(10, method="thread")
async def test_play_voice_with_interrupt(
    server: Tuple[socket.socket, list[tuple[str, bytes]]],
):
    """音声送信の中断テスト"""
    server_socket, received_data = server
    player = TCPIPPlayer(host="localhost", port=12346)

    # 中断イベントを作成
    interrupt_event = asyncio.Event()

    # 音声データを送信
    test_wav_data = create_test_wav_data(5)
    play_task = asyncio.create_task(player.aplay_voice(test_wav_data, interrupt_event))
    await asyncio.sleep(0)  # これがないとplay_taskが始まらない。理由は不明。

    # 中断イベントを設定（音声データ送信前）
    interrupt_event.set()

    # 再生が中断されたことを確認
    result = await play_task
    assert result is False

    # 停止コマンドが送信されたことを確認
    await asyncio.sleep(0.02)  # 待機時間を短縮
    assert len(received_data) >= 2
    assert received_data[0][0] == "play_wav"
    assert received_data[1][0] == "stop_wav"


@pytest.mark.asyncio
@pytest.mark.timeout(5, method="thread")
async def test_stop(server: Tuple[socket.socket, list[tuple[str, bytes]]]):
    """停止コマンドのテスト"""
    server_socket, received_data = server
    player = TCPIPPlayer(host="localhost", port=12346)

    # 停止コマンドを送信
    await player.astop()

    # 停止コマンドが送信されたことを確認
    await asyncio.sleep(0.02)  # 待機時間を短縮
    assert len(received_data) > 0
    assert received_data[0][0] == "stop_wav"


@pytest.mark.asyncio
@pytest.mark.timeout(5, method="thread")
async def test_is_playing(server: Tuple[socket.socket, list[tuple[str, bytes]]]):
    """is_playingプロパティのテスト"""
    server_socket, received_data = server
    player = TCPIPPlayer(host="localhost", port=12346)

    # 再生開始前はFalse
    assert player.is_playing is False

    # 再生開始
    test_wav_data = create_test_wav_data(0.5)
    play_task = asyncio.create_task(player.aplay_voice(test_wav_data))
    await asyncio.sleep(0.02)  # 待機時間を短縮

    # 再生中はTrue
    assert player.is_playing is True

    # 再生終了まで待つ
    await play_task
    await asyncio.sleep(0.02)  # 待機時間を短縮

    # 再生終了後はFalse
    assert player.is_playing is False


@pytest.mark.asyncio
async def test_is_playing_with_stop(
    server: Tuple[socket.socket, list[tuple[str, bytes]]],
):
    """is_playingプロパティの停止時の動作テスト"""
    server_socket, received_data = server
    player = TCPIPPlayer(host="localhost", port=12346)

    # 再生開始
    test_wav_data = create_test_wav_data(0.5)
    play_task = asyncio.create_task(player.aplay_voice(test_wav_data))
    await asyncio.sleep(0.02)  # 待機時間を短縮

    # 再生中はTrue
    assert player.is_playing is True

    # 停止
    await player.astop()
    await asyncio.sleep(0.02)  # 待機時間を短縮

    # 停止後はFalse
    assert player.is_playing is False
