"""법제처 DRF 응답 파서.

🔴 **이 API 는 모든 실패를 HTTP 200 으로 돌려준다.** 상태코드로는 아무것도 알 수 없다.
   실측한 실패 봉투 네 가지(2026-09-08):

   | 상황 | HTTP | 본문 |
   |---|---|---|
   | 없는 `target` | 200 | **0바이트** (Content-Type 도 없음) |
   | 잘못된 `OC` | 200 | `<Response><result>사용자 정보 검증에 실패하였습니다.</result><msg>…IP주소…</msg></Response>` |
   | `OC` 누락 | 200 | `<Response><result>필수입력요소 검증에 실패하였습니다.</result>…` |
   | 없는 식별자 | 200 | `<Law>일치하는 법령이 없습니다.  법령명을 확인하여 주십시오.</Law>` |

   특히 마지막은 **target 과 무관하게 루트가 `<Law>`** 다(판례를 조회해도 `<Law>` 로
   "일치하는 판례가 없습니다" 가 온다). 기대 루트만 찾으면 '본문 없음'으로 둔갑한다.

🔴 **빈 응답(0바이트)을 '결과 0건'으로 통과시키지 않는다.** 그것이 이 저장소가 막겠다고
   하는 '조용한 절단'의 이 API 판이다.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from .config import Target, scrub
from .models import Record, clean_text, normalize_date, record_from_element


class ParseError(RuntimeError):
    """응답이 기대한 봉투가 아닐 때."""


class ApiError(ParseError):
    """API 가 오류 봉투를 돌려줬을 때.

    `retryable` — 재시도가 의미 있는가. 인증·필수값 오류는 재시도해도 같은 답이다.
    """

    def __init__(self, message: str, *, retryable: bool = False, kind: str = "api"):
        self.retryable = retryable
        self.kind = kind
        super().__init__(message)


class NotFound(ApiError):
    """식별자에 해당하는 문헌이 없을 때(`<Law>일치하는 …이 없습니다</Law>`).

    🔴 **오류가 아니라 사실인 경우가 있다.** 판례는 데이터출처에 따라 본문이 아예
       없다(아래 `prec` 주석). 호출자가 구분할 수 있도록 별도 예외로 둔다.
    """

    def __init__(self, message: str):
        super().__init__(message, retryable=False, kind="not_found")


_NOT_FOUND_RE = re.compile(r"일치하는\s*.{0,10}(?:이|가)\s*없습니다")


def _to_root(body: bytes | str, *, what: str) -> ET.Element:
    """본문 → XML 루트. **바이트는 디코드하지 않고 그대로 넘긴다.**

    ElementTree 가 XML 선언(`encoding="utf-8"`)을 존중한다. 우리가 먼저 str 로 바꾸면
    charset 추측이 끼어들 여지가 생긴다.
    (이 API 는 자매 API 와 달리 Content-Type 에 charset 을 붙여 주지만, 그 사실에
     기대는 대신 선언을 읽게 두는 편이 안전하다 — 헤더는 바뀔 수 있다.)
    """
    data = body.encode("utf-8") if isinstance(body, str) else bytes(body or b"")

    if not data.strip():
        # 🔴 실측: 없는 target → HTTP 200 · 0바이트 · Content-Type 없음.
        raise ApiError(
            f"{what}: 응답이 **비어 있습니다**(0바이트). 이 API 는 존재하지 않는 "
            f"`target` 에 오류 대신 빈 본문을 돌려줍니다(실측) — target 철자를 확인하세요. "
            f"네트워크 문제일 수도 있으므로 재시도 대상입니다.",
            retryable=True, kind="empty")

    head = data[:400].lstrip().lower()
    if head.startswith((b"<!doctype", b"<html")):
        # 🔴 실측: lsHistory·couseLs 는 type=XML 을 무시하고 HTML 을 준다.
        raise ApiError(
            f"{what}: XML 이 아니라 **HTML** 이 왔습니다. 이 target 은 `type=XML` 을 "
            f"무시합니다(실측: lsHistory·couseLs). 화면용 서비스이므로 이 서버로는 "
            f"다룰 수 없습니다.", retryable=False, kind="html")

    try:
        return ET.fromstring(data)
    except ET.ParseError as e:
        preview = data[:200].decode("utf-8", "replace")
        raise ParseError(scrub(f"{what}: XML 파싱 실패({e}) — 응답 앞부분: {preview!r}")) from None


def _check_failure_envelopes(root: ET.Element, *, what: str) -> None:
    """HTTP 200 으로 위장한 실패 봉투를 예외로 올린다."""
    # (1) 인증·필수값 검증 실패 — `<Response><result>·<msg>`
    if root.tag == "Response":
        result = clean_text(root.findtext("./result")) or "(사유 미상)"
        msg = clean_text(root.findtext("./msg"))
        hint = ""
        if "사용자 정보" in result:
            hint = (" → `OC` 값을 확인하세요. OC 는 open.law.go.kr 가입 이메일의 @ 앞부분이며 "
                    "사용자가 직접 지정합니다(비밀값 아님). 등록 IP 제한에 걸렸을 수도 있습니다.")
        elif "필수입력" in result:
            hint = " → `OC` 가 전달되지 않았습니다. 환경변수 LAW_OC 를 설정하세요."
        raise ApiError(scrub(f"{what}: {result} {msg}{hint}"), retryable=False, kind="auth")

    # (2) 식별자 미일치 — 루트가 `<Law>` 이고 텍스트만 있다.
    #     ⚠️ target 과 무관하게 `<Law>` 다(판례도 `<Law>일치하는 판례가 없습니다</Law>`).
    if root.tag == "Law" and len(root) == 0:
        text = clean_text(root.text)
        if _NOT_FOUND_RE.search(text) or not text:
            raise NotFound(f"{what}: {text or '해당 문헌을 찾을 수 없습니다.'}")
        raise ApiError(scrub(f"{what}: {text}"), retryable=False, kind="api")


# ── 목록 ────────────────────────────────────────────────────────────────────
def parse_list(body: bytes | str, tgt: Target, *, expect_records: bool = True
               ) -> tuple[int, list[Record], dict[str, Any]]:
    """목록 응답 → (totalCnt, 레코드, 봉투 메타).

    `expect_records` — 이 응답에 레코드가 **있어야 하는가**. 첫 페이지에서는 True.
    끝을 지난 페이지는 정상적으로 비어 있으므로(실측: page=200 → 0건, totalCnt 는 정상)
    거기까지 오류로 올리면 마지막 페이지마다 재시도를 태운다.
    """
    what = f"{tgt.label}({tgt.code}) 목록"
    root = _to_root(body, what=what)
    _check_failure_envelopes(root, what=what)

    env: dict[str, Any] = {"root_tag": root.tag, "expected_root": tgt.list_root}
    if root.tag != tgt.list_root:
        # 강요하지 않고 **알린다** — 레지스트리가 낡았을 수 있고, 그 사실 자체가 정보다.
        env["root_tag_mismatch"] = (
            f"루트 태그가 기대({tgt.list_root})와 다릅니다: <{root.tag}>. "
            f"API 스키마가 바뀌었을 수 있습니다 — config.TARGETS 를 확인하세요.")

    total = _as_int(root.findtext("./totalCnt"))
    for k in ("page", "numOfRows", "resultCode", "resultMsg", "section", "키워드", "target"):
        v = root.findtext(f"./{k}")
        if v is not None:
            env[k] = clean_text(v)

    # ⚠️ `prec`(판례) 목록 봉투에는 numOfRows·resultCode·resultMsg 가 **없다**(실측).
    #    다른 갈래에는 있다. 없다고 오류로 보면 판례가 통째로 막힌다.
    if "resultCode" not in env:
        env["envelope_note"] = (
            f"이 갈래({tgt.code})의 목록 봉투에는 resultCode/numOfRows 가 없습니다"
            f"(실측: prec 이 그렇다). 오류가 아닙니다.")

    rec_els = root.findall(f"./{tgt.record_tag}")
    env["record_tag"] = tgt.record_tag
    if not rec_els and total > 0:
        # 레지스트리가 틀렸을 때 조용히 0건이 되는 것을 막는다 — 실제 자식 태그를 보여 준다.
        seen = list(dict.fromkeys(c.tag for c in root))
        env["record_tag_candidates"] = [t for t in seen if t not in (
            "totalCnt", "page", "numOfRows", "resultCode", "resultMsg",
            "section", "키워드", "target")]

    records = [record_from_element(el, target=tgt.code, label=tgt.label,
                                   id_field=tgt.id_field) for el in rec_els]

    if expect_records and total > 0 and not records:
        raise ParseError(
            f"{what}: totalCnt 는 {total:,}건인데 레코드가 0개입니다 — 정상적인 "
            f"'결과 없음'이 아닙니다. 기대한 레코드 태그는 <{tgt.record_tag}> 인데 "
            f"실제 자식 태그는 {', '.join(env.get('record_tag_candidates') or ['(없음)'])} "
            f"입니다. config.TARGETS 의 record_tag 가 낡았을 수 있습니다.")

    return total, records, env


def _as_int(value: Any) -> int:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return int(digits) if digits else 0


# ── 본문 ────────────────────────────────────────────────────────────────────
# 갈래마다 본문 구조가 다르다(실측). 조문을 들고 있는 갈래는 둘뿐이고, 그나마
# **자식 태그 이름이 서로 다르다**:
#   법령    <법령><조문><조문단위><조문번호>·<조문내용>·<항>…
#   자치법규 <LawService><조문><조><조문번호>·<조제목>·<조내용>   ← 이름이 다르다!
#
# 🔴 **조문의 알맹이는 `조문내용` 이 아니라 `항`·`호` 안에 있다.**
#    실측(감사교육원 운영 등에 관한 규칙, 조문단위 39개):
#      조문내용 = 39개 — 조 표제 문장뿐 ("제3조(교육대상) … 대상으로 한다.")
#      항       = 36개 (항내용 35 · 그 아래 호 21개)
#    초판은 `조문내용` 만 읽어 **본문의 70%를 잃었다**(2,057자 / 실제 7,359자).
#    자매 저장소의 `<recode>` 사고와 같은 종류다 — 오류 없이 조용히 줄어든다.
_ARTICLE_SPECS = {
    "조문단위": {"num": "조문번호", "branch": "조문가지번호", "title": "조문제목",
               "text": "조문내용", "flag": "조문여부", "eff": "조문시행일자"},
    "조":      {"num": "조문번호", "branch": "",           "title": "조제목",
               "text": "조내용",   "flag": "조문여부", "eff": ""},
}

# 조문 아래의 중첩 단위 — 바깥에서 안으로. 실측: 항 → 호 (목은 이 표본엔 없었으나
# 법령 일반에는 존재하므로 받아 둔다 — 없으면 그냥 지나간다).
_NEST = (("항", "항번호", "항내용"), ("호", "호번호", "호내용"), ("목", "목번호", "목내용"))


def _render_nested(el: ET.Element, depth: int = 0) -> list[str]:
    """`<항>`·`<호>`·`<목>` 을 들여쓰기를 살려 펼친다.

    ⚠️ 들여쓰기는 **계층 정보**다(항 → 호 → 목). 각 줄에 strip() 을 걸면 사라진다.
    """
    out: list[str] = []
    for tag, num_f, text_f in _NEST:
        for child in el.findall(tag):
            num = clean_text(child.findtext(num_f))
            text = clean_text(child.findtext(text_f))
            line = text or (f"{num}." if num else "")
            if line:
                pad = "  " * (depth + 1)
                out.extend(pad + ln for ln in line.split("\n"))
            out.extend(_render_nested(child, depth + 1))
    return out

# 본문에서 '서술형 텍스트'로 취급할 필드 — 관련도 채점·요약의 재료다.
NARRATIVE_FIELDS = (
    "판시사항", "판결요지", "판례내용", "참조조문", "참조판례",
    "결정요지", "전문", "심판대상조문",
    "질의요지", "회답", "이유",
    "조문내용", "부칙내용", "개정문내용", "제개정이유내용", "조약내용",
)


def parse_body(body: bytes | str, tgt: Target) -> tuple[dict[str, Any], dict[str, Any]]:
    """본문 응답 → (내용, 봉투 메타).

    돌려주는 `내용`:
      - `fields`   : 평탄한 name→value (기본정보를 펼친 것 포함)
      - `articles` : 조문 목록 [{번호, 제목, 내용, …}] — 법령·자치법규에만 있다
      - `text`     : 사람이 읽을 수 있게 이어붙인 본문
      - `raw_tree` : 최상위 자식 태그 목록(구조가 바뀌었는지 보는 용도)

    🔴 **`NotFound` 는 예외지만 사고가 아니다.** 특히 판례는 데이터출처에 따라 본문이
       없다 — 실측: `데이터출처명=국세법령정보시스템` 인 판례는 목록에는 나오지만
       본문 조회에 "일치하는 판례가 없습니다" 가 온다. `데이터출처명=대법원` 은 정상
       (18KB). 호출자는 이것을 '결손'으로 기록하고 넘어가야 한다.
    """
    what = f"{tgt.label}({tgt.code}) 본문"
    root = _to_root(body, what=what)
    _check_failure_envelopes(root, what=what)

    meta: dict[str, Any] = {"root_tag": root.tag, "expected_root": tgt.body_root}
    if root.tag != tgt.body_root:
        meta["root_tag_mismatch"] = (
            f"본문 루트가 기대({tgt.body_root})와 다릅니다: <{root.tag}>.")

    fields: dict[str, str] = {}
    articles: list[dict[str, str]] = []
    attachments: list[dict[str, str]] = []
    tree: list[str] = []
    # 조문/첨부 컨테이너 안의 잎은 fields 로 빨아들이지 않는다 — 39×조문번호 가 섞인다.
    skip_subtrees = {"조문", "첨부파일"}

    def absorb(el: ET.Element) -> None:
        """스칼라 잎을 **재귀적으로** fields 로 흡수. 같은 이름이 여럿이면 이어붙인다.

        🔴 재귀여야 한다 — `기본정보/연락부서/부서단위/부서명` 처럼 3단 중첩이 실제로
           있다(실측). 한 단만 훑으면 그 가지가 통째로 사라진다.
        """
        for c in el:
            if c.tag in skip_subtrees:
                continue
            if len(c) > 0:
                absorb(c)
                continue
            key, val = c.tag, clean_text(c.text)
            if fields.get(key) and val:
                fields[key] = f"{fields[key]}\n{val}"
            else:
                fields.setdefault(key, val)

    absorb(root)

    for child in root:
        tree.append(child.tag)
        if child.tag == "첨부파일" or child.find("첨부파일명") is not None:
            names = [clean_text(x.text) for x in child.findall(".//첨부파일명")]
            links = [clean_text(x.text) for x in child.findall(".//첨부파일링크")]
            for i, nm in enumerate(names):
                attachments.append(
                    {"이름": nm, "링크": links[i] if i < len(links) else ""})
        for art_tag, spec in _ARTICLE_SPECS.items():
            for a in child.findall(f"./{art_tag}"):
                head_txt = clean_text(a.findtext(spec["text"]))
                nested = _render_nested(a)
                num = clean_text(a.findtext(spec["num"]))
                branch = clean_text(a.findtext(spec["branch"])) if spec["branch"] else ""
                item = {
                    "번호": num,
                    "가지번호": branch if branch not in ("", "0", "000000") else "",
                    "제목": clean_text(a.findtext(spec["title"])) if spec["title"] else "",
                    "구분": clean_text(a.findtext(spec["flag"])) if spec["flag"] else "",
                    "내용": "\n".join([head_txt] + nested).strip() if (head_txt or nested)
                            else "",
                }
                if spec["eff"]:
                    item["시행일"] = normalize_date(a.findtext(spec["eff"]))
                ref = clean_text(a.findtext("조문참고자료"))
                if ref:
                    item["참고자료"] = ref
                articles.append(item)

    dates = {k: normalize_date(v) for k, v in fields.items()
             if k.endswith("일자") and v}
    content: dict[str, Any] = {
        "fields": fields,
        "dates_normalized": dates,
        "articles": articles,
        "attachments": attachments,
        "raw_tree": list(dict.fromkeys(tree)),
    }
    content["text"] = _render_text(fields, articles)
    meta["article_count"] = len(articles)
    meta["attachment_count"] = len(attachments)
    meta["text_chars"] = len(content["text"])
    meta["narrative_fields"] = [k for k in NARRATIVE_FIELDS if fields.get(k)]
    # 조문이 있는데 항이 하나도 안 잡혔다면 스키마가 바뀐 것일 수 있다 — 알린다.
    if articles and not any("\n" in (a.get("내용") or "") for a in articles):
        meta["flat_articles_note"] = (
            "조문이 전부 한 줄입니다 — 항·호가 잡히지 않았을 수 있습니다"
            "(정상인 갈래도 있습니다: 자치법규는 조내용 한 덩어리로 옵니다).")
    return content, meta


def _render_text(fields: dict[str, str], articles: list[dict[str, str]]) -> str:
    """사람이 읽을 수 있는 본문 — 관련도 채점·요약의 입력으로도 쓴다."""
    parts: list[str] = []
    for k in ("법령명_한글", "법령명한글", "자치법규명", "행정규칙명", "사건명",
              "안건명", "조약명_한글"):
        if fields.get(k):
            parts.append(fields[k])
            break

    for a in articles:
        head = " ".join(x for x in (a.get("번호"), a.get("제목")) if x)
        body = a.get("내용") or ""
        if head and body and not body.startswith(("제", head)):
            parts.append(f"{head}\n{body}")
        elif body:
            parts.append(body)
        elif head:
            parts.append(head)

    for k in NARRATIVE_FIELDS:
        v = fields.get(k)
        # 조문내용은 articles 로 이미 냈다(조문 구조가 있는 갈래). 구조가 없는 갈래
        # (행정규칙 조문형식여부=N)에서는 여기가 유일한 본문이므로 빠뜨리면 안 된다.
        if v and not (k == "조문내용" and articles):
            parts.append(f"[{k}]\n{v}")

    return "\n\n".join(p for p in parts if p).strip()
