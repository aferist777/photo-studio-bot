"""Minimal kie.ai Gemini client (stdlib only).

Text side only — the same OpenAI-compatible endpoint gop-tarot-bot uses. Image
generation talks to the jobs API and lives elsewhere.
"""

import json
import urllib.request

from .config import GEMINI_MODEL, GEMINI_URL, KIE_API_KEY


def ask(system: str, user: str, timeout: int = 120) -> str:
    payload = {
        "model": GEMINI_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    req = urllib.request.Request(
        GEMINI_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {KIE_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return (data["choices"][0]["message"]["content"] or "").strip()


def as_json(text: str) -> dict:
    """Parse a reply that should be a JSON object, fenced or not."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start:end + 1])
