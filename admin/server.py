"""Local admin panel: the photoshoot catalog and the bot's generation settings.

Bound to loopback with no authentication — see bot/config.ADMIN_HOST.
"""

import mimetypes
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bot import db, prompt, store
from bot.config import GENDER_LABELS, PREVIEW_DIR, VAULT_DIR
from tools import import_vault, structure

HERE = Path(__file__).resolve().parent

# A stock Windows registry has no .webp entry, so previews would go out as
# application/octet-stream.
mimetypes.add_type("image/webp", ".webp")

app = FastAPI(title="Photo studio", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
app.mount("/previews", StaticFiles(directory=PREVIEW_DIR), name="previews")
templates = Jinja2Templates(directory=str(HERE / "templates"))


async def _template_or_404(template_id: int) -> dict:
    template = await db.get_template(template_id)
    if not template:
        raise HTTPException(404, "template not found")
    return template


def _refresh():
    """Any write must drop the cached catalog so the live bot picks it up."""
    store.invalidate()


async def _counts() -> dict:
    counts = {}
    for gender in GENDER_LABELS:
        rows = await db.list_templates(gender=gender)
        counts[gender] = {
            "total": len(rows),
            "on": sum(1 for r in rows if r["is_enabled"] and r["prompt"]),
            "raw": sum(1 for r in rows if not prompt.is_structured(r["fields"])),
        }
    return counts


# ------------------------------------------------------------------ pages

@app.get("/")
async def page_catalog(request: Request, g: str = "female"):
    gender = g if g in GENDER_LABELS else "female"
    return templates.TemplateResponse(
        request,
        "catalog.html",
        {
            "section": "catalog",
            "gender": gender,
            "genders": GENDER_LABELS,
            "counts": await _counts(),
            "items": await db.list_templates(gender=gender),
            "vault": str(VAULT_DIR),
        },
    )


@app.get("/templates/{template_id}")
async def page_template(request: Request, template_id: int):
    template = await _template_or_404(template_id)
    return templates.TemplateResponse(
        request,
        "template.html",
        {
            "section": "catalog",
            "t": template,
            "genders": GENDER_LABELS,
            "specs": prompt.FIELDS,
            "values": prompt.loads(template["fields"]),
            "structured": prompt.is_structured(template["fields"]),
        },
    )


@app.get("/settings")
async def page_settings(request: Request):
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"section": "settings", "s": await db.get_settings(), "vault": str(VAULT_DIR)},
    )


# -------------------------------------------------------------------- api

@app.post("/api/import")
async def api_import():
    report = await import_vault.run()
    _refresh()
    return {"summary": import_vault.summary(report), **report}


@app.post("/api/structure")
async def api_structure(request: Request):
    body = await request.json() if await request.body() else {}
    report = await structure.run(
        only_missing=body.get("only_missing", True), ids=body.get("ids")
    )
    _refresh()
    return {"summary": structure.summary(report), **report}


@app.post("/api/templates")
async def api_create(request: Request):
    body = await request.json()
    gender = body.get("gender")
    if gender not in GENDER_LABELS:
        raise HTTPException(400, "unknown gender")
    title = (body.get("title") or "Untitled").strip()
    template_id = await db.create_template(gender, title)
    _refresh()
    return {"id": template_id}


@app.post("/api/templates/reorder")
async def api_reorder(request: Request):
    body = await request.json()
    gender = body.get("gender")
    if gender not in GENDER_LABELS:
        raise HTTPException(400, "unknown gender")
    await db.reorder_templates(gender, [int(i) for i in body.get("ids", [])])
    _refresh()
    return {"ok": True}


@app.post("/api/templates/{template_id}")
async def api_update(template_id: int, request: Request):
    await _template_or_404(template_id)
    body = await request.json()
    if "gender" in body and body["gender"] not in GENDER_LABELS:
        raise HTTPException(400, "unknown gender")
    await db.update_template(template_id, **body)
    _refresh()
    return {"ok": True}


@app.post("/api/templates/{template_id}/fields")
async def api_fields(template_id: int, request: Request):
    await _template_or_404(template_id)
    rendered = await db.set_fields(template_id, await request.json())
    _refresh()
    return {"prompt": rendered}


@app.post("/api/templates/{template_id}/unstructure")
async def api_unstructure(template_id: int):
    await _template_or_404(template_id)
    await db.clear_fields(template_id)
    _refresh()
    return {"ok": True}


@app.post("/api/templates/{template_id}/reset")
async def api_reset(template_id: int):
    template = await _template_or_404(template_id)
    if not template["source_prompt"]:
        raise HTTPException(400, "this template has no vault text")
    await db.reset_to_source(template_id)
    _refresh()
    return {"prompt": template["source_prompt"]}


@app.delete("/api/templates/{template_id}")
async def api_delete(template_id: int):
    await _template_or_404(template_id)
    await db.delete_template(template_id)
    _refresh()
    return {"ok": True}


@app.post("/api/settings")
async def api_settings(request: Request):
    await db.set_settings(**await request.json())
    _refresh()
    return {"ok": True}
