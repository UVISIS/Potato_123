"""
tests/conftest.py — 단위 테스트 공용 설정

핵심:
    · FakeSupabase : 실제 Supabase 없이 메모리 dict 로 동작하는 가짜 클라이언트.
      모든 함수가 사용하는 쿼리 메서드를 지원한다:
        select(count=...) / insert / update / upsert(on_conflict) / delete
        eq / neq / in_ / gte / order / limit / maybe_single / execute / .count
    · db fixture        : 테스트가 seed/검증에 사용할 가짜 클라이언트 인스턴스.
    · _patch_client     : (autouse) functions.* 의 get_client 를 가짜로 자동 교체.

사용 예:
    def test_xxx(db):
        db.seed("aircraft", [{"id": 1, "registration": "HL1254", ...}])
        from functions.csc01.fn1_get_aircraft_info import get_aircraft_info
        result = get_aircraft_info(1)
        assert set(result) == {...}     # 계약(반환 키) 고정
"""

from __future__ import annotations
import sys
import types
import pytest


class _Result:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class FakeQuery:
    def __init__(self, table: str, store: dict):
        self.table = table
        self.store = store
        self._op = "select"
        self._payload = None
        self._on_conflict = None
        self._filters = []          # list of (kind, col, val)
        self._orders = []           # list of (col, desc)
        self._limit = None
        self._single = False
        self._count = False

    # ── 쿼리 빌더 ────────────────────────────────────────────
    def select(self, *args, **kwargs):
        self._op = "select"
        if kwargs.get("count") == "exact":
            self._count = True
        return self

    def insert(self, payload):
        self._op = "insert"; self._payload = payload; return self

    def update(self, payload):
        self._op = "update"; self._payload = payload; return self

    def upsert(self, payload, on_conflict=None):
        self._op = "upsert"; self._payload = payload; self._on_conflict = on_conflict; return self

    def delete(self):
        self._op = "delete"; return self

    def eq(self, col, val):  self._filters.append(("eq", col, val));  return self
    def neq(self, col, val): self._filters.append(("neq", col, val)); return self
    def in_(self, col, val): self._filters.append(("in", col, val));  return self
    def gte(self, col, val): self._filters.append(("gte", col, val)); return self

    def order(self, col, desc=False):
        self._orders.append((col, desc)); return self

    def limit(self, n): self._limit = n; return self
    def maybe_single(self): self._single = True; return self

    # ── 실행 ─────────────────────────────────────────────────
    def _match(self, row) -> bool:
        for kind, col, val in self._filters:
            cell = row.get(col)
            if kind == "eq" and cell != val:
                return False
            if kind == "neq" and cell == val:
                return False
            if kind == "in" and cell not in val:
                return False
            if kind == "gte" and not (cell is not None and cell >= val):
                return False
        return True

    def _seq(self) -> int:
        seqs = self.store.setdefault("_seq", {})
        seqs[self.table] = seqs.get(self.table, 0) + 1
        return seqs[self.table]

    def execute(self):
        rows = self.store.setdefault(self.table, [])

        if self._op == "insert":
            payload = self._payload
            items = payload if isinstance(payload, list) else [payload]
            inserted = []
            for it in items:
                new = dict(it)
                new.setdefault("id", self._seq())
                rows.append(new)
                inserted.append(new)
            return _Result(inserted)

        if self._op == "update":
            updated = []
            for r in rows:
                if self._match(r):
                    r.update(self._payload)
                    updated.append(r)
            return _Result(updated)

        if self._op == "upsert":
            payload = self._payload
            items = payload if isinstance(payload, list) else [payload]
            out = []
            for it in items:
                existing = None
                if self._on_conflict:
                    for r in rows:
                        if r.get(self._on_conflict) == it.get(self._on_conflict):
                            existing = r; break
                if existing:
                    existing.update(it); out.append(existing)
                else:
                    new = dict(it); new.setdefault("id", self._seq())
                    rows.append(new); out.append(new)
            return _Result(out)

        if self._op == "delete":
            keep = [r for r in rows if not self._match(r)]
            removed = len(rows) - len(keep)
            self.store[self.table] = keep
            return _Result([{} for _ in range(removed)])

        # ── select
        out = [r for r in rows if self._match(r)]
        # 정렬 (마지막 지정 키가 1순위가 되도록 역순 stable sort)
        for col, desc in reversed(self._orders):
            out.sort(key=lambda r: (r.get(col) is None, r.get(col)), reverse=desc)
        if self._limit is not None:
            out = out[: self._limit]

        if self._single:
            return _Result(out[0] if out else None)
        return _Result(out, count=(len(out) if self._count else None))


class FakeSupabase:
    def __init__(self):
        self.store: dict = {}

    def seed(self, table: str, rows: list[dict]):
        """테스트용 초기 데이터 적재."""
        self.store.setdefault(table, []).extend([dict(r) for r in rows])

    def rows(self, table: str) -> list[dict]:
        """테스트에서 부수효과(INSERT/UPDATE) 검증용 조회."""
        return self.store.get(table, [])

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(name, self.store)


@pytest.fixture
def db() -> FakeSupabase:
    return FakeSupabase()


@pytest.fixture(autouse=True)
def _patch_client(monkeypatch, db):
    """
    functions.db.get_client + 이미 import 된 functions.* 모듈의 get_client 를
    가짜 클라이언트로 교체한다. (top-level import / 함수 내부 import 모두 커버)
    """
    # functions.db 가 없을 수도 있으니 더미 모듈 보장
    if "functions.db" not in sys.modules:
        mod = types.ModuleType("functions.db")
        mod.get_client = lambda: db
        sys.modules["functions.db"] = mod
    else:
        monkeypatch.setattr(sys.modules["functions.db"], "get_client", lambda: db, raising=False)

    for name, mod in list(sys.modules.items()):
        if name.startswith("functions.") and mod is not None and hasattr(mod, "get_client"):
            monkeypatch.setattr(mod, "get_client", lambda: db, raising=False)

    yield
