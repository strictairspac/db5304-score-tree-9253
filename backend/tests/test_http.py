"""HTTP endpoints: conflict payload, retry route, gate and permissions."""
import copy


def _run_worker(services):
    engine, domain, workflow = services
    job = workflow.claim()
    workflow.finish(job[0], job[1], result=domain.solve(job[2], engine))


def test_full_http_flow_conflict_retry_and_gate(client, auth_headers, sample, services):
    headers = auth_headers('operator')
    case = client.post('/cases', headers=headers,
                       json={'title': '首批', 'payload': sample}).json()
    response = client.post(f"/cases/{case['id']}/runs", headers=headers)
    assert response.status_code == 202
    first_run = response.json()
    _run_worker(services)

    evidence = client.get('/evidence', headers=headers).json()[0]
    assert evidence['exportable'] is True and evidence['inspection_passed'] is True

    duplicate_case = client.post('/cases', headers=headers,
                                 json={'title': '重复', 'payload': copy.deepcopy(sample)}).json()
    response = client.post(f"/cases/{duplicate_case['id']}/runs", headers=headers)
    assert response.status_code == 202 and response.json()['reused'] is True
    assert response.json()['run']['id'] == first_run['id']

    conflict = copy.deepcopy(sample)
    conflict['batch_no'] = 'CAT-HTTP-B'
    conflict['scores'][0]['available_copies'] = 99
    conflict_case = client.post('/cases', headers=headers,
                                json={'title': '冲突', 'payload': conflict}).json()
    response = client.post(f"/cases/{conflict_case['id']}/runs", headers=headers)
    assert response.status_code == 409
    assert response.json()['detail']['conflicts'][0]['score_number'] == 1209

    assert client.get('/conflicts', headers=auth_headers('viewer')).json()
    batches = client.get('/batches', headers=headers).json()
    assert {row['status'] for row in batches} >= {'accepted', 'rejected'}

    rejected = next(row for row in client.get('/runs', headers=headers).json()
                    if row['status'] == 'rejected')
    assert client.post(f"/runs/{rejected['id']}/retry", headers=headers).status_code == 409

    failure = copy.deepcopy(sample)
    failure['batch_no'] = 'CAT-HTTP-C'
    failure_case = client.post('/cases', headers=headers,
                               json={'title': '失败', 'payload': failure}).json()
    failed_run = client.post(f"/cases/{failure_case['id']}/runs", headers=headers).json()
    job = services[2].claim()
    services[2].finish(job[0], job[1], error='模拟失败')
    response = client.post(f"/runs/{failed_run['id']}/retry", headers=headers)
    assert response.status_code == 202 and response.json()['status'] == 'queued'
    _run_worker(services)
    retried_evidence = [row for row in client.get('/evidence', headers=headers).json()
                        if row['run_id'] == failed_run['id']]
    assert len(retried_evidence) == 1 and retried_evidence[0]['exportable'] is True

    locked = copy.deepcopy(sample)
    locked['batch_no'] = 'CAT-HTTP-D'
    locked_case = client.post('/cases', headers=headers,
                              json={'title': '锁定', 'payload': locked}).json()
    locked_run = client.post(f"/cases/{locked_case['id']}/runs", headers=headers).json()
    run_id, token, payload = services[2].claim()
    report = services[1].solve(payload, engine=services[0])
    report['exportable'] = False
    report['inspection_passed'] = False
    services[2].finish(run_id, token, result=report)
    locked_evidence = next(row for row in client.get('/evidence', headers=headers).json()
                           if row['run_id'] == locked_run['id'])
    assert client.get(f"/evidence/{locked_evidence['id']}/download",
                      headers=headers).status_code == 409
    assert client.get(f"/evidence/{evidence['id']}/download",
                      headers=auth_headers('viewer')).status_code == 200


def test_role_permissions_hold(client, auth_headers, sample):
    viewer = auth_headers('viewer')
    operator = auth_headers('operator')
    reviewer = auth_headers('reviewer')
    assert client.post('/cases', headers=viewer,
                       json={'title': 'x', 'payload': sample}).status_code == 403
    case = client.post('/cases', headers=operator,
                       json={'title': 'ok', 'payload': sample}).json()
    run = client.post(f"/cases/{case['id']}/runs", headers=operator).json()
    assert client.post(f"/runs/{run['id']}/retry", headers=viewer).status_code == 403
    evidence = client.get('/evidence', headers=operator).json()
    if evidence:
        assert client.post(f"/evidence/{evidence[0]['id']}/review", headers=operator,
                           json={'note': 'x'}).status_code == 403


def test_invalid_input_returns_field_error(client, auth_headers, sample):
    sample['page_capacity'] = 1
    response = client.post('/cases', headers=auth_headers('operator'),
                           json={'title': 'bad', 'payload': sample})
    assert response.status_code == 422 and '页容量' in response.json()['detail']
