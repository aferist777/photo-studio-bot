"""Entrypoint: the admin panel and the Telegram bot in one process.

One process means an edit in the browser reaches a running bot immediately —
no restart, no cache to synchronize between processes. The bot half joins here
once onboarding lands; for now this serves the catalog.
"""

import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn                                       # noqa: E402

from admin.server import app as admin_app            # noqa: E402
from bot import db                                   # noqa: E402
from bot.config import ADMIN_HOST, ADMIN_PORT        # noqa: E402
from tools.import_vault import import_if_empty       # noqa: E402


async def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    await db.init()
    await import_if_empty()

    server = uvicorn.Server(
        uvicorn.Config(admin_app, host=ADMIN_HOST, port=ADMIN_PORT, log_level="warning")
    )
    print(f"\n  Admin panel:  http://{ADMIN_HOST}:{ADMIN_PORT}\n  Ctrl+C to stop\n")
    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
