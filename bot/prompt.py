"""Template fields and the prose they turn into.

A template is stored as fields so every one of them has the same shape and a
new one is a form to fill rather than an essay to write. The model still gets a
paragraph: Google's guidance for nano-banana asks for a described scene, not a
list of keys. Both forms are kept, so the two can be compared on real output —
see the prompt_format setting.
"""

import json
from typing import NamedTuple


class Field(NamedTuple):
    key: str
    label: str
    hint: str
    placeholder: str


FIELDS = [
    Field("shot", "Shot", "Genre and framing",
          "cinematic editorial portrait, waist-up, 1960s Vogue aesthetic"),
    Field("subject", "Subject", "Who is in frame. No facial features — those come from the selfie",
          "an elegant woman"),
    Field("wardrobe", "Wardrobe", "Clothes, jewellery, accessories",
          "a deep crimson velvet dress with a sculpted off-shoulder neckline"),
    Field("styling", "Styling", "Hair and make-up as shape and finish, never colour",
          "hair in voluminous waves, natural makeup"),
    Field("location", "Location", "Place and background, written with its preposition",
          "on a sunlit Parisian rooftop, the Eiffel Tower soft behind her"),
    Field("pose", "Pose", "Pose, action, expression",
          "leaning back on the seat, barefoot, calm and confident"),
    Field("lighting", "Lighting", "Light, time of day, palette",
          "golden hour light in amber and peach tones, creamy bokeh"),
    Field("camera", "Camera", "Camera, lens, aperture, grain",
          "a Hasselblad with an 85mm lens at f/2.8"),
    Field("extras", "Extras", "Props and anything that fits nowhere else",
          "a glass of red wine resting beside her"),
    Field("negative", "Negative", "What must not appear",
          "CGI, cartoon shading, plastic skin, over-smoothing"),
]

KEYS = [f.key for f in FIELDS]

# Most values are written as self-contained clauses and drop straight in; these
# three read better with a connective in front.
JOINERS = {
    "wardrobe": "wearing {v}",
    "camera": "shot on {v}",
    "negative": "avoid {v}",
}
# Order the sentences appear in. shot and subject share the opening sentence.
# Location lands before pose so the scene is set before the person acts in it.
TAIL = ["wardrobe", "styling", "location", "pose", "lighting", "camera", "extras", "negative"]


def loads(raw: str) -> dict:
    """Fields as stored on the row; empty or broken JSON reads as no fields."""
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: str(data.get(k) or "").strip() for k in KEYS}


def is_structured(raw: str) -> bool:
    """loads() always returns the full key set, so an empty dict is never the tell."""
    return any(loads(raw).values())


def dumps(fields: dict) -> str:
    clean = {k: str(fields.get(k) or "").strip() for k in KEYS}
    return json.dumps(clean, ensure_ascii=False) if any(clean.values()) else ""


def _sentence(text: str) -> str:
    text = text.strip().rstrip(" .,;")
    return text[:1].upper() + text[1:] + "."


def render(fields: dict) -> str:
    """Fields -> one paragraph for the image model."""
    value = lambda key: (fields.get(key) or "").strip().rstrip(" .,;")

    parts = []
    shot, subject = value("shot"), value("subject")
    if shot and subject:
        parts.append(f"{shot} of {subject}")
    elif shot or subject:
        parts.append(shot or subject)

    for key in TAIL:
        text = value(key)
        if text:
            parts.append(JOINERS.get(key, "{v}").format(v=text))

    return " ".join(_sentence(p) for p in parts)


def assemble(template: dict, settings: dict) -> str:
    """The exact string that goes to the image model."""
    fields = loads(template.get("fields", ""))
    if settings.get("prompt_format") == "json" and any(fields.values()):
        body = json.dumps({k: v for k, v in fields.items() if v}, ensure_ascii=False, indent=2)
    else:
        body = template.get("prompt") or render(fields)
    prefix = (settings.get("face_prefix") or "").strip()
    return f"{prefix}\n\n{body}".strip()
