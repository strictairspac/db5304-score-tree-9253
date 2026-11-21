"""Additive migration from the initial snapshot schema."""
from sqlalchemy import (JSON, Column, ForeignKey, Integer, MetaData, String,
                        Table, Text, create_engine, inspect, text)


def test_upgrade_adds_tables_columns_and_backfills_legacy_evidence(tmp_path):
    legacy_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(legacy_url)
    metadata = MetaData()
    users = Table('accounts', metadata, Column('id', Integer, primary_key=True),
                  Column('username', String(40), nullable=False, unique=True),
                  Column('password_hash', String(200), nullable=False),
                  Column('role', String(20), nullable=False))
    cases = Table('business_cases', metadata, Column('id', Integer, primary_key=True),
                  Column('slug', String(64), nullable=False, unique=True),
                  Column('title', String(120), nullable=False), Column('payload', JSON, nullable=False),
                  Column('author', String(40), nullable=False), Column('created_at', String(32), nullable=False))
    runs = Table('business_runs', metadata, Column('id', Integer, primary_key=True),
                 Column('case_id', ForeignKey('business_cases.id'), nullable=False),
                 Column('status', String(20), nullable=False), Column('owner', String(40), nullable=False),
                 Column('attempt_token', String(36)), Column('started_at', String(32)),
                 Column('finished_at', String(32)), Column('created_at', String(32), nullable=False),
                 Column('error', Text))
    evidence = Table('business_evidence', metadata, Column('id', Integer, primary_key=True),
                     Column('run_id', ForeignKey('business_runs.id'), nullable=False, unique=True),
                     Column('report', JSON, nullable=False), Column('digest', String(64), nullable=False),
                     Column('reviewer', String(40)), Column('review_note', String(500)),
                     Column('reviewed_at', String(32)))
    Table('audit_events', metadata, Column('id', Integer, primary_key=True),
          Column('actor', String(40), nullable=False), Column('action', String(32), nullable=False),
          Column('reference', String(50), nullable=False), Column('created_at', String(32), nullable=False))
    metadata.create_all(engine)
    with engine.begin() as conn:
        case_id = conn.execute(cases.insert().values(
            slug='old', title='旧档案', payload={}, author='operator', created_at='t')).inserted_primary_key[0]
        run_id = conn.execute(runs.insert().values(
            case_id=case_id, status='complete', owner='operator', created_at='t')).inserted_primary_key[0]
        conn.execute(evidence.insert().values(run_id=run_id, report={'old': True}, digest='d1'))
    engine.dispose()

    import os
    os.environ['DATABASE_URL'] = legacy_url
    from src.config import migrate
    from src.config import settings
    # settings 已按测试库初始化，这里直接对遗留库执行同一套迁移语句
    migrate.engine = create_engine(legacy_url)
    migrate.upgrade()
    migrate.upgrade()  # 第二次必须幂等

    inspector = inspect(migrate.engine)
    run_columns = {c['name'] for c in inspector.get_columns('business_runs')}
    evidence_columns = {c['name'] for c in inspector.get_columns('business_evidence')}
    assert {'attempt_count', 'batch_id'} <= run_columns
    assert {'inspection_passed', 'exportable'} <= evidence_columns
    assert {'catalog_batches', 'batch_conflicts'} <= set(inspector.get_table_names())
    with migrate.engine.connect() as conn:
        assert conn.execute(text(
            'select inspection_passed, exportable from business_evidence')).one() == (1, 1)
        assert conn.execute(text(
            'select attempt_count, batch_id from business_runs')).one() == (0, None)
    settings.engine.dispose()
