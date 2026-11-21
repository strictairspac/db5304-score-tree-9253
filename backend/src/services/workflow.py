import hashlib
import uuid

from fastapi import HTTPException
from sqlalchemy import and_, or_, select

from src.config.settings import cache, engine
from src.constants.workflow import BatchStatus, Status
from src.models.tables import audit, batches, cases, conflicts, evidence, runs
from src.services import domain
from src.utils.encoding import canonical
from src.utils.time import utc_time


def log(conn, actor, action, reference):
    conn.execute(audit.insert().values(actor=actor, action=action, reference=str(reference),
                                       created_at=utc_time()))


def recent(table):
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(select(table).order_by(table.c.id.desc()).limit(100)).mappings()]


def found(conn, table, identity):
    row = conn.execute(select(table).where(table.c.id == identity)).mappings().first()
    if row is None:
        raise HTTPException(404, '找不到该记录')
    return dict(row)


def make_case(title, payload, actor):
    title = title.strip()
    if not title:
        raise HTTPException(422, '档案名称不能为空')
    try:
        if len(canonical(payload)) > 512 * 1024:
            raise ValueError('业务输入超过 512 KiB')
        if callable(getattr(domain, 'validate', None)):
            domain.validate(payload)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from None
    with engine.begin() as conn:
        case_id = conn.execute(cases.insert().values(slug=uuid.uuid4().hex, title=title, payload=payload,
                               author=actor, created_at=utc_time())).inserted_primary_key[0]
        log(conn, actor, 'create_case', case_id)
        return found(conn, cases, case_id)


def _fingerprint(payload) -> str:
    """归并口径：批次号 + 编号/谱名/库存的规范化内容指纹。"""
    batch_no, _, _, _, scores = domain._read_payload(payload)
    material = {'batch_no': batch_no,
                'scores': [{'number': s.number, 'title': s.title, 'available_copies': s.available_copies}
                           for s in scores]}
    return hashlib.sha256(canonical(material)).hexdigest()


def _accepted_index(conn) -> dict[int, dict]:
    """已成功归并批次的编号 -> 曲谱库存视图（失败/拒绝批次不参与归并）。"""
    index: dict[int, dict] = {}
    accepted = conn.execute(select(batches).where(batches.c.status == BatchStatus.ACCEPTED)).mappings()
    for batch in accepted:
        case = found(conn, cases, batch['case_id'])
        for row in case['payload'].get('scores', []):
            index[row['number']] = {
                'title': str(row.get('title', '')).strip(),
                'available_copies': row.get('available_copies'),
                'batch_id': batch['id'], 'batch_no': batch['batch_no'],
            }
    return index


def _detect_conflicts(conn, payload):
    batch_no, _, _, _, scores = domain._read_payload(payload)
    merged = _accepted_index(conn)
    clashes = []
    for score in scores:
        holder = merged.get(score.number)
        if holder is None:
            continue
        same_stock = holder['title'] == score.title and holder['available_copies'] == score.available_copies
        if same_stock:
            # 编号已归并且库存一致：扫描端重复送批，幂等吸收，不算冲突
            continue
        clashes.append({
            'score_number': score.number,
            'incoming_title': score.title, 'incoming_copies': score.available_copies,
            'existing_batch_id': holder['batch_id'], 'existing_batch_no': holder['batch_no'],
            'existing_title': holder['title'], 'existing_copies': holder['available_copies'],
        })
    return batch_no, clashes


