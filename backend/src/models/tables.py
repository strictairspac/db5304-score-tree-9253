from sqlalchemy import (JSON, Boolean, Column, ForeignKey, Integer, MetaData,
                        String, Table, Text)

schema = MetaData()
users = Table('accounts', schema,
    Column('id', Integer, primary_key=True),
    Column('username', String(40), nullable=False, unique=True),
    Column('password_hash', String(200), nullable=False),
    Column('role', String(20), nullable=False))
cases = Table('business_cases', schema,
    Column('id', Integer, primary_key=True),
    Column('slug', String(64), nullable=False, unique=True),
    Column('title', String(120), nullable=False),
    Column('payload', JSON, nullable=False),
    Column('author', String(40), nullable=False),
    Column('created_at', String(32), nullable=False))
runs = Table('business_runs', schema,
    Column('id', Integer, primary_key=True),
    Column('case_id', ForeignKey('business_cases.id'), nullable=False, index=True),
    Column('status', String(20), nullable=False, index=True),
    Column('owner', String(40), nullable=False),
    Column('attempt_token', String(36)),
    Column('attempt_count', Integer, nullable=False, server_default='0'),
    Column('batch_id', ForeignKey('catalog_batches.id'), index=True),
    Column('started_at', String(32)),
    Column('finished_at', String(32)),
    Column('created_at', String(32), nullable=False),
    Column('error', Text))
evidence = Table('business_evidence', schema,
    Column('id', Integer, primary_key=True),
    Column('run_id', ForeignKey('business_runs.id'), nullable=False, unique=True),
    Column('report', JSON, nullable=False),
    Column('digest', String(64), nullable=False),
    # 巡检闸门：只有叶页链、记录数守恒与范围结果全部通过，才可导出
    Column('inspection_passed', Boolean, nullable=False, server_default='0'),
    Column('exportable', Boolean, nullable=False, server_default='0'),
    Column('reviewer', String(40)),
    Column('review_note', String(500)),
    Column('reviewed_at', String(32)))
# 流通组按曲谱编号与库存归并的目录批次登记。
# 同一批次号+内容指纹在归并成功后由应用层保证唯一；失败批次允许重新登记以支持恢复。
batches = Table('catalog_batches', schema,
    Column('id', Integer, primary_key=True),
    Column('batch_no', String(64), nullable=False, index=True),
    Column('fingerprint', String(64), nullable=False),
    Column('case_id', ForeignKey('business_cases.id'), nullable=False),
    Column('status', String(20), nullable=False, index=True),
    Column('score_count', Integer, nullable=False, server_default='0'),
    Column('copies_total', Integer, nullable=False, server_default='0'),
    Column('owner', String(40), nullable=False),
    Column('created_at', String(32), nullable=False),
    Column('merged_at', String(32)))
# 编号冲突明细：同一编号被多个批次以不同库存/谱名送入
conflicts = Table('batch_conflicts', schema,
    Column('id', Integer, primary_key=True),
    Column('batch_id', ForeignKey('catalog_batches.id'), nullable=False, index=True),
    Column('score_number', Integer, nullable=False, index=True),
    Column('incoming_title', String(120)),
    Column('incoming_copies', Integer),
    Column('existing_batch_id', ForeignKey('catalog_batches.id'), nullable=False),
    Column('existing_title', String(120)),
    Column('existing_copies', Integer),
    Column('created_at', String(32), nullable=False))
audit = Table('audit_events', schema,
    Column('id', Integer, primary_key=True),
    Column('actor', String(40), nullable=False),
    Column('action', String(32), nullable=False),
    Column('reference', String(50), nullable=False),
    Column('created_at', String(32), nullable=False))
