from fastapi import HTTPException
from starlette.responses import Response

from src.config.settings import engine
from src.models.tables import evidence
from src.services.workflow import found
from src.utils.encoding import canonical


def download(identity):
    with engine.connect() as conn:
        data = found(conn, evidence, identity)
    # 巡检闸门：叶页链、记录数守恒与范围结果全部通过，报告才可安全下载
    if not data.get('exportable') or not data.get('inspection_passed'):
        raise HTTPException(409, '巡检未全部通过，报告处于锁定状态，不可导出。')
    return Response(canonical(data), media_type='application/json', headers={
        'Content-Disposition': f'attachment; filename="evidence-{identity}.json"'})
