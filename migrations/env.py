import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from module_agent.shared.config import app_settings
from module_agent.bootstrap import database_models
from module_agent.shared.database.base import Base


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Importing models registers every table on Base.metadata for autogeneration.
_ = database_models
target_metadata = Base.metadata

# LangGraph owns these checkpoint tables and migrates them independently.  They
# are deliberately excluded from our application's Alembic autogeneration so
# `alembic check` does not try to delete third-party state.
LANGGRAPH_TABLES = {
    "checkpoint_blobs",
    "checkpoint_migrations",
    "checkpoint_writes",
    "checkpoints",
}


def include_object(
    object_: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object | None,
) -> bool:
    _ = object_, compare_to
    return not (
        type_ == "table"
        and reflected
        and name in LANGGRAPH_TABLES
    )


def run_migrations_offline() -> None:
    context.configure(
        url=app_settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = app_settings.database_url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
