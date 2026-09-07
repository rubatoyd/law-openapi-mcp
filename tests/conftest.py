from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def fx():
    """실응답 픽스처 로더.

    `tests/fixtures/*.xml` 은 2026-09-08 에 라이브로 받은 **진짜 응답**이다
    (OC 값만 `__OC__` 로 가렸다). 손으로 지어낸 표본이 아니므로 여기 있는 태그·필드는
    전부 실제로 관측된 것이다.
    """
    def load(name: str) -> bytes:
        return (FIXTURES / name).read_bytes()
    return load


@pytest.fixture(autouse=True)
def _no_real_oc(monkeypatch):
    """테스트가 실수로 라이브 호출을 하지 않도록 OC 를 지운다.

    (클라이언트는 OC 가 없으면 호출 전에 LawError 를 낸다.)
    """
    for k in ("LAW_OC", "LAW_API_OC", "MOLEG_OC"):
        monkeypatch.delenv(k, raising=False)
