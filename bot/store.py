"""Runtime cache of the catalog the bot shows.

The bot reads this on every catalog tap; the admin panel drops it on every
write, so an edit in the browser is live on the next message — no restart, no
cache to synchronize between processes.
"""

from . import db

_catalog: dict[str, list[dict]] | None = None
_settings: dict[str, str] | None = None


async def catalog(gender: str) -> list[dict]:
    global _catalog
    if _catalog is None:
        _catalog = {g: await db.list_templates(gender=g, only_enabled=True)
                    for g in ("female", "male")}
    return _catalog.get(gender, [])


async def settings() -> dict:
    global _settings
    if _settings is None:
        _settings = await db.get_settings()
    return _settings


def invalidate():
    global _catalog, _settings
    _catalog = None
    _settings = None
