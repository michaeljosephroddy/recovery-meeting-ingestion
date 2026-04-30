import psycopg

from app.config import Settings


def connect(settings: Settings) -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(settings.database_url)

