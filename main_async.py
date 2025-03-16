import asyncio
import logging
import os

import dotenv

from fastvoicechat.fastvoicechat import FastVoiceChat
from fastvoicechat.tts import TTS
from fastvoicechat.tts.players import SimpleAudioPlayer
from fastvoicechat.tts.synthesizers import VoiceVoxSynthesizer

dotenv.load_dotenv()


async def amain():
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
    tts = TTS(
        synthesizer=VoiceVoxSynthesizer(
            host=os.getenv("VOICEVOX_HOST", "localhost:50021")
        ),
        player=SimpleAudioPlayer(),
    )

    logging.debug("Creating AsyncFastVoiceChat instance...")
    fastvoicechat = FastVoiceChat(
        tts=tts,
        allow_interrupt=args.allow_interrupt,
    )

    print("Press Ctrl+C to stop.")
    try:
        while True:
            await fastvoicechat.autter_after_listening()
    except asyncio.CancelledError:
        print("Task cancelled. Stopping...")
    finally:
        await fastvoicechat.astop()

    print("Main thread exiting.")
    return 0


if __name__ == "__main__":
    asyncio.run(amain())
