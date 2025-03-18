import asyncio
import logging

import dotenv

from fastvoicechat import create_fastvoicechat

dotenv.load_dotenv()


def main():
    import argparse

    parser = argparse.ArgumentParser()
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

    # TTSインスタンスを作成
    logging.debug("Creating AsyncFastVoiceChat instance...")
    fastvoicechat = create_fastvoicechat()

    print("Press Ctrl+C to stop.")
    try:
        while True:
            fastvoicechat.utter_after_listening()
    except asyncio.CancelledError:
        print("Task cancelled. Stopping...")
    finally:
        fastvoicechat.stop()

    print("Main thread exiting.")
    return 0


if __name__ == "__main__":
    main()
