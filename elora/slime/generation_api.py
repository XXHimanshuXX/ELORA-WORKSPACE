"""
generation_api.py — the slime creates.

API-FIRST law: for platforms you pay for, use the API (more reliable,
never challenged, survives UI changes). Browser mimicry of consumer
web apps is a fallback, not the design.

Supported:
  - Gemini API (paid/free tier): text, images
  - Any OpenAI-compatible endpoint
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.request
from typing import Optional


class GenerationOrgan:
    """Creates images/media via API subscriptions or local models."""

    def __init__(self, vault=None, ledger=None):
        self.vault = vault
        self.ledger = ledger
        self._secrets_dir = ".elora/secrets"
        os.makedirs(self._secrets_dir, exist_ok=True)

    def generate_image(self, prompt: str, out_path: str, provider: str = "gemini") -> dict:
        key = self._get_key("gemini_api_key")
        if not key:
            return {"error": "no gemini key in .elora/secrets/gemini_api_key"}

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={key}"
        payload = {
            "contents": [{
                "parts": [{"text": f"Generate an image: {prompt}"}]
            }]
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read().decode("utf-8"))

            for part in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
                if "inline_data" in part:
                    img_data = base64.b64decode(part["inline_data"]["data"])
                    parent = os.path.dirname(os.path.abspath(out_path))
                    if parent:
                        os.makedirs(parent, exist_ok=True)
                    with open(out_path, "wb") as f:
                        f.write(img_data)
                    if self.ledger is not None:
                        self.ledger.append(
                            organ="generation",
                            kind="image_generated",
                            message=prompt[:100],
                            payload={"path": out_path, "bytes": len(img_data)},
                        )
                    return {"generated": True, "path": out_path}
            return {"error": "no image in response"}
        except Exception as e:
            return {"error": str(e)}

    def _get_key(self, name: str) -> Optional[str]:
        path = os.path.join(self._secrets_dir, name)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:
                return None
        return None


def main():
    parser = argparse.ArgumentParser(description="ELORA Generation Organ")
    parser.add_argument("--prompt", required=True, help="Image prompt")
    parser.add_argument("--out", required=True, help="Output image file path")
    args = parser.parse_args()

    gen = GenerationOrgan()
    res = gen.generate_image(args.prompt, args.out)
    print(json.dumps(res))


if __name__ == "__main__":
    main()
