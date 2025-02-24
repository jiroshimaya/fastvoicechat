# fastchat  
openai api、google sttを使用して、マルチスレッド処理により高速な音声対話を実行するデモプログラム。

# 使い方
## 準備

- voicevoxを起動する

```sh
git clone [url]
# 必要ならpipの前に仮想環境作成
cd fastchat
# 環境変数ファイルをコピーして、voicevox、openai api、google stt用のjsonの情報を記入
cp .env_sample .env
```

## 起動

```sh
uv run main.py [--disable_interrupt]
```

PCに話しかけて返答が再生されれば成功。

## プログラムから使う

FastChat.utter_after_listening()メソッドにより高速リプライを使用できます。
並列処理の関係上[^multiprocess]、`__main__`スコープ内で実行する必要があることに注意してください。

[^multiprocess]: おそらくmultiprocessingを使用していることが原因で、multiprocessingは必須ではないので、機会があれば修正します

```Python
from fastchat import FastChat

def main():
    fastchat = FastChat(speaker="pc", 
                        allow_interrupt= False,
                        )
    fastchat.start()
    print("喋って!")
    fastchat.utter_after_listening()
    print("終了")
    fastchat.stop()
    fastchat.join()

if __name__ == "__main__":
    main()
```

