import asyncio
import logging
import os

import dotenv

from fastvoicechat.fvchat import create_fastvoicechat

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

    # TTSインスタンスを作成
    logging.debug("Creating AsyncFastVoiceChat instance...")
    fastvoicechat = create_fastvoicechat(
        tts_kwargs={
            "synthesizer_type": os.getenv("SYNTHESIZER_TYPE", "voicevox"),
            "synthesizer_kwargs": {
                "host": os.getenv("VOICEVOX_HOST", "http://localhost:50021")
            },
            "player_type": os.getenv("PLAYER_TYPE", "simpleaudio"),
        },
        stt_kwargs={
            "recognition_type": os.getenv("RECOGNITION_TYPE", "googlespeech"),
            # "recognition_kwargs": {
            #    "model_path": "model",
            # },
            "vad_type": os.getenv("VAD_TYPE", "webrtcvad"),
        },
        allow_interrupt=args.allow_interrupt,
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
