"""Idempotent additive migration for demo deployments on persistent volumes.

Fresh databases are created directly from ``models.tables``. Existing volumes
from the initial snapshot predate batch registration and the export gate, so
the missing columns and tables are added here without dropping any data.
"""
from sqlalchemy import inspect, text

from src.config.settings import engine
from src.models.tables import batches, conflicts, schema


def _add_missing_columns(conn, table, statements):
    existing = {column['name'] for column in inspect(conn).get_columns(table)}
    added = []
    for name, statement in statements.items():
        if name not in existing:
            conn.execute(text(statement))
            added.append(name)
    return added


def upgrade():
    schema.create_all(engine)
    with engine.begin() as conn:
        _add_missing_columns(conn, 'business_runs', {
            'attempt_count': "ALTER TABLE business_runs ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0",
            'batch_id': 'ALTER TABLE business_runs ADD COLUMN batch_id INTEGER NULL',
        })
        evidence_added = _add_missing_columns(conn, 'business_evidence', {
            'inspection_passed': 'ALTER TABLE business_evidence ADD COLUMN inspection_passed BOOLEAN NOT NULL DEFAULT 0',
            'exportable': 'ALTER TABLE business_evidence ADD COLUMN exportable BOOLEAN NOT NULL DEFAULT 0',
        })
        # 旧库升级：闸门列刚加入，历史证据均来自通过全部巡检的旧版本，保持其可下载状态
        if evidence_added:
            conn.execute(text(
                'UPDATE business_evidence SET inspection_passed = 1, exportable = 1'))
        tables_now = set(inspect(conn).get_table_names())
        for table in (batches, conflicts):
            if table.name not in tables_now:
                table.create(bind=conn)
