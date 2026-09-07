"""법제처 국가법령정보 MCP 서버 (FastMCP).

⚠️ `mcp.server.fastmcp` 를 **조건부 import 하지 않는다.** mcp 2.0 은 이 모듈을 제거했으므로
   폴백을 두면 반쯤 동작하는 서버가 조용히 뜬다. pyproject 의 `mcp>=1.2.0,<2` 상한이
   유일한 방어선이고, 여기서는 실패를 시끄럽게 내는 편이 옳다.
   (자매 저장소 kci·scienceon·nl 이 이 상한 누락으로 각각 기동 불능을 겪었다.)
"""
from __future__ import annotations

import argparse
import functools
import os
import sys

from mcp.server.fastmcp import FastMCP

from .client import LawClient, LawError
from .config import (
    DEFAULT_DISPLAY,
    HTML_ONLY_TARGETS,
    MAX_CALLS_PER_TOOL_CALL,
    MAX_DISPLAY,
    MINISTRY_EXPC_NOTE,
    target_groups,
    TARGETS,
    get_oc,
    scrub,
)
from .exporters import export
from .models import COLUMNS
from .parser import NotFound

mcp = FastMCP("law")


def _safe(fn):
    """도구는 **항상 JSON 직렬화 가능한 dict** 를 반환 — 예외 누수 금지."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            return {"error": scrub(f"{type(e).__name__}: {e}")}
    return wrapper


_READ = {"readOnlyHint": True, "openWorldHint": True}
_WRITE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}

_NO_OC = {
    "error": "LAW_OC 미설정 — 법제처 OPEN API 는 `OC` 로 인증합니다.",
    "hint": "https://open.law.go.kr 에서 OPEN API 를 신청할 때 지정한 값"
            "(가입 이메일의 @ 앞부분)을 환경변수 LAW_OC 로 설정하세요. 비밀값이 아닙니다.",
}


def _budget_guard(max_records: int, page_size: int | None, n_axes: int = 1):
    """예상 호출 수가 상한을 넘으면 **호출 전에** 거부한다(실행 후 후회 방지)."""
    size = min(max(1, page_size or DEFAULT_DISPLAY), MAX_DISPLAY)
    est = max(1, -(-max(1, int(max_records)) // size)) * max(1, n_axes)
    if est <= MAX_CALLS_PER_TOOL_CALL:
        return None
    return {
        "error": f"이 요청은 최대 약 {est:,}회 API 호출이 필요합니다 — 한 번의 도구 호출 "
                 f"상한({MAX_CALLS_PER_TOOL_CALL:,}회)을 넘습니다.",
        "hint": "max_records 를 줄이거나, 축(targets×queries)을 나눠 여러 번 호출하거나, "
                f"page_size 를 키우세요(최대 {MAX_DISPLAY}).",
        "estimated_calls": est, "limit": MAX_CALLS_PER_TOOL_CALL,
    }


@mcp.tool(annotations=_READ)
@_safe
def law_status() -> dict:
    """연결 점검 — `OC` 보유 여부 + 법제처 OPEN API 실제 왕복 1회."""
    if not get_oc():
        return {**_NO_OC, "ok": False, "has_oc": False}
    return LawClient().status()


@mcp.tool(annotations=_READ)
@_safe
def law_targets() -> dict:
    """다룰 수 있는 갈래와 갈래별 실측 스키마·주의사항.

    갈래마다 응답 태그와 식별자 파라미터가 다르고 **이름에서 유추할 수 없다** —
    이 도구가 그 표다.
    """
    return {
        "수집_단위": "법령 하나가 문헌 하나다. 조문은 인용 시 위치로 넣지, "
                     "레코드로 쪼개지 않는다. 본문이 필요하면 law_body 를 쓴다.",
        # ⚠️ 72종을 평평하게 늘어놓으면 호출자가 고를 수 없고 응답도 길어진다.
        #    묶음별로 코드와 이름만 주고, 세부 스키마는 필요할 때 쓰도록 따로 둔다.
        "갈래": {
            g: {k: TARGETS[k].label for k in codes}
            for g, codes in target_groups().items()
        },
        "갈래_수": len(TARGETS),
        "본문_없는_갈래": {k: t.label for k, t in TARGETS.items() if not t.has_body},
        "다루지_않는_target": HTML_ONLY_TARGETS,
        "부처_법령해석": MINISTRY_EXPC_NOTE,
        "한계": {
            "display_상한": MAX_DISPLAY,
            "page_상한": "없음 — totalCnt 전량 회수 가능(실측)",
            "도구_호출당_요청_상한": MAX_CALLS_PER_TOOL_CALL,
        },
        "주의": [
            "🔴 모든 실패가 HTTP 200 이다. 없는 target 은 0바이트, 잘못된 OC 는 "
            "<Response>, 없는 식별자는 <Law>일치하는 … 없습니다</Law> 로 온다.",
            "🔴 query 를 비우면 오류가 아니라 전체 카탈로그가 온다"
            "(현행법령 5,614건). 이 서버는 빈 검색어를 거부한다.",
            "🔴 판례 본문은 데이터출처에 따라 없다 — 데이터출처명=대법원 은 본문이 오고, "
            "국세법령정보시스템 은 목록에만 있다. 결손이지 오류가 아니다.",
        ],
        "표_열": COLUMNS,
    }


@mcp.tool(annotations=_READ)
@_safe
def law_search(target: str, query: str, max_records: int = 50,
               page_size: int | None = None, scope: int = 1,
               allow_full_catalog: bool = False) -> dict:
    """법령·판례 등 한 갈래를 검색한다.

    Args:
        target: 갈래 코드. law(현행법령)·admrul(행정규칙)·ordin(자치법규)·prec(판례)·
            detc(헌재결정례)·expc(법령해석례)·trty(조약)·eflaw·elaw·lsStmd.
            `law_targets` 로 전체 목록을 볼 수 있다.
        query: 검색어. **비울 수 없다** — 비우면 전체 카탈로그가 온다.
        max_records: 회수 상한(예산). 이 API 는 page 상한이 없어 올리면 전량도 받는다.
        page_size: 한 페이지 건수(최대 500).
        scope: 1=제목만(기본), 2=본문 포함.
        allow_full_catalog: query="*" 로 갈래 전체를 받겠다고 명시할 때만 True.
    """
    if not get_oc():
        return _NO_OC
    guard = _budget_guard(max_records, page_size)
    if guard:
        return guard
    recs, meta = LawClient().search(
        target, query, max_records=max_records, page_size=page_size,
        scope=scope, allow_full_catalog=allow_full_catalog)
    return {
        "records": [{**r.to_row(), "unmapped": r.unmapped()} for r in recs],
        "meta": meta,
    }


@mcp.tool(annotations=_READ)
@_safe
def law_body(target: str, doc_id: str, include_articles: bool = True,
             max_chars: int = 40_000, ef_date: str | None = None) -> dict:
    """식별자 1건의 본문을 받는다(조문·판시사항·질의요지 등).

    Args:
        target: 갈래 코드.
        doc_id: 목록 결과의 일련번호. 갈래마다 파라미터명이 MST/ID 로 다르지만
            이 도구가 알아서 맞춘다.
        include_articles: 조문 목록을 함께 돌려줄지(법령·자치법규에만 있다).
        ef_date: 시행일법령(eflaw) 전용 — 목록의 `시행일자`. 🔴 없이 부르면 오류가
            아니라 HTML 이 온다. 같은 법령의 시행일별 판본이라 (MST, efYd) 가 신원이다.
        max_chars: 본문 텍스트 상한. 넘으면 잘라내고 그 사실을 알린다.
    """
    if not get_oc():
        return _NO_OC
    try:
        content, meta = LawClient().body(target, doc_id, ef_date=ef_date)
    except NotFound as e:
        # 🔴 오류가 아니라 사실인 경우가 있다 — 호출자가 구분할 수 있게 표시해 돌려준다.
        return {
            "found": False, "reason": str(e),
            "note": "이 API 는 목록에는 있으나 본문이 없는 문헌이 있습니다"
                    "(실측: 데이터출처명=국세법령정보시스템 인 판례). 결손으로 "
                    "기록하고 넘어가는 것이 맞습니다.",
        }
    text = content.get("text") or ""
    out = {
        "found": True,
        "fields": content["fields"],
        "dates_normalized": content["dates_normalized"],
        "attachments": content.get("attachments") or [],
        "meta": meta,
    }
    if len(text) > max_chars:
        out["text"] = text[:max_chars]
        out["text_truncated"] = (
            f"본문이 {len(text):,}자여서 {max_chars:,}자까지만 실었습니다 — "
            f"max_chars 를 올리거나 articles 로 필요한 조문만 보세요.")
    else:
        out["text"] = text
    if include_articles:
        out["articles"] = content.get("articles") or []
        out["articles_note"] = (
            "`구분`='전문' 은 장·절 표제이지 조문이 아닙니다. `가지번호` 가 있으면 "
            "제N조의M 입니다(인용 위치 표기에 씁니다).")
    return out


@mcp.tool(annotations=_WRITE)
@_safe
def law_collect(targets: list[str], queries: list[str], out_dir: str,
                name: str = "law_collect", formats: list[str] | None = None,
                max_records: int = 200, page_size: int | None = None,
                scope: int = 1) -> dict:
    """갈래 × 검색어의 합집합을 모아 파일로 저장한다.

    ⚠️ `max_records` 는 **전체에 걸친 예산**이다. 앞선 축이 다 쓰면 뒤 축은 조회되지
       않으며, 그 사실은 meta 의 `stopped_early_note` 로 보고된다.
    ⚠️ 한 축이 실패해도 나머지는 계속 수집한다 — 실패는 `failed_axes` 로 보고된다.
    """
    if not get_oc():
        return _NO_OC
    formats = formats or ["xlsx", "json"]
    n_axes = max(1, len(targets or [])) * max(1, len(queries or []))
    guard = _budget_guard(max_records, page_size, n_axes)
    if guard:
        return guard

    recs, meta = LawClient().collect(
        targets, queries, max_records=max_records, page_size=page_size, scope=scope)
    paths = export(recs, formats, out_dir, name)
    return {
        "saved": paths, "count": len(recs), "meta": meta,
        "columns_note": "정규화 열 뒤에 원본 필드가 그대로 열로 붙습니다 — "
                        "매핑되지 않은 값도 파일에서 볼 수 있습니다.",
    }


@mcp.tool(annotations=_READ)
@_safe
def law_citation(target: str, doc_id: str) -> dict:
    """한 건을 서지(인용) 필드로 매핑한다 — 발령주체·호·공포일·시행일·제정기관.

    목록에서 1건을 다시 찾아 매핑한다. 서지관리 도구(Ibis 의 `legislation` 유형 등)로
    바로 넘길 수 있는 모양이다.
    """
    if not get_oc():
        return _NO_OC
    client = LawClient()
    content, meta = client.body(target, doc_id)
    f = content["fields"]
    tgt = TARGETS[target.strip()]

    def pick(*names: str) -> str:
        for n in names:
            if f.get(n):
                return f[n]
        return ""

    d = content["dates_normalized"]
    return {
        "citation": {
            "title": pick("법령명_한글", "법령명한글", "자치법규명", "행정규칙명",
                          "사건명", "안건명", "조약명_한글"),
            "발령주체": pick("소관부처", "소관부처명", "지자체기관명", "법원명",
                             "해석기관명", "상위부처명"),
            "제정기관": pick("소관부처", "소관부처명", "지자체기관명", "해석기관명"),
            "호": pick("공포번호", "발령번호", "사건번호", "안건번호", "조약번호"),
            "공포일": d.get("공포일자") or d.get("발령일자") or d.get("선고일자")
                      or d.get("종국일자") or d.get("해석일자") or d.get("서명일자", ""),
            "시행일": d.get("시행일자") or d.get("발효일자", ""),
            "종류": pick("법종구분", "행정규칙종류", "자치법규종류", "사건종류명") or tgt.label,
            "제개정": pick("제개정구분", "제개정구분명", "제개정정보"),
            "url": f"https://www.law.go.kr/DRF/lawService.do?target={tgt.code}"
                   f"&{tgt.id_param}={doc_id}&type=HTML",
        },
        "note": "조문은 문헌이 아니라 **인용 위치**다 — 「초·중등교육법」 제23조처럼 "
                "인용문에 붙이고, 서지 항목은 법령 하나로 둔다.",
        "meta": meta,
    }


def _env_port(name: str) -> int | None:
    raw = (os.environ.get(name) or "").strip()
    return int(raw) if raw.isdigit() else None


def main(argv: list[str] | None = None) -> None:
    """⚠️ 기본 전송은 **stdio 로 못박는다** — 바뀌면 기존 MCP 등록이 전부 죽는다."""
    parser = argparse.ArgumentParser(prog="law-mcp", add_help=True)
    parser.add_argument("--transport", default=os.environ.get("LAW_MCP_TRANSPORT", "stdio"),
                        choices=["stdio", "sse", "streamable-http"])
    parser.add_argument("--host", default=os.environ.get("LAW_MCP_HOST"))
    parser.add_argument("--port", type=int, default=_env_port("LAW_MCP_PORT"))
    args, _unknown = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    if args.host:
        mcp.settings.host = args.host
    if args.port:
        mcp.settings.port = args.port
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
