"""Turn free-text template prompts into the fixed field set.

    python -m tools.structure          fill templates that have no fields yet
    python -m tools.structure --all    redo every template from its raw text

One Gemini pass per template does both jobs: it splits the text into fields and
repairs the OCR damage the vault screenshots carried. The raw text stays on the
row, so a bad parse is one click from being redone.
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot import db, gemini, prompt                                 # noqa: E402
from bot.config import KIE_API_KEY                                 # noqa: E402

SYSTEM = f"""\
You convert a free-text image prompt into fixed fields for a photoshoot template library.

Return a JSON object with exactly these keys: {", ".join(prompt.KEYS)}. Every value is a
string. Use an empty string when the source says nothing about that field.

Rules:
- Never invent detail the source does not state, and never drop detail it does state.
  Anything that fits no other field goes into extras.
- Repair OCR damage. The sources were copied out of screenshots, so words are welded
  together ("stylishblack", "leansback"), spaces after full stops are missing, and camera
  jargon is garbled — "under the scaffolding sky" and "creating an ultrasound serene
  details" are corruption, not intent. Fix them to the nearest sensible reading.
- The face comes from a separate reference photo, so `subject` must not describe the face
  at all: no eye colour, skin tone, face shape, freckles, age markers or hair colour. Keep
  only what a casting note would say — "an elegant woman", "a young man".
- Hair and make-up as shape and finish belong in `styling` ("voluminous waves", "natural
  makeup", "wind-swept"). Their colour never does.
- `camera` holds physical kit only — body, lens, aperture, film stock, grain — because it
  is rendered as "shot on ...". Leave it empty when the source names none. Optical effects
  such as bokeh, lens flare, HDR or vignetting go to `lighting`.
- The first line of the message gives the template's gender. If the source never names the
  subject's gender, take it from there: "a woman" or "a man".
- Drop every instruction aimed at the image model about using an uploaded photo, matching
  a face or reference accuracy. That is handled elsewhere.
- Drop aspect ratio and resolution statements. Those are global settings.
- Each value is a self-contained descriptive phrase that reads as its own sentence: no
  leading capital, no trailing period. Write `location` with its preposition, e.g.
  "on a sunlit Parisian rooftop, the Eiffel Tower soft behind her".
- Keep the original English wording wherever it is already good.

Reply with the JSON object and nothing else.\
"""


def _parse(reply: str) -> dict:
    data = gemini.as_json(reply)
    return {key: str(data.get(key) or "").strip() for key in prompt.KEYS}


async def run(only_missing: bool = True, ids: list[int] | None = None) -> dict:
    report = {"done": 0, "skipped": 0, "errors": []}
    if not KIE_API_KEY:
        report["errors"].append("KIE_API_KEY is empty — nothing to parse with")
        return report

    rows = await db.list_templates()
    if ids:
        rows = [r for r in rows if r["id"] in ids]
    if only_missing:
        rows = [r for r in rows if not prompt.is_structured(r["fields"])]
    rows = [r for r in rows if (r["source_prompt"] or r["prompt"] or "").strip()]

    gate = asyncio.Semaphore(6)

    async def one(row: dict):
        source = (row["source_prompt"] or row["prompt"]).strip()
        message = f"Template gender: {row['gender']}\n\n{source}"
        async with gate:
            try:
                fields = _parse(await asyncio.to_thread(gemini.ask, SYSTEM, message))
            except Exception as exc:                # noqa: BLE001 - network or bad JSON
                report["errors"].append(f"{row['title']}: {exc}")
                return
        # A parse that lost most of the text summarized instead of splitting.
        if len(" ".join(fields.values())) < len(source) * 0.45:
            report["errors"].append(f"{row['title']}: parse dropped too much, left as is")
            report["skipped"] += 1
            return
        await db.set_fields(row["id"], fields)
        report["done"] += 1

    await asyncio.gather(*(one(r) for r in rows))
    return report


def summary(report: dict) -> str:
    parts = [f"{report['done']} parsed"]
    if report["skipped"]:
        parts.append(f"{report['skipped']} skipped")
    if report["errors"]:
        parts.append(f"{len(report['errors'])} errors")
    return ", ".join(parts)


async def _main():
    await db.init()
    report = await run(only_missing="--all" not in sys.argv)
    print(summary(report))
    for line in report["errors"]:
        print(f"  ! {line}")


if __name__ == "__main__":
    asyncio.run(_main())
