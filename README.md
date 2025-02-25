# fastchat  
openai api、google sttを使用して、マルチスレッド処理により高速な音声対話を実行するデモプログラム。

# 使い方
## 環境
以下で動作確認済み。windowsやubuntu、M1以外のmacでは正しく動作しない可能性があります。特にthreadやaudio関係の処理がOS依存性が強そうです。

- M1 MacbookAir 
- python 3.11

## 準備

- voicevoxを起動する

```sh
git clone [url]
# 必要ならpipの前に仮想環境作成
cd fastvoicechat
# 環境変数ファイルをコピーして、voicevox、openai api、google stt用のjsonの情報を記入
cp .env_sample .env
```

## 起動

```sh
uv run main.py [--disable_interrupt] [--use-async]
```

PCに話しかけて返答が再生されれば成功。

## プログラムから使う
### マルチスレッド方式
FastVoiceChat.utter_after_listening()メソッドにより高速リプライを使用できます。
並列処理の関係上[^multiprocess]、`__main__`スコープ内で実行する必要があることに注意してください。

[^multiprocess]: おそらくmultiprocessingを使用していることが原因で、multiprocessingは必須ではないので、機会があれば修正します

```Python
from fastvoicechat import FastVoiceChat

def main():
    fastvoicechat = FastChat(allow_interrupt= False)
    fastvoicechat.start()
    print("喋って!")
    fastvoicechat.utter_after_listening()
    print("終了")
    fastvoicechat.stop()
    fastvoicechat.join()

if __name__ == "__main__":
    main()
```

## 非同期方式(experimental[^experimental])

asyncioを使用した非同期方式も利用可能です。
こちらの方式ではasync/awaitを使用して処理を行います。
[^experimetal]: コード生成（threadからasyncへの置き換え）にClaude 3.7 Sonnetを使用しました。E2Eの動作確認のみ実施しており、コードの詳細は未確認です。将来的にはthreadよりもasyncのほうが好ましいのではと思っています。


```Python
import asyncio
from fastvoicechat import AsyncFastVoiceChat

async def main():
    fastvoicechat = AsyncFastVoiceChat(allow_interrupt=False)
    await fastvoicechat.start()
    print("喋って!")
    await fastvoicechat.utter_after_listening()
    print("終了")
    await fastvoicechat.stop()

if __name__ == "__main__":
    asyncio.run(main())
```
