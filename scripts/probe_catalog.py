"""후보 target 을 실측해 레지스트리 재료를 뽑는다 (1회성이지만 커밋한다).

`docs/DRF_CATALOG.md` 는 **문서에 무엇이 있는지**까지다. 실제 응답의 루트 태그·레코드
태그·식별자 파라미터는 갈래마다 다르고 **이름에서 유추할 수 없다**(GUIDE §3 함정 일곱).
그래서 레지스트리에 넣기 전에 여기서 한 번 잰다.

    python scripts/probe_catalog.py            # 후보 전체
    python scripts/probe_catalog.py decc lstrm # 지정한 것만

결과는 `probe-out/catalog.json` 에 저장하고, 레지스트리에 붙여 넣을 파이썬 조각을
표준출력으로 낸다.

🔑 **본문 파라미터는 짐작하지 않는다** — 목록 레코드의 `…상세링크` 가
`/DRF/lawService.do?OC=…&target=prec&ID=621039&type=HTML` 처럼 **파라미터 이름을 그대로
담고 있다**. 거기서 읽는다.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from law_mcp.config import SEARCH_URL, SERVICE_URL, get_oc, use_os_trust  # noqa: E402

THROTTLE = 0.55
_s = requests.Session()
_s.headers["User-Agent"] = "law-openapi-mcp-probe (+github.com/rubatoyd/law-openapi-mcp)"

# 봉투 필드(레코드가 아닌 것) — 레코드 태그를 골라낼 때 제외한다.
# ⚠️ `기관명` 은 레코드가 아니라 **봉투 필드**다(위원회 갈래). 넣지 않으면 결과가
#    1건일 때 '가장 많이 반복되는 자식' 규칙이 `기관명` 을 레코드로 오인한다 — 실제로 그랬다.
ENVELOPE_TAGS = {"target", "키워드", "section", "totalCnt", "page", "numOfRows",
                 "resultCode", "resultMsg", "totalCount", "keyword", "기관명",
                 "위원회명", "sort", "display"}

# 인용 가능한 문헌만 — 연계·분석 갈래는 범위 밖이다(docs/DRF_CATALOG.md 참조).
MINISTRY = [
    ("moeCgmExpc", "교육부 법령해석"), ("moelCgmExpc", "고용노동부 법령해석"),
    ("molitCgmExpc", "국토교통부 법령해석"), ("moefCgmExpc", "재정경제부 법령해석"),
    ("mofCgmExpc", "해양수산부 법령해석"), ("moisCgmExpc", "행정안전부 법령해석"),
    ("meCgmExpc", "기후에너지환경부 법령해석"), ("kcsCgmExpc", "관세청 법령해석"),
    ("ntsCgmExpc", "국세청 법령해석"), ("msitCgmExpc", "과학기술정보통신부 법령해석"),
    ("mpvaCgmExpc", "국가보훈부 법령해석"), ("mndCgmExpc", "국방부 법령해석"),
    ("mafraCgmExpc", "농림축산식품부 법령해석"), ("mcstCgmExpc", "문화체육관광부 법령해석"),
    ("mojCgmExpc", "법무부 법령해석"), ("mohwCgmExpc", "보건복지부 법령해석"),
    ("motieCgmExpc", "산업통상부 법령해석"), ("mogefCgmExpc", "성평등가족부 법령해석"),
    ("mofaCgmExpc", "외교부 법령해석"), ("mssCgmExpc", "중소벤처기업부 법령해석"),
    ("mouCgmExpc", "통일부 법령해석"), ("molegCgmExpc", "법제처 법령해석"),
    ("mfdsCgmExpc", "식품의약품안전처 법령해석"), ("mpmCgmExpc", "인사혁신처 법령해석"),
    ("kmaCgmExpc", "기상청 법령해석"), ("khsCgmExpc", "국가유산청 법령해석"),
    ("rdaCgmExpc", "농촌진흥청 법령해석"), ("npaCgmExpc", "경찰청 법령해석"),
    ("dapaCgmExpc", "방위사업청 법령해석"), ("mmaCgmExpc", "병무청 법령해석"),
    ("kfsCgmExpc", "산림청 법령해석"), ("nfaCgmExpc", "소방청 법령해석"),
    ("okaCgmExpc", "재외동포청 법령해석"), ("ppsCgmExpc", "조달청 법령해석"),
    ("kdcaCgmExpc", "질병관리청 법령해석"), ("kostatCgmExpc", "국가데이터처 법령해석"),
    ("kipoCgmExpc", "지식재산처 법령해석"), ("kcgCgmExpc", "해양경찰청 법령해석"),
    ("naaccCgmExpc", "행정중심복합도시건설청 법령해석"),
]

COMMITTEE = [
    ("ppc", "개인정보보호위원회 결정문"), ("eiac", "고용보험심사위원회 결정문"),
    ("ftc", "공정거래위원회 결정문"), ("acr", "국민권익위원회 결정문"),
    ("fsc", "금융위원회 결정문"), ("nlrc", "노동위원회 결정문"),
    ("kcc", "방송미디어통신위원회 결정문"), ("iaciac", "산업재해보상보험재심사위원회 결정문"),
    ("oclt", "중앙토지수용위원회 결정문"), ("ecc", "중앙환경분쟁조정위원회 결정문"),
    ("sfc", "증권선물위원회 결정문"), ("nhrck", "국가인권위원회 결정문"),
]

SPECIAL = [
    ("ttSpecialDecc", "조세심판원"), ("kmstSpecialDecc", "해양안전심판원"),
    ("acrSpecialDecc", "국민권익위원회 특별행정심판"),
    ("adapSpecialDecc", "인사혁신처 소청심사위원회"), ("baiPvcs", "감사원 사전컨설팅"),
]

OTHER = [
    ("decc", "행정심판례"), ("lstrm", "법령용어"), ("school", "학칙·공단·공공기관"),
    ("licbyl", "법령 별표·서식"), ("admbyl", "행정규칙 별표·서식"),
    ("ordinbyl", "자치법규 별표·서식"),
]

CANDIDATES = OTHER + COMMITTEE + SPECIAL + MINISTRY


def call(url: str, **params) -> requests.Response:
    oc = get_oc()
    if not oc:
        raise SystemExit("LAW_OC 미설정")
    r = _s.get(url, params={"OC": oc, "type": "XML", **params}, timeout=30)
    time.sleep(THROTTLE)
    return r


def probe(code: str, label: str, query: str = "교육") -> dict:
    e: dict = {"target": code, "label": label, "query": query}
    r = call(SEARCH_URL, target=code, query=query, display=3)
    e["list_http"] = r.status_code
    e["list_bytes"] = len(r.content)
    head = r.content[:120].lstrip().lower()
    if not r.content.strip():
        e["verdict"] = "빈 응답(0바이트) — 이 OC 로는 없는 target"
        return e
    if head.startswith((b"<!doctype", b"<html")):
        e["verdict"] = "HTML — XML 미지원"
        return e
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as ex:
        e["verdict"] = f"XML 파싱 실패: {ex}"
        return e
    if root.tag == "Response":
        e["verdict"] = "인증/필수값 실패: " + (root.findtext("./result") or "")
        return e

    e["list_root"] = root.tag
    e["totalCnt"] = root.findtext("./totalCnt")
    kids = [c.tag for c in root]
    cand = [t for t in dict.fromkeys(kids) if t not in ENVELOPE_TAGS]
    e["record_tag_candidates"] = cand
    if not cand:
        e["verdict"] = "레코드 태그 없음(결과 0건이거나 봉투만)"
        return e
    # target 코드와 같은 이름의 후보가 있으면 그것이 레코드다(대소문자 무시).
    # 없으면 가장 많이 반복되는 자식. 🔴 반복 수만 보면 결과가 1건일 때 봉투 필드를 고른다.
    same = [t for t in cand if t.lower() == code.lower()]
    rec_tag = same[0] if same else max(
        cand, key=lambda t: sum(1 for c in root if c.tag == t))
    e["record_tag"] = rec_tag
    recs = root.findall(f"./{rec_tag}")
    e["records"] = len(recs)
    if not recs:
        e["verdict"] = "레코드 0건"
        return e
    rec = recs[0]
    e["fields"] = [c.tag for c in rec]

    # 🔑 상세링크에서 본문 파라미터 이름을 **읽는다**(짐작 금지)
    link = ""
    for c in rec:
        if c.tag.endswith("상세링크") or c.tag.endswith("링크"):
            link = (c.text or "").strip()
            break
    e["detail_link"] = link
    id_param = None
    if link:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
        # 🔴 `MST`/`ID` 만 찾으면 안 된다 — `lstrm` 은 **`trmSeqs`** 다(실측).
        #    링크에 실린 파라미터 중 공통 인자가 아닌 것을 식별자로 본다.
        common = {"OC", "target", "type", "mobile", "mobileYn", "efYd", "LM", "chrClsCd"}
        for k, v in q.items():
            if k not in common and v and v[0]:
                id_param = k
                e["id_value_from_link"] = v[0]
                break
    # 식별자 필드 이름 추정: 링크의 값과 같은 값을 가진 필드를 찾는다
    id_field = None
    if e.get("id_value_from_link"):
        for c in rec:
            if (c.text or "").strip() == e["id_value_from_link"]:
                id_field = c.tag
                break
    if not id_field:
        for c in rec:
            if c.tag.endswith("일련번호") and (c.text or "").strip():
                id_field = c.tag
                if not id_param:
                    id_param = "ID"
                e.setdefault("id_value_from_link", (c.text or "").strip())
                break
    e["id_param"] = id_param
    e["id_field"] = id_field

    # 표제 후보
    for c in rec:
        if any(k in c.tag for k in ("명", "제목", "안건")) and (c.text or "").strip():
            e["title_field"] = c.tag
            break

    # 본문
    ident = e.get("id_value_from_link")
    if ident and id_param:
        rb = call(SERVICE_URL, target=code, **{id_param: ident})
        e["body_http"] = rb.status_code
        e["body_bytes"] = len(rb.content)
        bh = rb.content[:120].lstrip().lower()
        if rb.status_code == 404:
            e["body_verdict"] = "HTTP 404 — 본문 없음"
        elif not rb.content.strip():
            e["body_verdict"] = "빈 응답"
        elif bh.startswith((b"<!doctype", b"<html")):
            e["body_verdict"] = "HTML"
        else:
            try:
                bt = ET.fromstring(rb.content)
                e["body_root"] = bt.tag
                e["body_children"] = [c.tag for c in bt][:14]
                if bt.tag == "Law" and len(bt) == 0:
                    e["body_verdict"] = "없음 봉투: " + (bt.text or "")[:40]
                else:
                    e["body_verdict"] = "OK"
            except ET.ParseError as ex:
                e["body_verdict"] = f"파싱 실패 {ex}"
    e["verdict"] = "OK"
    return e


def main(argv: list[str]) -> int:
    use_os_trust()
    # `--query 법` 으로 질의어를 바꾼다. 갈래에 따라 '교육'이 0건인 곳이 많고,
    # **0건은 target 이 무효라는 뜻이 아니다**(실측: totalCnt=0 이면서 봉투는 정상).
    query = "교육"
    if "--query" in argv:
        i = argv.index("--query")
        query = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    wanted = set(argv)
    cands = [(c, l) for c, l in CANDIDATES if not wanted or c in wanted]
    out = []
    for i, (c, l) in enumerate(cands, 1):
        e = probe(c, l, query)
        out.append(e)
        print(f"[{i:>2}/{len(cands)}] {c:<18} {e.get('verdict','?'):<34} "
              f"rec=<{e.get('record_tag','-')}> id={e.get('id_param','-')} "
              f"body=<{e.get('body_root','-')}> {e.get('body_verdict','')}",
              file=sys.stderr)
    Path("probe-out").mkdir(exist_ok=True)
    # ⚠️ 질의어가 파일명이 된다 — `*` 같은 문자는 Windows 에서 못 쓴다(실제로 터졌다).
    from law_mcp.exporters import safe_name
    Path(f"probe-out/catalog_{safe_name(query, fallback='q')}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    ok = [e for e in out if e.get("verdict") == "OK" and e.get("record_tag")]
    print(f"\n# 레지스트리 조각 — 응답한 {len(ok)}/{len(out)}종")
    for e in ok:
        has_body = e.get("body_verdict") == "OK"
        print(f'    "{e["target"]}": Target("{e["target"]}", "{e["label"]}", '
              f'"{e["list_root"]}", "{e["record_tag"]}", "{e.get("id_field")}", '
              f'"{e.get("id_param")}", "{e.get("body_root", "")}", '
              f'"{e.get("title_field", "")}", {has_body}),')
    bad = [e for e in out if e.get("verdict") != "OK"]
    if bad:
        print(f"\n# 응답하지 않은 {len(bad)}종")
        for e in bad:
            print(f'#   {e["target"]:<18} {e["verdict"]}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
