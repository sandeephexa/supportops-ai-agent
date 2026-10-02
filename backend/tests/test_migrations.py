from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_initial_migration_roundtrip(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/migrations.db"
    monkeypatch.setenv("SUPPORTOPS_DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_engine(url)
    assert {"cases", "documents", "actions", "tickets", "audit_events"} <= set(
        inspect(engine).get_table_names()
    )
    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    command.upgrade(config, "head")
    assert "cases" in inspect(engine).get_table_names()
    engine.dispose()
