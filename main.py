import asyncio
import logging
import os
import signal
import threading
import time

import dotenv

from fastvoicechat.fastvoicechat import FastVoiceChat

dotenv.load_dotenv()


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--speaker", "-s", type=str, default="pc", choices=["pc", "robot", "winsound"]
    )
    parser.add_argument("--disable-interrupt", "-d", action="store_true", default=False)
    parser.add_argument(
        "--loglevel",
        "-l",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level",
    )
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.loglevel.upper(), None))

    logging.debug("Creating AsyncFastVoiceChat instance...")
    fastvoicechat = FastVoiceChat(
        speaker=args.speaker,
        allow_interrupt=not args.disable_interrupt,
        voicevox_host=os.getenv("VOICEVOX_HOST", "localhost:50021"),
    )

    # 終了フラグと強制終了フラグ
    exit_flag = False
    force_exit = False
    last_sigint_time = 0

    # シグナルハンドラを設定
    def signal_handler(sig, frame):
        nonlocal exit_flag, force_exit, last_sigint_time
        current_time = time.time()

        # 2秒以内に2回Ctrl+Cが押された場合は強制終了
        if current_time - last_sigint_time < 2:
            print("\nForce exiting...")
            force_exit = True
            os._exit(1)  # 強制終了にはos._exitを使用

        last_sigint_time = current_time
        print(
            "\nCtrl+C detected. Stopping gracefully... (Press Ctrl+C again to force exit)"
        )
        # フラグを設定するだけで、実際の停止処理はメインループで行う
        exit_flag = True

    # Ctrl+C (SIGINT) のハンドラを登録
    signal.signal(signal.SIGINT, signal_handler)

    # 監視スレッドを作成して、定期的にフラグをチェック
    def watchdog_thread():
        nonlocal exit_flag, force_exit
        while not exit_flag and not force_exit:
            time.sleep(0.5)  # 500ミリ秒ごとにチェック

        # 終了フラグが立っていたら、5秒後に強制終了
        if exit_flag and not force_exit:
            time.sleep(5)
            if not force_exit:  # まだ終了していなければ
                print("\nWatchdog: Graceful shutdown taking too long, forcing exit...")
                os._exit(2)  # 強制終了

    # 監視スレッドを開始
    watchdog = threading.Thread(target=watchdog_thread, daemon=True)
    watchdog.start()

    print("Press Ctrl+C to stop.")
    try:
        while not exit_flag and not force_exit:
            try:
                # タイムアウト付きでutter_after_listeningを呼び出す
                # これにより、黙っているときでもCtrl+Cのチェックが行われる
                with_timeout = asyncio.run_coroutine_threadsafe(
                    asyncio.wait_for(
                        fastvoicechat.autter_after_listening(),
                        timeout=1.0,  # 1秒のタイムアウト
                    ),
                    asyncio.get_event_loop_policy().get_event_loop(),
                )

                try:
                    # タイムアウト付きで結果を待機
                    with_timeout.result(timeout=1.5)  # 少し余裕を持たせる
                except asyncio.TimeoutError:
                    # タイムアウトしても問題ない（次のループでフラグをチェック）
                    if exit_flag or force_exit:
                        break
                except Exception as e:
                    if "asyncio.CancelledError" in str(e):
                        # キャンセルされた場合は無視
                        pass
                    else:
                        logging.error(f"Error in utter_after_listening: {e}")

                # 終了フラグをチェック
                if exit_flag or force_exit:
                    break

            except Exception as e:
                logging.error(f"Error in main loop: {e}")
                # エラーが発生しても継続する
                time.sleep(0.5)

                # 終了フラグをチェック
                if exit_flag or force_exit:
                    break
    except asyncio.CancelledError:
        print("Task cancelled. Stopping...")
    except KeyboardInterrupt:
        # signal_handlerで処理されるため、ここには到達しないはず
        print("KeyboardInterrupt caught in main try block")
        exit_flag = True
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
    finally:
        if not force_exit:
            # 終了処理
            print("Cleaning up resources...")
            try:
                # タイムアウト付きで停止処理を実行
                shutdown_task = asyncio.ensure_future(
                    asyncio.wait_for(fastvoicechat.astop(), timeout=5.0)
                )

                try:
                    # 新しいイベントループを作成して実行
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(shutdown_task)
                except asyncio.TimeoutError:
                    print("Shutdown timed out after 5 seconds, forcing exit")
                except Exception as e:
                    logging.error(f"Error during shutdown: {e}")
                finally:
                    if loop and not loop.is_closed():
                        loop.close()

                print("Main thread exiting.")
            except Exception as e:
                logging.error(f"Error during shutdown: {e}")
                print("Failed to clean up resources, forcing exit")

    return 0


if __name__ == "__main__":
    main()
