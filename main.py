import asyncio
import logging
import os

import dotenv

from fastvoicechat.fastvoicechat import FastVoiceChat

dotenv.load_dotenv()


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--speaker", "-s", type=str, default="pc", choices=["pc"])
    parser.add_argument("--allow-interrupt", "-a", action="store_true", default=False)
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
        allow_interrupt=args.allow_interrupt,
        voicevox_host=os.getenv("VOICEVOX_HOST", "localhost:50021"),
    )

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
