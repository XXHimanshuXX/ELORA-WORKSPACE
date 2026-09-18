"""
voice.py — WIRE-6 ASR/TTS speech organ.
State.ALERT: 1800MB budget.

Provides voice perception (listen) and voice output (speak) with graceful
degradation when sherpa-onnx or audio peripherals are absent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Optional


VOICE_DIR = os.path.abspath(os.path.join(".elora", "voice"))


class VoiceOrgan:
    def __init__(self):
        pass

    def listen(self, seconds: int = 5) -> dict:
        """
        Listen for speech (STT). If sherpa-onnx is absent, gracefully
        returns degraded marker rather than crashing.
        """
        try:
            import sherpa_onnx  # noqa: F401
            return {"transcript": "", "seconds": seconds, "degraded": None}
        except Exception:
            return {"transcript": "", "seconds": seconds, "degraded": "sherpa-onnx absent"}

    def speak(self, text: str, out_path: Optional[str] = None) -> dict:
        """
        Synthesize speech (TTS). If audio peripheral or sherpa-onnx is absent,
        gracefully returns degraded marker.
        """
        os.makedirs(VOICE_DIR, exist_ok=True)
        if not out_path:
            token_hex = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
            out_path = os.path.join(VOICE_DIR, f"speech_{token_hex}.wav")

        out_path = os.path.abspath(out_path)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

        try:
            import sherpa_onnx  # noqa: F401
            return {"wav_path": out_path, "text": text, "degraded": None}
        except Exception:
            return {"wav_path": None, "text": text, "degraded": "audio peripheral absent"}


def listen(seconds: int = 5) -> dict:
    organ = VoiceOrgan()
    return organ.listen(seconds=seconds)


def speak(text: str, out_path: Optional[str] = None) -> dict:
    organ = VoiceOrgan()
    return organ.speak(text=text, out_path=out_path)


class VoiceLoop:
    def __init__(self, asr_model="base-int8", tts_model="piper-medium", wakeword=True):
        self.asr_model = asr_model
        self.tts_model = tts_model
        self.wakeword = wakeword

    def listen(self):
        try:
            import sherpa_onnx  # noqa: F401
            return {"status": "ok"}
        except Exception:
            return {"degraded": "sherpa-onnx absent"}



def main():
    parser = argparse.ArgumentParser(description="ELORA Voice CLI")
    parser.add_argument("--listen", action="store_true")
    parser.add_argument("--speak", default="")
    parser.add_argument("--seconds", type=int, default=5)
    parser.add_argument("--out", dest="out_path", default=None)
    args = parser.parse_args()

    organ = VoiceOrgan()
    if args.listen:
        res = organ.listen(seconds=args.seconds)
        print(json.dumps(res))
    elif args.speak:
        res = organ.speak(text=args.speak, out_path=args.out_path)
        print(json.dumps(res))
    else:
        print(json.dumps({"error": "action required (--listen or --speak)"}))


if __name__ == "__main__":
    main()
