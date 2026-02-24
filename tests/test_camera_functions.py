import pytest
from contextlib import contextmanager
from datetime import datetime, timezone

import ingest.main as main
from fastapi import HTTPException


class FakeCursor:
    def __init__(self, results=None):
        self._results = results or []
        self._fetch_index = 0
        self.executed = []
        self.rowcount = 0

    def execute(self, query, params=None):
        # record the statement and optionally provide a fake rowcount
        self.executed.append((query.strip(), params))
        # for update/delete statements, simulate a rowcount >0
        if query.strip().upper().startswith("UPDATE"):
            self.rowcount = 1

    def fetchone(self):
        if self._fetch_index < len(self._results):
            r = self._results[self._fetch_index]
            self._fetch_index += 1
            return r
        return None

    def fetchall(self):
        return list(self._results)

    def fetchmany(self, n):
        batch = self._results[self._fetch_index : self._fetch_index + n]
        self._fetch_index += len(batch)
        return batch


class DummyConn:
    def __init__(self, cursor: FakeCursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def make_fake_conn(cursor: FakeCursor):
    @contextmanager
    def fc():
        yield DummyConn(cursor)
    return fc


# ---------- tests for helpers ----------

def test_get_camera_row_none(monkeypatch):
    # simulate no row returned
    cur = FakeCursor(results=[None])
    monkeypatch.setattr(main, "_conn", make_fake_conn(cur))
    assert main.get_camera_row("x") is None


def test_get_camera_row_happy(monkeypatch):
    now = datetime.now(timezone.utc)
    row = (1, "cam1", "My cam", True, "criticidade", 2.5, now, "1.2.3.4")
    cur = FakeCursor(results=[row])
    monkeypatch.setattr(main, "_conn", make_fake_conn(cur))

    got = main.get_camera_row("cam1")
    assert got["id"] == 1
    assert got["camera_id"] == "cam1"
    assert got["nome"] == "My cam"
    assert got["ativa"] is True
    assert got["criticidade"] == "CRITICIDADE"
    assert isinstance(got["peso"], float) and got["peso"] == 2.5
    assert got["peso_score"] == 2.5
    assert got["ip"] == "1.2.3.4"
    assert got["created_at"] == now.isoformat()


def test_ensure_camera_exists_creates(monkeypatch):
    # first call to get_camera_row returns None; second returns a dummy
    calls = {"count": 0}

    def fake_get_camera_row(cam_id):
        calls["count"] += 1
        if calls["count"] == 1:
            return None
        return {
            "camera_id": cam_id,
            "nome": "CAM X",
            "ativa": True,
            "criticidade": "NORMAL",
            "peso": 1.0,
            "peso_score": 1.0,
            "ip": "1.2.3.3",
        }

    monkeypatch.setattr(main, "get_camera_row", fake_get_camera_row)

    # our fake cursor should capture the INSERT
    cur = FakeCursor()
    monkeypatch.setattr(main, "_conn", make_fake_conn(cur))

    res = main.ensure_camera_exists("abc123", default_name="foo", ip="1.2.3.3")
    assert res["camera_id"] == "abc123"
    assert any("INSERT INTO cameras" in q for q, _ in cur.executed)


def test_ensure_camera_exists_updates_ip(monkeypatch):
    orig = {"camera_id": "camA", "nome": "CAM A", "ativa": True, "criticidade": "NORMAL", "peso": 1.0, "peso_score": 1.0, "ip": None}
    monkeypatch.setattr(main, "get_camera_row", lambda cid: orig)

    cur = FakeCursor()
    monkeypatch.setattr(main, "_conn", make_fake_conn(cur))

    res = main.ensure_camera_exists("camA", ip="9.9.9.9")
    # should return same row but ip now set externally
    assert res == orig
    # update query executed
    assert any("UPDATE cameras SET ip" in q for q, _ in cur.executed)


# ---------- tests for API endpoints ----------

class DummyRequest:
    def __init__(self, data):
        self._data = data
        self.headers = {}
        self.client = None

    async def json(self):
        return self._data


@ pytest.mark.asyncio
async def test_create_camera_validation(monkeypatch):
    req = DummyRequest({"camera_id": "", "nome": ""})
    with pytest.raises(HTTPException):
        await main.create_camera(req)

    req = DummyRequest({"camera_id": "x", "nome": "y", "criticidade": "bad"})
    with pytest.raises(HTTPException):
        await main.create_camera(req)

    req = DummyRequest({"camera_id": "x", "nome": "y", "peso_score": 0})
    with pytest.raises(HTTPException):
        await main.create_camera(req)


@ pytest.mark.asyncio
async def test_create_camera_success(monkeypatch):
    # make DB do nothing and return a fake row via get_camera_row
    monkeypatch.setattr(main, "get_camera_row", lambda cid: {"camera_id": cid})
    cur = FakeCursor()
    monkeypatch.setattr(main, "_conn", make_fake_conn(cur))

    req = DummyRequest({"camera_id": "C1", "nome": "Name", "criticidade": "NORMAL", "peso_score": 2.3, "ip": "1.1.1.1"})
    result = await main.create_camera(req)
    assert result["ok"] is True
    assert result["camera"]["camera_id"] == "C1"
    assert any("ON CONFLICT" in q for q, _ in cur.executed)


@ pytest.mark.asyncio
async def test_update_camera_not_found(monkeypatch):
    cur = FakeCursor(results=[None])
    monkeypatch.setattr(main, "_conn", make_fake_conn(cur))
    req = DummyRequest({})
    with pytest.raises(HTTPException) as exc:
        await main.update_camera(123, req)
    assert exc.value.status_code == 404


@ pytest.mark.asyncio
async def test_update_camera_valid(monkeypatch):
    # simulate existing camera
    cur = FakeCursor(results=[(1,)])
    monkeypatch.setattr(main, "_conn", make_fake_conn(cur))
    # later select returns full row
    final_row = (123, "abc", "nome", True, "NORMAL", 1.5, datetime.now(timezone.utc), "ip")
    cur2 = FakeCursor(results=[final_row])

    # hack: need _conn to return different cursors for first/second with blocks
    seq = [cur, cur2]
    def _conn_gen():
        @contextmanager
        def c():
            yield DummyConn(seq.pop(0))
        return c()
    monkeypatch.setattr(main, "_conn", _conn_gen)

    req = DummyRequest({"nome": "new", "criticidade": "CRITICA", "peso": 2.0, "ativa": False, "ip": "10.0.0.1"})
    out = await main.update_camera(123, req)
    assert out["id"] == 123
    assert out["nome"] == "nome" or out["camera_id"] == "abc"
    # ensure update query executed with fields
    assert any("UPDATE cameras SET" in q for q, _ in cur.executed)


def test_delete_camera(monkeypatch):
    cur = FakeCursor()
    monkeypatch.setattr(main, "_conn", make_fake_conn(cur))
    out = main.delete_camera(55)
    assert out == {"ok": True}
    assert any("DELETE FROM cameras" in q for q, _ in cur.executed)
