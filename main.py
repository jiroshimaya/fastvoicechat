import asyncio
import logging
import os
import sys

import dotenv

from fastvoicechat.asyncfastvoicechat import AsyncFastVoiceChat

dotenv.load_dotenv()


async def async_main():
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
    parser.add_argument(
        "--use-async",
        "-a",
        action="store_true",
        default=False,
        help="Use async version of FastVoiceChat",
    )
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.loglevel.upper(), None))

    if args.use_async:
        logging.debug("Creating AsyncFastVoiceChat instance...")
        fastvoicechat = AsyncFastVoiceChat(
            speaker=args.speaker,
            allow_interrupt=not args.disable_interrupt,
            voicevox_host=os.getenv("VOICEVOX_HOST", "localhost:50021"),
        )

        # 初期化と開始
        await fastvoicechat.initialize()
        fastvoicechat.start()

        print("Press Ctrl+C to stop.")
        try:
            while True:
                await fastvoicechat.utter_after_listening()
        except KeyboardInterrupt:
            print("KeyboardInterrupt detected. Stopping...")
            await fastvoicechat.stop()
            await fastvoicechat.join()

    else:
        # 既存の同期版 FastVoiceChat を使用
        from fastvoicechat import FastVoiceChat

        logging.debug("Creating FastVoiceChat instance...")
        fastvoicechat = FastVoiceChat(
            speaker=args.speaker,
            allow_interrupt=not args.disable_interrupt,
            voicevox_host=os.getenv("VOICEVOX_HOST", "localhost:50021"),
        )

        fastvoicechat.start()
        print("Press Ctrl+C to stop.")
        try:
            while True:
                fastvoicechat.utter_after_listening()
        except KeyboardInterrupt:
            print("KeyboardInterrupt detected. Stopping...")
            fastvoicechat.stop()
            fastvoicechat.join()

    print("Main thread exiting.")
    return 0


def main():
    try:
        exit_code = asyncio.run(async_main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("KeyboardInterrupt detected in main(). Exiting...")
        sys.exit(1)


if __name__ == "__main__":
    main()
