"""Batch merge, conflict rejection, idempotency, recovery and export gating."""
import copy

import pytest
from fastapi import HTTPException


def _drain(workflow, domain, engine):
    claimed = []
    while True:
        job = workflow.claim()
        if not job:
            return claimed
        run_id, token, payload = job
        claimed.append(run_id)
        try:
            workflow.finish(run_id, token, result=domain.solve(payload, engine))
        except Exception as exc:  # pragma: no cover - test aid
            workflow.finish(run_id, token, error=str(exc))


def _enqueue(workflow, payload, title='case'):
    case = workflow.make_case(title, payload, 'operator')
    return workflow.enqueue(case['id'], 'operator')


def test_first_batch_merges_and_evidence_is_exportable(services, sample):
    engine, domain, workflow = services
    run = _enqueue(workflow, copy.deepcopy(sample), '首批')
    _drain(workflow, domain, engine)
    from src.models.tables import batches, evidence, runs
    with engine.connect() as conn:
        finished = workflow.found(conn, runs, run['id'])
        evidence_row = conn.execute(
            evidence.select().where(evidence.c.run_id == run['id'])).mappings().one()
        batch = workflow.found(conn, batches, finished['batch_id'])
    assert finished['status'] == 'complete'
    assert evidence_row['exportable'] == 1 and evidence_row['inspection_passed'] == 1
    assert batch['status'] == 'accepted' and batch['score_count'] == 17


def test_duplicate_delivery_reuses_run_and_adds_no_evidence(services, sample):
    engine, domain, workflow = services
    first = _enqueue(workflow, copy.deepcopy(sample))
    _drain(workflow, domain, engine)
    from src.models.tables import evidence, runs
    reused = _enqueue(workflow, copy.deepcopy(sample), '重复送批')
    assert reused['reused'] is True and reused['run']['id'] == first['id']
    with engine.connect() as conn:
        assert len(conn.execute(runs.select()).mappings().all()) == 1
        assert len(conn.execute(evidence.select()).mappings().all()) == 1


def test_conflicting_stock_is_rejected_with_field_level_conflicts(services, sample):
    engine, domain, workflow = services
    _enqueue(workflow, copy.deepcopy(sample))
    _drain(workflow, domain, engine)
    conflicting = copy.deepcopy(sample)
    conflicting['batch_no'] = 'CAT-B'
    conflicting['scores'][0]['available_copies'] = 99
    conflicting['scores'][1]['title'] = '改名冲突曲目'
    with pytest.raises(HTTPException) as exc_info:
        _enqueue(workflow, conflicting, '冲突批')
    assert exc_info.value.status_code == 409
    numbers = sorted(item['score_number'] for item in exc_info.value.detail['conflicts'])
    assert numbers == [1205, 1209]
    from src.models.tables import batches, conflicts
    with engine.connect() as conn:
        assert conn.execute(
            batches.select().where(batches.c.status == 'rejected')).mappings().one()
        assert len(conn.execute(conflicts.select()).mappings().all()) == 2


def test_rejected_batch_does_not_pollute_merge_inventory(services, sample):
    engine, domain, workflow = services
    _enqueue(workflow, copy.deepcopy(sample))
    _drain(workflow, domain, engine)
    conflicting = copy.deepcopy(sample)
    conflicting['batch_no'] = 'CAT-B'
    conflicting['scores'][0]['available_copies'] = 99
    with pytest.raises(HTTPException):
        _enqueue(workflow, conflicting)
    fresh = {'batch_no': 'CAT-C', 'page_capacity': 3, 'range_start': 3001, 'range_end': 3002,
             'scores': [{'number': 3001, 'title': '新曲一', 'available_copies': 1},
                        {'number': 3002, 'title': '新曲二', 'available_copies': 0}]}
    run = _enqueue(workflow, fresh, '全新批')
    _drain(workflow, domain, engine)
    from src.models.tables import runs
    with engine.connect() as conn:
        assert workflow.found(conn, runs, run['id'])['status'] == 'complete'


def test_same_number_same_stock_is_absorbed_without_conflict(services, sample):
    engine, domain, workflow = services
    _enqueue(workflow, copy.deepcopy(sample))
    _drain(workflow, domain, engine)
    redelivery = copy.deepcopy(sample)
    redelivery['batch_no'] = 'CAT-D'
    run = _enqueue(workflow, redelivery, '同库存重送')
    assert run.get('reused') is not True
    _drain(workflow, domain, engine)
    from src.models.tables import conflicts, runs
    with engine.connect() as conn:
        assert workflow.found(conn, runs, run['id'])['status'] == 'complete'
        assert conn.execute(
            conflicts.select().where(conflicts.c.batch_id == run['batch_id'])).first() is None


