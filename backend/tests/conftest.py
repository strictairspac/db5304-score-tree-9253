"""Pytest fixtures: isolated SQLite database and a fake Redis client.

The real deployment runs on MySQL + Redis; these tests exercise the same
SQLAlchemy layer against SQLite so the suite needs no external services.
"""
import os
import sys
import types
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


@pytest.fixture(scope='session', autouse=True)
def _isolated_environment(tmp_path_factory):
    db_path = tmp_path_factory.mktemp('db') / 'workflow.db'
    os.environ['AUTH_KEY'] = 'test-key'
    os.environ['DATABASE_URL'] = f'sqlite:///{db_path}'
    os.environ['ARTIFACTS_DIR'] = str(tmp_path_factory.mktemp('artifacts'))
    fake = types.ModuleType('redis')

    class _FakeRedis:
        def __init__(self):
            self.queue = []

        def lpush(self, _key, value):
            self.queue.insert(0, value)

        def ltrim(self, _key, start, end):
            self.queue[:] = self.queue[start:end + 1]

        def brpop(self, _key, timeout=0):
            return None

        def ping(self):
            return True

    _FakeRedis.from_url = staticmethod(lambda *args, **kwargs: _FakeRedis())
    fake.Redis = _FakeRedis
    sys.modules['redis'] = fake
    yield


@pytest.fixture()
def services(_isolated_environment):
    from src.config.settings import engine
    from src.models.tables import schema
    schema.drop_all(engine)
    schema.create_all(engine)
    from src.models.tables import users
    from src.services.security import hash_password
    with engine.begin() as conn:
        for name, role in (('operator', 'operator'), ('reviewer', 'reviewer'), ('viewer', 'viewer')):
            conn.execute(users.insert().values(username=name, role=role,
                                               password_hash=hash_password('pw')))
    from src.services import domain, workflow
    return engine, domain, workflow


@pytest.fixture()
def client(services):
    from fastapi.testclient import TestClient
    from src.main import app
    return TestClient(app)


@pytest.fixture()
def auth_headers(client):
    def make(name):
        response = client.post('/login', json={'username': name, 'password': 'pw'})
        assert response.status_code == 200
        return {'Authorization': f"Bearer {response.json()['token']}"}
    return make


@pytest.fixture()
def sample(services):
    import copy
    _, domain, _ = services
    return copy.deepcopy(domain.SPEC['sample'])
