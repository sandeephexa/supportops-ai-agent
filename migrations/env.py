from alembic import context
from sqlalchemy import create_engine, pool, text
from supportops.config import Settings
from supportops.db import Base

config = context.config
url = Settings().database_url
config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # Checkpointer tables and the expression FTS index are managed explicitly.
    if (
        reflected
        and type_ == "table"
        and name in {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}
    ):
        return False
    if reflected and type_ == "index" and name == "documents_fts":
        return False
    return True


if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        if url.startswith("postgresql"):
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
