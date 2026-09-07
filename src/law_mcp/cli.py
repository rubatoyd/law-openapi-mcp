"""명령줄 인터페이스 — MCP 서버와 같은 코어를 쓴다.

    law status
    law targets
    law search --target law --query 교육
    law body   --target law --id 209959
    law collect --target law,prec --query 교육,평생교육 --format xlsx,json
"""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .client import LawClient, LawError
from .config import DEFAULT_DISPLAY, HTML_ONLY_TARGETS, MAX_DISPLAY, TARGETS, get_oc
from .exporters import export
from .parser import NotFound


def _split(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]


def _dump(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_status(args) -> int:
    info = LawClient().status()
    _dump(info)
    return 0 if info.get("ok") else 1


def cmd_targets(args) -> int:
    from .config import target_groups
    total = len(TARGETS)
    for group, codes in target_groups().items():
        print(f"\n[{group}] {len(codes)}종")
        for k in codes:
            t = TARGETS[k]
            body = t.id_param if t.has_body else "본문없음"
            print(f"  {k:<18} {t.label:<24} {body}")
    print(f"\n총 {total}종.")
    print("다루지 않는 target (XML 을 주지 않는다 — 실측):")
    for k, why in HTML_ONLY_TARGETS.items():
        print(f"  {k}: {why}")
    return 0


def cmd_search(args) -> int:
    recs, meta = LawClient().search(
        args.target, args.query, max_records=args.max_records,
        page_size=args.page_size, scope=args.scope,
        allow_full_catalog=args.allow_full_catalog)
    if args.json:
        _dump({"records": [r.to_row() for r in recs], "meta": meta})
        return 0
    print(f"[{meta['target_label']}] '{meta['query']}' — "
          f"total {meta.get('total', 0):,}건 중 {len(recs):,}건 회수")
    for r in recs:
        bits = [r.doc_id, r.title]
        tail = " · ".join(x for x in (r.authority, r.kind, r.promulgated) if x)
        print(f"  {bits[0]:>14s}  {bits[1][:52]}")
        if tail:
            print(f"  {'':>14s}  {tail}")
    for key in ("truncated_note", "early_stop_note", "incomplete_note",
                "page_size_note", "error"):
        if meta.get(key):
            print(f"\n  [!] {meta[key]}")
    return 0


def cmd_body(args) -> int:
    try:
        content, meta = LawClient().body(args.target, args.id, ef_date=args.ef_date)
    except NotFound as e:
        print(f"[본문 없음] {e}")
        print("  이 API 는 목록에는 있으나 본문이 없는 문헌이 있습니다"
              "(실측: 데이터출처명=국세법령정보시스템 인 판례).")
        return 2
    if args.json:
        _dump({"content": content, "meta": meta})
        return 0
    print(content["text"][:args.max_chars])
    if len(content["text"]) > args.max_chars:
        print(f"\n… (전체 {len(content['text']):,}자 중 {args.max_chars:,}자만 표시)")
    arts = content.get("articles") or []
    if arts:
        real = [a for a in arts if a.get("구분") != "전문"]
        print(f"\n조문 {len(real)}개 (장·절 표제 {len(arts) - len(real)}개 별도)")
    if content.get("attachments"):
        print(f"첨부 {len(content['attachments'])}개")
    return 0


def cmd_collect(args) -> int:
    recs, meta = LawClient().collect(
        _split(args.target), _split(args.query), max_records=args.max_records,
        page_size=args.page_size, scope=args.scope)
    paths = export(recs, _split(args.format) or ["xlsx"], args.out_dir, args.name)
    print(f"{len(recs):,}건 수집 · API 호출 {meta.get('api_calls', 0)}회")
    for p in paths:
        print(f"  저장: {p}")
    for key in ("stopped_early_note", "failed_axes_note", "truncated_note",
                "early_stop_note", "incomplete_note"):
        if meta.get(key):
            print(f"  [!] {meta[key]}")
    if args.json:
        _dump(meta)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="law", description=__doc__.splitlines()[0])
    p.add_argument("--version", action="version", version=f"law-openapi-mcp {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="연결 점검").set_defaults(func=cmd_status)
    sub.add_parser("targets", help="다룰 수 있는 갈래").set_defaults(func=cmd_targets)

    def common(sp):
        sp.add_argument("--page-size", type=int, default=None,
                        help=f"한 페이지 건수 (최대 {MAX_DISPLAY}, 기본 {DEFAULT_DISPLAY})")
        sp.add_argument("--scope", type=int, default=1, choices=[1, 2],
                        help="1=제목만(기본), 2=본문 포함")
        sp.add_argument("--json", action="store_true", help="JSON 으로 출력")

    s = sub.add_parser("search", help="한 갈래 검색")
    s.add_argument("--target", required=True)
    s.add_argument("--query", required=True)
    s.add_argument("--max-records", type=int, default=50)
    s.add_argument("--allow-full-catalog", action="store_true",
                   help='query="*" 로 갈래 전체를 받겠다고 명시')
    common(s)
    s.set_defaults(func=cmd_search)

    b = sub.add_parser("body", help="식별자 1건의 본문")
    b.add_argument("--target", required=True)
    b.add_argument("--id", required=True, help="목록 결과의 일련번호")
    b.add_argument("--ef-date", default=None,
                   help="시행일법령(eflaw) 전용 — 목록의 시행일자(YYYYMMDD)")
    b.add_argument("--max-chars", type=int, default=8000)
    b.add_argument("--json", action="store_true")
    b.set_defaults(func=cmd_body)

    c = sub.add_parser("collect", help="갈래 × 검색어 합집합 수집")
    c.add_argument("--target", required=True, help="쉼표로 여럿")
    c.add_argument("--query", required=True, help="쉼표로 여럿")
    c.add_argument("--out-dir", default="output")
    c.add_argument("--name", default="law_collect")
    c.add_argument("--format", default="xlsx,json")
    c.add_argument("--max-records", type=int, default=200)
    common(c)
    c.set_defaults(func=cmd_collect)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    if args.cmd != "targets" and not get_oc():
        print("LAW_OC 미설정 — open.law.go.kr 에서 OPEN API 신청 시 지정한 값"
              "(가입 이메일의 @ 앞부분)을 .env 또는 환경변수 LAW_OC 로 주세요.",
              file=sys.stderr)
        return 1
    try:
        return args.func(args)
    except (LawError, ValueError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
