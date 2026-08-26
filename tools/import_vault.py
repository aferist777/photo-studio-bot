"""Import photoshoot templates from the Obsidian vault into the catalog.

    python -m tools.import_vault

Rerun it whenever the vault changes: only the touched templates move. A prompt
edited in the admin panel is kept and flagged rather than overwritten, so the
vault stays the source without being a bulldozer.

This step only lands the free text. `tools.structure` then splits it into the
field set the panel edits.
"""

import asyncio
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageOps                                    # noqa: E402

from bot import db                                                 # noqa: E402
from bot.config import PREVIEW_DIR, VAULT_DIR, VAULT_GENDERS       # noqa: E402

WIKILINK = re.compile(r"!\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}

# The vault templates each carry their own way of saying "keep the face from my
# photo". That job belongs to the face prefix in settings now, so the phrasings
# are stripped here — replaced rather than deleted where a bare cut would leave
# a hole in the sentence.
#
# Inline cuts leave a space behind on purpose: the vault has "of a me(use my
# image...)relaxing on a yacht" with no spaces around the parenthetical, and a
# bare deletion welds the neighbours into "merelaxing". _tidy collapses the
# doubles afterwards.
FACE_DIRECTIVES: list[tuple[str, str]] = [
    (r"(?im)^[ \t]*use\s+\d{1,3}\s*%\s+upload(?:ed)?\s+face[ \t]*$", ""),
    (r"(?i)\(\s*use\s+(?:the\s+uploaded\s+picture|my\s+image|my\s+photo)[^)]*\)", " "),
    (r"(?i)face[- ]reference\s+aligned\s*\([^)]*\)\s*\.?", " "),
    (r"(?i)face\s+alignment:\s*\d{1,3}\s*%\s*accurate\s+to\s+reference\s*\.?", " "),
    (r"(?i),?\s*uploaded\s+face\s+alignment\s*\([^)]*\)", " "),
    (r"(?i)face\s+with\s+the\s+face\s+from\s+the\s+uploaded\s+image,?\s*"
     r"keeping\s+the\s+facial\s+features\s+exactly\s+the\s+same\s*\.?", " "),
    (r"(?i)\d{1,3}\s*%\s*unaltered\s+real\s+faces?\s+from\s+uploaded\s+photos,?\s*", " "),
    (r"(?i)without\s+changing\s+my\s+face\s+or\s+hairstyle,\s*", " "),
    (r"(?i)\[\s*my\s+photo\s*\]", "the person"),
    (r"(?i)\bthe\s+uploaded\s+person\b", "the person"),
    (r"(?i)\ba\s+me\b", "a person"),
]

def _tidy(text: str) -> str:
    """Close the gaps a stripped directive leaves behind."""
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:])\s*(?=[,.;:])", "", text)
    text = re.sub(r"\.\s*\.", ".", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [ln.strip() for ln in text.splitlines()]
    text = "\n".join(ln for ln in lines if ln).strip(" ,.;:\n")
    # A cut leading clause ("Without changing my face, create an ...") leaves the
    # prompt starting mid-sentence.
    return text[:1].upper() + text[1:]


def _strip_directives(text: str) -> tuple[str, bool]:
    cleaned = text
    for pattern, replacement in FACE_DIRECTIVES:
        cleaned = re.sub(pattern, replacement, cleaned)
    return _tidy(cleaned), cleaned != text


def _index_images() -> dict[str, Path]:
    """Wikilinks carry a bare file name, so build one name -> path map."""
    found: dict[str, Path] = {}
    for root in (VAULT_DIR, VAULT_DIR.parent):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() in IMAGE_EXT:
                found.setdefault(path.name, path)
    return found


def _make_preview(src: Path, source_key: str) -> str:
    """Shrink a vault screenshot into a catalog thumbnail; return its file name."""
    name = hashlib.sha1(source_key.encode("utf-8")).hexdigest()[:12] + ".webp"
    dst = PREVIEW_DIR / name
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((640, 640))
        im.save(dst, "WEBP", quality=82, method=5)
    return name


def _parse_note(path: Path, gender: str, images: dict[str, Path]) -> dict:
    raw = path.read_text(encoding="utf-8")
    links = WIKILINK.findall(raw)
    body = WIKILINK.sub("", raw)
    prompt, cleaned = _strip_directives(body)

    source_key = f"{gender}/{path.stem}"
    preview = ""
    for link in links:
        src = images.get(Path(link).name)
        if src:
            preview = _make_preview(src, source_key)
            break

    return {
        "source_key": source_key,
        "gender": gender,
        "title": path.stem,
        "prompt": prompt,
        "preview": preview,
        "cleaned": cleaned,
        "missing_preview": bool(links) and not preview,
    }


# -------------------------------------------------------------------- run

async def run() -> dict:
    report = {
        "added": 0, "updated": 0, "unchanged": 0, "cleaned": 0,
        "conflicts": [], "no_preview": [], "orphans": [], "errors": [],
    }
    if not VAULT_DIR.exists():
        report["errors"].append(f"vault folder not found: {VAULT_DIR}")
        return report

    images = _index_images()
    notes: list[dict] = []
    for folder, gender in VAULT_GENDERS.items():
        directory = VAULT_DIR / folder
        if not directory.exists():
            report["errors"].append(f"missing folder: {directory}")
            continue
        for path in sorted(directory.glob("*.md")):
            try:
                notes.append(_parse_note(path, gender, images))
            except Exception as exc:                    # noqa: BLE001 - one bad note, keep going
                report["errors"].append(f"{path.name}: {exc}")

    notes = [n for n in notes if n["prompt"]]
    for note in notes:
        if note["cleaned"]:
            report["cleaned"] += 1
        if note["missing_preview"]:
            report["no_preview"].append(note["title"])
        outcome = await db.upsert_from_vault(
            note["source_key"], note["gender"], note["title"], note["prompt"], note["preview"]
        )
        if outcome == "conflict":
            report["conflicts"].append(note["title"])
            report["updated"] += 1
        else:
            report[outcome] += 1

    seen = {n["source_key"] for n in notes}
    report["orphans"] = sorted(await db.vault_keys() - seen)
    return report


def summary(report: dict) -> str:
    parts = [
        f"{report['added']} added", f"{report['updated']} updated",
        f"{report['unchanged']} unchanged",
    ]
    if report["conflicts"]:
        parts.append(f"{len(report['conflicts'])} kept your edits")
    if report["no_preview"]:
        parts.append(f"{len(report['no_preview'])} without preview")
    if report["orphans"]:
        parts.append(f"{len(report['orphans'])} gone from the vault")
    if report["errors"]:
        parts.append(f"{len(report['errors'])} errors")
    return ", ".join(parts)


async def import_if_empty():
    """First launch on a fresh database pulls the vault in automatically."""
    if await db.list_templates():
        return
    report = await run()
    print(f"  Vault import: {summary(report)}")
    for line in report["errors"]:
        print(f"  ! {line}")


async def _main():
    await db.init()
    report = await run()
    print(summary(report))
    for key in ("conflicts", "no_preview", "orphans", "errors"):
        for line in report[key]:
            print(f"  {key}: {line}")


if __name__ == "__main__":
    asyncio.run(_main())
