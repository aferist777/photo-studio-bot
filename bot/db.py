"""SQLite layer for the photo studio bot.

The admin panel edits the same rows a running bot reads, so a prompt fixed in
the browser reaches the next generation without a restart.
"""

from contextlib import asynccontextmanager

import aiosqlite

from . import prompt
from .config import DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS templates(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_key TEXT UNIQUE,               -- 'female/НА ФОНЕ ПАРИЖА'; NULL for hand-made ones
  gender TEXT NOT NULL,                 -- female | male
  position INTEGER NOT NULL,
  is_enabled INTEGER DEFAULT 1,
  title TEXT NOT NULL,
  fields TEXT DEFAULT '',               -- JSON of bot/prompt.KEYS; source of truth once set
  prompt TEXT DEFAULT '',               -- what the bot sends: rendered from fields, or typed
  source_prompt TEXT DEFAULT '',        -- last text imported from the vault
  source_changed INTEGER DEFAULT 0,     -- vault moved while the panel copy was edited
  preview TEXT DEFAULT '',              -- file name inside assets/previews
  uses INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_templates_gender ON templates(gender, position);

CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS users(
  user_id INTEGER PRIMARY KEY,
  username TEXT DEFAULT '',
  first_name TEXT DEFAULT '',
  gender TEXT DEFAULT '',
  credits INTEGER DEFAULT 0,
  consent_at TEXT,                      -- set when the user agreed to face storage
  is_blocked INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS faces(
  user_id INTEGER NOT NULL,
  slot TEXT NOT NULL,                   -- front | side | closeup
  path TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (user_id, slot)
);

CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  template_id INTEGER,
  status TEXT DEFAULT 'queued',         -- queued | running | done | failed
  result_path TEXT DEFAULT '',
  error TEXT DEFAULT '',
  created_at TEXT DEFAULT (datetime('now')),
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(user_id, created_at);

CREATE TABLE IF NOT EXISTS payments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  charge_id TEXT UNIQUE,                -- Telegram provider charge id, blocks double credit
  stars INTEGER DEFAULT 0,
  credits INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now'))
);
"""

# Seeded once, then owned by the admin panel.
DEFAULT_SETTINGS = {
    # Prepended to every template prompt. Replaces the ad-hoc "use 100% upload
    # face" lines the vault templates carried, in one editable place.
    "face_prefix": (
        "Use the uploaded reference photos as the exact face of the person in this scene. "
        "Keep the facial features, bone structure, skin tone and hairline identical to the "
        "references — same person, no beautification, no age change, no reshaping. "
        "Photorealistic skin texture with visible pores. "
        "Take nothing else from the reference photos: clothing, pose, framing, background "
        "and lighting all come from the scene description below."
    ),
    "aspect_ratio": "3:4",
    "image_size": "2K",
    # prose | json — what actually goes to the model. Prose is what Google asks
    # for; json is here so the two can be compared on real generations.
    "prompt_format": "prose",
    "free_credits": "3",
    "credits_per_pack": "10",
    "pack_price_stars": "150",
}


@asynccontextmanager
async def _connect():
    conn = await aiosqlite.connect(DB_PATH)
    try:
        conn.row_factory = aiosqlite.Row
        yield conn
    finally:
        await conn.close()


async def _add_missing_columns(c):
    """CREATE TABLE IF NOT EXISTS skips databases made by an earlier schema."""
    added = {"templates": {"fields": "TEXT DEFAULT ''"}}
    for table, columns in added.items():
        cur = await c.execute(f"PRAGMA table_info({table})")
        have = {r[1] for r in await cur.fetchall()}
        for name, decl in columns.items():
            if name not in have:
                await c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


async def init():
    async with aiosqlite.connect(DB_PATH) as c:
        await c.executescript(SCHEMA)
        await _add_missing_columns(c)
        for key, value in DEFAULT_SETTINGS.items():
            await c.execute(
                "INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO NOTHING",
                (key, value),
            )
        await c.commit()


# -------------------------------------------------------------- templates

TEMPLATE_FIELDS = {"gender", "is_enabled", "title", "prompt", "preview"}


async def list_templates(gender: str | None = None, only_enabled: bool = False) -> list[dict]:
    sql = "SELECT * FROM templates WHERE 1=1"
    params: list = []
    if gender:
        sql += " AND gender=?"
        params.append(gender)
    if only_enabled:
        sql += " AND is_enabled=1 AND prompt<>''"
    sql += " ORDER BY position, id"
    async with _connect() as c:
        cur = await c.execute(sql, params)
        return [dict(r) for r in await cur.fetchall()]


async def get_template(template_id: int) -> dict | None:
    async with _connect() as c:
        cur = await c.execute("SELECT * FROM templates WHERE id=?", (template_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def create_template(gender: str, title: str, **fields) -> int:
    async with _connect() as c:
        cur = await c.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM templates WHERE gender=?", (gender,)
        )
        pos = (await cur.fetchone())[0]
        cur = await c.execute(
            "INSERT INTO templates(gender, position, title) VALUES(?,?,?)",
            (gender, pos, title),
        )
        template_id = cur.lastrowid
        await c.commit()
    if fields:
        await update_template(template_id, **fields)
    return template_id


async def update_template(template_id: int, **fields):
    payload = {k: v for k, v in fields.items() if k in TEMPLATE_FIELDS}
    if not payload:
        return
    sets = ", ".join(f"{k}=?" for k in payload)
    async with _connect() as c:
        await c.execute(
            f"UPDATE templates SET {sets} WHERE id=?", (*payload.values(), template_id)
        )
        await c.commit()


async def delete_template(template_id: int):
    async with _connect() as c:
        await c.execute("DELETE FROM templates WHERE id=?", (template_id,))
        await c.commit()


async def reorder_templates(gender: str, ordered_ids: list[int]):
    async with _connect() as c:
        for pos, tid in enumerate(ordered_ids, start=1):
            await c.execute(
                "UPDATE templates SET position=? WHERE id=? AND gender=?", (pos, tid, gender)
            )
        await c.commit()


async def set_fields(template_id: int, values: dict) -> str:
    """Merge field values in, re-render the prompt, return the new prose."""
    row = await get_template(template_id)
    if not row:
        return ""
    fields = {**prompt.loads(row["fields"]), **{k: v for k, v in values.items() if k in prompt.KEYS}}
    rendered = prompt.render(fields)
    async with _connect() as c:
        await c.execute(
            "UPDATE templates SET fields=?, prompt=? WHERE id=?",
            (prompt.dumps(fields), rendered, template_id),
        )
        await c.commit()
    return rendered


async def clear_fields(template_id: int):
    """Back to a plain typed prompt; the rendered text stays as the starting point."""
    async with _connect() as c:
        await c.execute("UPDATE templates SET fields='' WHERE id=?", (template_id,))
        await c.commit()


async def reset_to_source(template_id: int):
    """Drop panel edits and go back to the text the vault last supplied.

    Fields go with them: they were parsed out of the old text, so keeping them
    would leave the row describing something the prompt no longer says.
    """
    async with _connect() as c:
        await c.execute(
            "UPDATE templates SET prompt=source_prompt, fields='', source_changed=0 WHERE id=?",
            (template_id,),
        )
        await c.commit()


async def upsert_from_vault(
    source_key: str, gender: str, title: str, prompt: str, preview: str
) -> str:
    """Insert or refresh one vault template.

    Returns 'added', 'updated', 'conflict' or 'unchanged'. A prompt edited in
    the panel is never overwritten — the new vault text lands in source_prompt
    and the row is flagged, so the editor can offer the swap instead.
    """
    async with _connect() as c:
        cur = await c.execute("SELECT * FROM templates WHERE source_key=?", (source_key,))
        row = await cur.fetchone()

        if row is None:
            cur = await c.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM templates WHERE gender=?", (gender,)
            )
            pos = (await cur.fetchone())[0]
            await c.execute(
                "INSERT INTO templates(source_key, gender, position, title, prompt, "
                "source_prompt, preview) VALUES(?,?,?,?,?,?,?)",
                (source_key, gender, pos, title, prompt, prompt, preview),
            )
            await c.commit()
            return "added"

        row = dict(row)
        if row["source_prompt"] == prompt and row["title"] == title and row["preview"] == preview:
            return "unchanged"

        edited = (row["prompt"] or "").strip() != (row["source_prompt"] or "").strip()
        if edited and row["source_prompt"] != prompt:
            await c.execute(
                "UPDATE templates SET source_prompt=?, source_changed=1, title=?, preview=? "
                "WHERE id=?",
                (prompt, title, preview, row["id"]),
            )
            await c.commit()
            return "conflict"

        keep = row["prompt"] if edited else prompt
        await c.execute(
            "UPDATE templates SET prompt=?, source_prompt=?, source_changed=0, title=?, "
            "preview=? WHERE id=?",
            (keep, prompt, title, preview, row["id"]),
        )
        await c.commit()
        return "updated"


async def vault_keys() -> set[str]:
    async with _connect() as c:
        cur = await c.execute("SELECT source_key FROM templates WHERE source_key IS NOT NULL")
        return {r[0] for r in await cur.fetchall()}


async def bump_uses(template_id: int):
    async with _connect() as c:
        await c.execute("UPDATE templates SET uses=uses+1 WHERE id=?", (template_id,))
        await c.commit()


# --------------------------------------------------------------- settings

async def get_settings() -> dict:
    async with _connect() as c:
        cur = await c.execute("SELECT key, value FROM settings")
        stored = {r["key"]: r["value"] for r in await cur.fetchall()}
    return {**DEFAULT_SETTINGS, **stored}


async def set_settings(**pairs):
    pairs = {k: str(v) for k, v in pairs.items() if k in DEFAULT_SETTINGS}
    if not pairs:
        return
    async with _connect() as c:
        for key, value in pairs.items():
            await c.execute(
                "INSERT INTO settings(key, value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
        await c.commit()
