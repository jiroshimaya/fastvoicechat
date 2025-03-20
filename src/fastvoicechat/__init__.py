"""FastVoiceChat - 音声チャットを簡単に実装するためのPythonライブラリ

このモジュールは以下の主要なクラスと関数を提供します：

- :class:`fastvoicechat.fvchat.FastVoiceChat`: メインの音声チャットクラス
- :class:`fastvoicechat.base.CallbackLoop`: コールバックループの基本クラス
- :func:`fastvoicechat.factory.create_fastvoicechat`: FastVoiceChatインスタンスを作成するファクトリ関数
"""

from .base import CallbackLoop
from .factory import create_fastvoicechat
from .fvchat import FastVoiceChat

# パブリックAPIとして公開するクラスと関数
__all__ = ["FastVoiceChat", "CallbackLoop", "create_fastvoicechat"]