def enqueue(case_id, actor):
    """登记目录批次并排入执行队列。

    扫描端重复送批的三种处理：
    1. 同批次号 + 同内容指纹：复用既有执行，不新增证据；
    2. 编号已归并且库存一致：作为重复条目吸收，正常执行；
    3. 编号冲突（谱名或库存不一致）：整批拒绝并指出冲突，不产生执行与证据。
    """
    with engine.connect() as conn:
        case = found(conn, cases, case_id)
        try:
            batch_no = domain._read_payload(case['payload'])[0]
            fingerprint = _fingerprint(case['payload'])
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from None
        duplicate = conn.execute(
            select(batches).where(batches.c.batch_no == batch_no,
                                  batches.c.fingerprint == fingerprint,
                                  batches.c.status == BatchStatus.ACCEPTED)).mappings().first()
        if duplicate is not None:
            existing_run = conn.execute(
                select(runs).where(runs.c.batch_id == duplicate['id']).order_by(runs.c.id.desc())
            ).mappings().first()
        else:
            existing_run = None
        _, clash_list = _detect_conflicts(conn, case['payload'])
        score_count = len(case['payload'].get('scores', []))
        copies_total = sum(int(row.get('available_copies', 0)) for row in case['payload'].get('scores', []))

    if duplicate is not None:
        with engine.begin() as conn:
            log(conn, actor, 'duplicate_batch', duplicate['id'])
        return {'reused': True, 'batch_id': duplicate['id'],
                'run': dict(existing_run) if existing_run else None,
                'detail': f'批次 {batch_no} 已由扫描端送入并归并，复用既有执行，未新增证据。'}

    if clash_list:
        # 先在独立事务落盘拒绝记录，再抛出 409，避免异常回滚丢失冲突证据
        with engine.begin() as conn:
            batch_id = conn.execute(batches.insert().values(
                batch_no=batch_no, fingerprint=fingerprint, case_id=case_id,
                status=BatchStatus.REJECTED, score_count=0, copies_total=0,
                owner=actor, created_at=utc_time())).inserted_primary_key[0]
            for clash in clash_list:
                conn.execute(conflicts.insert().values(
                    batch_id=batch_id, score_number=clash['score_number'],
                    incoming_title=clash['incoming_title'], incoming_copies=clash['incoming_copies'],
                    existing_batch_id=clash['existing_batch_id'],
                    existing_title=clash['existing_title'], existing_copies=clash['existing_copies'],
                    created_at=utc_time()))
            rejected_run = conn.execute(runs.insert().values(
                case_id=case_id, status=Status.REJECTED, owner=actor, batch_id=batch_id,
                attempt_count=0, created_at=utc_time(),
                error=f'批次 {batch_no} 存在 {len(clash_list)} 个编号冲突，整批拒绝，未归并库存。')
            ).inserted_primary_key[0]
            log(conn, actor, 'reject_batch', batch_id)
        raise HTTPException(409, {
            'message': f'批次 {batch_no} 与已归并批次存在 {len(clash_list)} 个编号冲突，整批拒绝。',
            'batch_id': batch_id, 'run_id': rejected_run, 'conflicts': clash_list})

    with engine.begin() as conn:
        batch_id = conn.execute(batches.insert().values(
            batch_no=batch_no, fingerprint=fingerprint, case_id=case_id,
            status=Status.QUEUED.value, score_count=score_count, copies_total=copies_total,
            owner=actor, created_at=utc_time())).inserted_primary_key[0]
        run_id = conn.execute(runs.insert().values(case_id=case_id, status=Status.QUEUED,
                              owner=actor, batch_id=batch_id, attempt_count=0,
                              created_at=utc_time())).inserted_primary_key[0]
        log(conn, actor, 'enqueue', run_id)
        result = found(conn, runs, run_id)
    _wake()
    return result


def retry(run_id, actor):
    """失败/接管中断后的显式重试：复用同一执行记录与批次，不新增证据行。"""
    with engine.begin() as conn:
        run = found(conn, runs, run_id)
        if run['status'] not in (Status.FAILED, Status.REJECTED):
            raise HTTPException(409, '仅执行失败或被拒绝的记录可以重试；处理中或已完成的记录无需重试。')
        if run['status'] == Status.REJECTED:
            clash = conn.execute(select(conflicts).where(conflicts.c.batch_id == run['batch_id'])).mappings().first()
            if clash is not None:
                raise HTTPException(409, '该批次因编号冲突被拒绝，请先修正冲突编号或库存后以新批次重新提交。')
        conn.execute(runs.update().where(runs.c.id == run_id).values(
            status=Status.QUEUED, attempt_token=None, started_at=None,
            finished_at=None, error=None, attempt_count=runs.c.attempt_count + 1))
        if run['batch_id'] is not None:
            conn.execute(batches.update().where(batches.c.id == run['batch_id'])
                         .values(status=Status.QUEUED.value, merged_at=None))
        log(conn, actor, 'retry', run_id)
        result = found(conn, runs, run_id)
    _wake()
    return result


