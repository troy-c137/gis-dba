"""Load local configuration and resolve database connection settings."""

import os

from dotenv import load_dotenv

load_dotenv()


def database_url(name: str = "DATABASE_URL") -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required; see .env.example")
    return value