def test_failed_run_retries_with_single_evidence(services, sample):
    engine, domain, workflow = services
    payload = copy.deepcopy(sample)
    payload['batch_no'] = 'CAT-E'
    run = _enqueue(workflow, payload)
    job = workflow.claim()
    workflow.finish(job[0], job[1], error='模拟后台失败')
    from src.models.tables import batches, evidence, runs
    with engine.connect() as conn:
        assert workflow.found(conn, runs, run['id'])['status'] == 'failed'
        assert workflow.found(conn, batches, run['batch_id'])['status'] == 'failed'
        assert conn.execute(
            evidence.select().where(evidence.c.run_id == run['id'])).first() is None
    retried = workflow.retry(run['id'], 'operator')
    assert retried['status'] == 'queued'
    _drain(workflow, domain, engine)
    with engine.connect() as conn:
        finished = workflow.found(conn, runs, run['id'])
        assert finished['status'] == 'complete' and finished['attempt_count'] == 3
        rows = conn.execute(
            evidence.select().where(evidence.c.run_id == run['id'])).mappings().all()
        assert len(rows) == 1 and rows[0]['exportable'] == 1
        assert workflow.found(conn, batches, run['batch_id'])['status'] == 'accepted'


def test_completed_run_cannot_be_retried(services, sample):
    engine, domain, workflow = services
    run = _enqueue(workflow, copy.deepcopy(sample))
    _drain(workflow, domain, engine)
    with pytest.raises(HTTPException) as exc_info:
        workflow.retry(run['id'], 'operator')
    assert exc_info.value.status_code == 409


def test_takeover_rejects_stale_token_and_leaves_no_half_evidence(services, sample):
    engine, domain, workflow = services
    from src.models.tables import evidence, runs
    from src.utils.time import utc_time
    payload = copy.deepcopy(sample)
    payload['batch_no'] = 'CAT-F'
    run = _enqueue(workflow, payload)
    run_id, old_token, _ = workflow.claim()
    with engine.begin() as conn:
        conn.execute(runs.update().where(runs.c.id == run_id)
                     .values(started_at=utc_time(-900), status='running'))
    _, new_token, _ = workflow.claim()
    assert workflow.finish(run_id, old_token,
                           result={'inspection_passed': True, 'exportable': True}) is None
    with engine.connect() as conn:
        assert conn.execute(
            evidence.select().where(evidence.c.run_id == run_id)).first() is None
    workflow.finish(run_id, new_token, result=domain.solve(payload, engine))
    with engine.connect() as conn:
        row = conn.execute(
            evidence.select().where(evidence.c.run_id == run_id)).mappings().one()
        assert row['exportable'] == 1
        assert workflow.found(conn, runs, run_id)['attempt_count'] == 2


def test_rejected_conflict_run_cannot_be_retried(services, sample):
    engine, domain, workflow = services
    _enqueue(workflow, copy.deepcopy(sample))
    _drain(workflow, domain, engine)
    conflicting = copy.deepcopy(sample)
    conflicting['batch_no'] = 'CAT-R'
    conflicting['scores'][0]['available_copies'] = 50
    with pytest.raises(HTTPException):
        _enqueue(workflow, conflicting)
    from src.models.tables import runs
    with engine.connect() as conn:
        rejected = conn.execute(
            runs.select().where(runs.c.status == 'rejected')).mappings().one()
    with pytest.raises(HTTPException) as exc_info:
        workflow.retry(rejected['id'], 'operator')
    assert exc_info.value.status_code == 409


def test_failed_batch_can_re_register_then_succeed(services, sample):
    engine, domain, workflow = services
    first = _enqueue(workflow, copy.deepcopy(sample))
    job = workflow.claim()
    workflow.finish(job[0], job[1], error='崩溃')
    second = _enqueue(workflow, copy.deepcopy(sample), '失败后重送')
    assert second['batch_id'] != first['batch_id']
    _drain(workflow, domain, engine)
    from src.models.tables import runs
    with engine.connect() as conn:
        assert workflow.found(conn, runs, second['id'])['status'] == 'complete'
    third = _enqueue(workflow, copy.deepcopy(sample), '归并后再送')
    assert third['reused'] is True and third['run']['id'] == second['id']


def test_download_gate_blocks_locked_report(services, sample):
    engine, domain, workflow = services
    from src.controllers.workflow import download
    good = _enqueue(workflow, copy.deepcopy(sample))
    _drain(workflow, domain, engine)
    from src.models.tables import evidence
    with engine.connect() as conn:
        good_evidence = conn.execute(
            evidence.select().where(evidence.c.run_id == good['id'])).mappings().one()
    assert download(good_evidence['id']).status_code == 200

    locked_payload = copy.deepcopy(sample)
    locked_payload['batch_no'] = 'CAT-G'
    locked_run = _enqueue(workflow, locked_payload)
    run_id, token, _ = workflow.claim()
    report = domain.solve(locked_payload, engine)
    report['exportable'] = False
    report['inspection_passed'] = False
    workflow.finish(run_id, token, result=report)
    with engine.connect() as conn:
        locked_evidence = conn.execute(
            evidence.select().where(evidence.c.run_id == locked_run['id'])).mappings().one()
    with pytest.raises(HTTPException) as exc_info:
        download(locked_evidence['id'])
    assert exc_info.value.status_code == 409
