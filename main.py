"""Application entry point."""

import asyncio

from src.config import load_settings
from src.logger import setup_logging
from src.server import start_server


def main() -> None:
    """Load config and start the WebSocket server."""
    settings = load_settings()
    setup_logging(settings.log_level)
    if settings.debug:
        print(f"Debug mode is ON. Host={settings.host}, Port={settings.port}")
    asyncio.run(start_server(settings))


if __name__ == "__main__":
    main()
