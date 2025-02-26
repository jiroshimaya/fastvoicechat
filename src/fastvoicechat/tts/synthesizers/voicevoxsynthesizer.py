import asyncio

import aiohttp

from fastvoicechat.tts.base import BaseSynthesizer


class VoiceVoxSynthesizer(BaseSynthesizer):
    """VoiceVoxのHTTP APIを非同期で扱うクラス"""

    def __init__(self, host="http://localhost:50021"):
        self.host = host if host.startswith("http") else f"http://{host}"
        self._session = None
        self._speakers_cache = None
        self._connection_retries = 3
        self._retry_delay = 1.0  # 初回リトライ待機時間（秒）

    async def _get_session(self) -> aiohttp.ClientSession:
        """HTTPセッションを取得（必要なら作成）"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                connector=aiohttp.TCPConnector(limit=5),
            )
        return self._session

    async def synthesize(self, text: str, speaker_id: int = 0) -> bytes:
        """
        テキストからVoiceVox APIを使って音声を合成

        Args:
            text: 読み上げるテキスト
            speaker_id: 話者ID

        Returns:
            bytes: WAV形式の音声データ
        """
        session = await self._get_session()

        retry_count = 0
        while retry_count <= self._connection_retries:
            try:
                # 音声合成クエリを作成
                params = {"text": text, "speaker": speaker_id}
                async with session.post(
                    f"{self.host}/audio_query", params=params
                ) as response:
                    response.raise_for_status()
                    query_data = await response.json()

                # 音声合成を実行
                headers = {"Content-Type": "application/json"}
                async with session.post(
                    f"{self.host}/synthesis",
                    headers=headers,
                    params=params,
                    json=query_data,
                ) as response:
                    response.raise_for_status()
                    return await response.read()

            except (aiohttp.ClientError, asyncio.TimeoutError):
                if retry_count >= self._connection_retries:
                    raise
                retry_count += 1
                # 指数バックオフ
                await asyncio.sleep(self._retry_delay * (2 ** (retry_count - 1)))
                continue
        return b""

    async def get_available_speakers(self) -> list:
        """
        利用可能な話者リストを取得する

        Returns:
            list: 話者情報のリスト
        """
        # キャッシュがあればそれを返す
        if self._speakers_cache is not None:
            return self._speakers_cache

        session = await self._get_session()

        retry_count = 0
        while retry_count <= self._connection_retries:
            try:
                async with session.get(f"{self.host}/speakers") as response:
                    response.raise_for_status()
                    speakers = await response.json()
                    self._speakers_cache = speakers
                    return speakers
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if retry_count >= self._connection_retries:
                    raise
                retry_count += 1
                await asyncio.sleep(self._retry_delay * (2 ** (retry_count - 1)))
                continue
        return []

    async def close(self):
        """HTTPセッションを閉じる"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            self._session = None
