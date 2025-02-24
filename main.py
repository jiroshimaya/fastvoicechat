import logging
import os
import sys

import dotenv

from fastvoicechat import FastVoiceChat

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

    logging.debug("Creating FastChat instance...")

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
            # time.sleep(0.5)
    except KeyboardInterrupt:
        print("KeyboardInterrupt detected. Stopping...")
        fastvoicechat.stop()

    fastvoicechat.join()
    print("Main thread exiting.")
    sys.exit(0)


if __name__ == "__main__":
    main()