def _wake():
    try:
        cache.lpush('worker:wake', 'queued')
        cache.ltrim('worker:wake', 0, 99)
    except Exception:
        # The durable database queue is polled even if Redis is temporarily unavailable.
        pass


def claim():
    """领取排队任务，或接管超过 10 分钟无心跳的执行（崩溃恢复）。"""
    ready = or_(runs.c.status == Status.QUEUED,
                and_(runs.c.status == Status.RUNNING, runs.c.started_at < utc_time(-600)))
    with engine.begin() as conn:
        run = conn.execute(select(runs.c.id, runs.c.case_id, runs.c.attempt_count).where(ready)
                           .order_by(runs.c.id).limit(1).with_for_update(skip_locked=True)).first()
        if not run:
            return None
        token = str(uuid.uuid4())
        conn.execute(runs.update().where(runs.c.id == run.id).values(
            started_at=utc_time(), status=Status.RUNNING, attempt_token=token,
            attempt_count=(run.attempt_count or 0) + 1))
        return run.id, token, found(conn, cases, run.case_id)['payload']


def finish(run_id, token, result=None, error=None):
    """终态写入。attempt_token 保证只有当前持有者能落盘，证据唯一且不留半份。"""
    digest = hashlib.sha256(canonical(result)).hexdigest() if result is not None else None
    with engine.begin() as conn:
        rowcount = conn.execute(runs.update().where(
            runs.c.id == run_id, runs.c.attempt_token == token, runs.c.status == Status.RUNNING)
            .values(status=Status.FAILED if error else Status.COMPLETE,
                    finished_at=utc_time(), error=error)).rowcount
        if not rowcount:
            # 令牌失效（已被接管或重复回调）：放弃本次写入，避免半份结果
            return
        if result is not None:
            passed = bool(result.get('inspection_passed'))
            exportable = bool(result.get('exportable')) and passed
            # run_id 唯一约束兜底：重试成功也只会有一份证据
            already = conn.execute(select(evidence.c.id).where(evidence.c.run_id == run_id)).first()
            if already is None:
                conn.execute(evidence.insert().values(run_id=run_id, report=result, digest=digest,
                                                       inspection_passed=passed, exportable=exportable))
            current = conn.execute(select(runs.c.batch_id).where(runs.c.id == run_id)).mappings().first()
            if current and current['batch_id'] is not None:
                conn.execute(batches.update().where(batches.c.id == current['batch_id']).values(
                    status=BatchStatus.ACCEPTED if exportable else BatchStatus.FAILED,
                    merged_at=utc_time() if exportable else None))
        else:
            current = conn.execute(select(runs.c.batch_id).where(runs.c.id == run_id)).mappings().first()
            if current and current['batch_id'] is not None:
                conn.execute(batches.update().where(batches.c.id == current['batch_id'])
                             .values(status=BatchStatus.FAILED, merged_at=None))
        log(conn, 'worker', Status.FAILED.value if error else Status.COMPLETE.value, run_id)


def review(identity, note, actor):
    note = note.strip()
    if not note:
        raise HTTPException(422, '复核意见不能为空')
    with engine.begin() as conn:
        found(conn, evidence, identity)
        count = conn.execute(evidence.update().where(evidence.c.id == identity, evidence.c.reviewed_at.is_(None))
                            .values(review_note=note, reviewer=actor, reviewed_at=utc_time())).rowcount
        if count != 1:
            raise HTTPException(409, '该证据已经复核')
        log(conn, actor, 'review', identity)
        return found(conn, evidence, identity)


def list_conflicts(limit=100):
    with engine.connect() as conn:
        rows = conn.execute(select(conflicts, batches.c.batch_no)
                            .join(batches, batches.c.id == conflicts.c.batch_id)
                            .order_by(conflicts.c.id.desc()).limit(limit)).mappings()
        return [dict(row) for row in rows]
