"""라이브 탐침 — 이 저장소의 상수를 **다시 잴 수 있게** 남겨 둔다.

docs/LAW_API_GUIDE.md 의 표는 전부 이 스크립트로 나왔다. 문서만 고치고 코드를
안 고치는(또는 그 반대의) 표류를 막으려면 다시 재는 길이 있어야 한다.

    python scripts/probe_api.py envelopes     # 갈래별 목록·본문 봉투 태그
    python scripts/probe_api.py limits        # display·page 상한
    python scripts/probe_api.py failures      # HTTP 200 으로 오는 실패 봉투 4종
    python scripts/probe_api.py htmlonly      # lsHistory·couseLs 가 XML 을 주는가
    python scripts/probe_api.py all

⚠️ **호출은 사용자 계정으로 나간다.** 필요한 것만 재고, throttle 을 지킨다.
   전수 조사(갈래 30종 × 검색어)는 이미 2026-09-08 에 끝났다 — 되풀이하지 말 것.
"""
from __future__ import annotations

import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from law_mcp.config import (  # noqa: E402
    HTML_ONLY_TARGETS, SEARCH_URL, SERVICE_URL, TARGETS, get_oc, use_os_trust)

THROTTLE = 0.6
_session = requests.Session()
_session.headers["User-Agent"] = "law-openapi-mcp-probe (+github.com/rubatoyd/law-openapi-mcp)"


def call(url: str, **params) -> requests.Response:
    oc = get_oc()
    if not oc:
        raise SystemExit("LAW_OC 미설정 — .env 또는 환경변수로 주세요.")
    r = _session.get(url, params={"OC": oc, "type": "XML", **params}, timeout=30)
    time.sleep(THROTTLE)
    return r


def _root(resp: requests.Response):
    try:
        return ET.fromstring(resp.content)
    except ET.ParseError:
        return None


def envelopes() -> dict:
    """갈래마다 루트 태그·레코드 태그·식별자 파라미터가 다르다 — 그 표를 다시 뜬다."""
    out = {}
    for code, t in TARGETS.items():
        r = call(SEARCH_URL, target=code, query="교육", display=3)
        root = _root(r)
        e: dict = {"http": r.status_code, "bytes": len(r.content),
                   "ctype": r.headers.get("Content-Type", "")}
        if root is None:
            e["parse"] = "실패(HTML 이거나 빈 응답)"
            out[code] = e
            continue
        e["list_root"] = root.tag
        e["list_root_expected"] = t.list_root
        e["totalCnt"] = root.findtext("./totalCnt")
        recs = root.findall(f"./{t.record_tag}")
        e["record_tag_expected"] = t.record_tag
        e["records_found"] = len(recs)
        e["all_child_tags"] = list(dict.fromkeys(c.tag for c in root))
        if recs:
            e["fields"] = [c.tag for c in recs[0]]
            ident = recs[0].findtext(t.id_field)
            e["id_field"] = t.id_field
            e["id_value"] = ident
            if ident:
                rb = call(SERVICE_URL, target=code, **{t.id_param: ident})
                rb_root = _root(rb)
                e["body_http"] = rb.status_code
                e["body_bytes"] = len(rb.content)
                e["body_root"] = rb_root.tag if rb_root is not None else "(파싱실패)"
                e["body_root_expected"] = t.body_root
        out[code] = e
        print(f"[{code}] list<{e.get('list_root')}> rec×{e.get('records_found')} "
              f"body<{e.get('body_root')}>", file=sys.stderr)
    return out


def limits() -> dict:
    """display 상한과 page 하드 상한. ordin('교육' 8,517건)을 자로 쓴다."""
    out: dict = {"display": {}, "page": {}}
    for d in (100, 300, 500, 1000):
        root = _root(call(SEARCH_URL, target="ordin", query="교육", display=d))
        out["display"][str(d)] = {
            "numOfRows_echo": root.findtext("./numOfRows"),
            "records": len(root.findall("./law")),
        }
    for pg in (2, 50, 86, 200):
        root = _root(call(SEARCH_URL, target="ordin", query="교육",
                          display=100, page=pg))
        out["page"][str(pg)] = {
            "page_echo": root.findtext("./page"),
            "records": len(root.findall("./law")),
            "totalCnt": root.findtext("./totalCnt"),
        }
    return out


def failures() -> dict:
    """🔴 실패가 전부 HTTP 200 이다 — 네 가지를 다시 확인한다."""
    out = {}
    oc = get_oc()

    def raw(url, **p):
        r = _session.get(url, params=p, timeout=30)
        time.sleep(THROTTLE)
        return {"http": r.status_code, "bytes": len(r.content),
                "ctype": r.headers.get("Content-Type", ""),
                "head": r.content[:220].decode("utf-8", "replace")}

    out["bad_target"] = raw(SEARCH_URL, OC=oc, type="XML", target="zzzz", query="교육")
    out["bad_oc"] = raw(SEARCH_URL, OC="zzzznotreal", type="XML", target="law", query="교육")
    out["no_oc"] = raw(SEARCH_URL, type="XML", target="law", query="교육")
    out["bad_id"] = raw(SERVICE_URL, OC=oc, type="XML", target="law", MST="99999999")
    # 🔴 query 를 빼면 오류가 아니라 전체 카탈로그가 온다
    out["no_query"] = raw(SEARCH_URL, OC=oc, type="XML", target="law")
    return out


def htmlonly() -> dict:
    """lsHistory·couseLs 가 정말 XML 을 안 주는가(문서가 아니라 응답으로 확인)."""
    out = {}
    for code in HTML_ONLY_TARGETS:
        for label, url, extra in (("lawSearch", SEARCH_URL, {"query": "교육"}),
                                  ("lawService", SERVICE_URL, {"MST": "209959"})):
            r = call(url, target=code, **extra)
            head = r.content[:120].decode("utf-8", "replace")
            out[f"{code}/{label}"] = {
                "http": r.status_code, "bytes": len(r.content),
                "ctype": r.headers.get("Content-Type", ""),
                "is_html": head.lstrip().lower().startswith(("<!doctype", "<html")),
            }
    return out


COMMANDS = {"envelopes": envelopes, "limits": limits,
            "failures": failures, "htmlonly": htmlonly}


def main(argv: list[str]) -> int:
    use_os_trust()
    what = argv[0] if argv else "all"
    names = list(COMMANDS) if what == "all" else [what]
    if any(n not in COMMANDS for n in names):
        print(f"사용법: probe_api.py [{'|'.join(COMMANDS)}|all]", file=sys.stderr)
        return 2
    result = {n: COMMANDS[n]() for n in names}
    out_dir = Path("probe-out")
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"probe_{what}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n저장: {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
