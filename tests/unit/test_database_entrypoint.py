import src.database as database
import src.core.database as core_database


def test_core_database_should_reexport_unified_async_entrypoint():
    assert core_database.get_async_engine is database.get_async_engine
    assert core_database.get_async_session_factory is database.get_async_session_factory
    assert core_database.get_db is database.get_db
    assert core_database.get_db_context is database.get_db_context
    assert core_database.init_database is database.init_database
    assert core_database.close_database is database.close_database


def test_core_database_should_not_create_legacy_sync_session_entrypoints():
    assert not hasattr(core_database, "engine")
    assert not hasattr(core_database, "SessionLocal")
