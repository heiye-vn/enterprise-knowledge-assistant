import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

pytestmark = pytest.mark.integration


def test_migration_upgrade_is_repeatable_and_rollback_rebuilds_eight_tables(test_engine):
    from app.config import PROJECT_ROOT

    config = Config(str(PROJECT_ROOT / "backend/alembic.ini"))
    with test_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        command.check(config)
        command.downgrade(config, "base")
        assert set(inspect(connection).get_table_names()) == {"alembic_version"}
        command.upgrade(config, "head")
        assert len(set(inspect(connection).get_table_names()) - {"alembic_version"}) == 8
        command.check(config)
