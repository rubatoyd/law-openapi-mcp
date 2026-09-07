"""파서 회귀 — 전부 **실응답 픽스처** 기반.

이 파일이 지키는 것은 하나다: **조용히 줄어들지 않는다.**
태그가 바뀌거나 중첩을 놓치면 오류 없이 0건·빈 본문이 되는 API 이므로,
'예외가 안 났다'는 통과 근거가 못 된다. 건수와 글자수를 직접 붙든다.
"""
from __future__ import annotations

import pytest

from law_mcp.config import TARGETS, resolve_target, validate_query
from law_mcp.models import clean_text, normalize_date
from law_mcp.parser import ApiError, NotFound, ParseError, parse_body, parse_list


# ── 갈래별 목록: 태그 함정이 표대로인가 ─────────────────────────────────────
# 실측값이다. 이 숫자가 바뀌면 API 가 바뀐 것이거나 파서가 깨진 것이다.
LIST_EXPECT = {
    "law":    (159,  "law",    "209959"),
    "prec":   (259,  "prec",   "621039"),
    "admrul": (732,  "admrul", "2100000255232"),
    "ordin":  (8517, "law",    "1682617"),     # 🔴 레코드 태그가 제 이름이 아니다
    "expc":   (579,  "expc",   "335283"),
    "detc":   (258,  "Detc",   "52626"),       # 🔴 대문자
    "trty":   (79,   "Trty",   "1909"),        # 🔴 대문자
}


@pytest.mark.parametrize("code", sorted(LIST_EXPECT))
def test_list_parses_with_measured_tags(fx, code):
    total, recs, env = parse_list(fx(f"list_{code}.xml"), TARGETS[code])
    exp_total, exp_tag, exp_id = LIST_EXPECT[code]
    assert total == exp_total
    assert env["record_tag"] == exp_tag
    assert len(recs) == 3, "픽스처는 display=3 으로 받았다"
    assert recs[0].doc_id == exp_id
    assert recs[0].title, "표제가 비면 title_field 매핑이 깨진 것이다"
    assert "root_tag_mismatch" not in env


def test_ordin_record_tag_is_law_not_ordin(fx):
    """🔴 자치법규의 레코드 태그는 `<law>` 다 — 이름으로 유추하면 0건이 된다."""
    assert TARGETS["ordin"].record_tag == "law"
    _, recs, _ = parse_list(fx("list_ordin.xml"), TARGETS["ordin"])
    assert len(recs) == 3


def test_uppercase_record_tags_are_not_normalized(fx):
    """XML 태그는 대소문자를 구분한다 — detc/trty 를 소문자로 바꾸면 0건이다."""
    for code in ("detc", "trty"):
        assert TARGETS[code].record_tag[0].isupper()
        _, recs, _ = parse_list(fx(f"list_{code}.xml"), TARGETS[code])
        assert len(recs) == 3


def test_prec_envelope_lacks_resultcode_and_that_is_ok(fx):
    """판례 목록 봉투에는 resultCode·numOfRows 가 없다(실측) — 오류로 보면 안 된다."""
    total, recs, env = parse_list(fx("list_prec.xml"), TARGETS["prec"])
    assert "resultCode" not in env
    assert "envelope_note" in env
    assert total == 259 and len(recs) == 3


# ── HTTP 200 으로 위장한 실패들 ─────────────────────────────────────────────
def test_empty_body_is_error_not_zero_results():
    """🔴 없는 target 은 HTTP 200 + 0바이트다. '결과 0건'으로 통과시키면 안 된다."""
    with pytest.raises(ApiError) as e:
        parse_list(b"", TARGETS["law"])
    assert e.value.kind == "empty"
    assert e.value.retryable is True


def test_auth_failure_envelope():
    body = ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            "<result>사용자 정보 검증에 실패하였습니다.</result>"
            "<msg>OPEN API 호출 시 사용자 검증을 위하여…</msg></Response>").encode()
    with pytest.raises(ApiError) as e:
        parse_list(body, TARGETS["law"])
    assert e.value.kind == "auth"
    assert e.value.retryable is False
    assert "OC" in str(e.value)


def test_missing_required_param_envelope():
    body = ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            "<result>필수입력요소 검증에 실패하였습니다.</result>"
            "<msg>필수 입력값이 존재하지 않습니다.</msg></Response>").encode()
    with pytest.raises(ApiError) as e:
        parse_list(body, TARGETS["law"])
    assert e.value.kind == "auth"
    assert "LAW_OC" in str(e.value)


def test_not_found_envelope_root_is_Law_for_every_target(fx):
    """🔴 판례를 조회해도 루트가 `<Law>` 다 — 기대 루트만 찾으면 '본문 없음'이 된다."""
    with pytest.raises(NotFound):
        parse_body(fx("body_prec.xml"), TARGETS["prec"])


def test_html_response_is_rejected_loudly():
    body = b"<!DOCTYPE html><html><head><title>x</title></head><body>y</body></html>"
    with pytest.raises(ApiError) as e:
        parse_list(body, TARGETS["law"])
    assert e.value.kind == "html"


def test_total_positive_but_no_records_is_an_error():
    """태그가 바뀌면 '결과 0건'이 아니라 시끄럽게 실패해야 한다."""
    body = ("<LawSearch><totalCnt>159</totalCnt>"
            "<somethingelse><법령일련번호>1</법령일련번호></somethingelse>"
            "</LawSearch>").encode()
    with pytest.raises(ParseError) as e:
        parse_list(body, TARGETS["law"])
    assert "somethingelse" in str(e.value)


def test_past_end_page_is_allowed_when_not_expecting_records():
    body = b"<LawSearch><totalCnt>159</totalCnt><page>200</page></LawSearch>"
    total, recs, _ = parse_list(body, TARGETS["law"], expect_records=False)
    assert total == 159 and recs == []


# ── 본문: 중첩을 잃지 않는가 ────────────────────────────────────────────────
def test_law_body_keeps_hang_and_ho(fx):
    """🔴 조문의 알맹이는 `조문내용` 이 아니라 `항`·`호` 안에 있다.

    초판은 `조문내용` 만 읽어 본문의 70%를 잃었다(2,057자 / 실제 7,359자).
    """
    content, meta = parse_body(fx("body_law.xml"), TARGETS["law"])
    assert meta["article_count"] == 39
    art3 = [a for a in content["articles"]
            if a["번호"] == "3" and a["구분"] == "조문"][0]
    assert "감사원 소속직원" in art3["내용"], "호가 사라졌다"
    assert "1." in art3["내용"]
    assert meta["text_chars"] > 5_500, f"본문이 줄었다: {meta['text_chars']}자"


def test_law_body_separates_headings_from_articles(fx):
    """`조문여부='전문'` 은 장·절 표제이지 조문이 아니다(실측: 39 = 조문 29 + 전문 10)."""
    content, _ = parse_body(fx("body_law.xml"), TARGETS["law"])
    kinds = [a["구분"] for a in content["articles"]]
    assert kinds.count("조문") == 29
    assert kinds.count("전문") == 10


def test_law_body_keeps_branch_numbers(fx):
    """제6조의2 같은 가지번호는 인용 위치 표기에 필요하다."""
    content, _ = parse_body(fx("body_law.xml"), TARGETS["law"])
    branches = [(a["번호"], a["가지번호"]) for a in content["articles"] if a["가지번호"]]
    assert ("6", "2") in branches


def test_deeply_nested_scalars_survive(fx):
    """기본정보/연락부서/부서단위/부서명 — 3단 중첩. 한 단만 훑으면 통째로 사라진다."""
    content, _ = parse_body(fx("body_law.xml"), TARGETS["law"])
    assert content["fields"].get("부서명") == "교육지원과"


def test_ordin_uses_different_article_tag_names(fx):
    """자치법규는 `<조>` 에 `조제목`·`조내용` 이다 — 법령과 이름이 다르다."""
    content, meta = parse_body(fx("body_ordin.xml"), TARGETS["ordin"])
    assert meta["article_count"] == 12
    assert any(a["제목"] for a in content["articles"])


def test_admrul_without_article_structure_still_has_text(fx):
    """조문형식여부='N' 인 행정규칙은 조문 구조가 없다 — 그때는 조문내용이 유일한 본문이다."""
    content, meta = parse_body(fx("body_admrul.xml"), TARGETS["admrul"])
    assert meta["article_count"] == 0
    assert "조문내용" in meta["narrative_fields"]
    assert content["text"].strip()


def test_admrul_attachments_are_captured(fx):
    """별표·서식은 첨부파일로 온다 — 버리면 사용자가 원문에 닿을 길이 없다."""
    content, meta = parse_body(fx("body_admrul.xml"), TARGETS["admrul"])
    assert meta["attachment_count"] == 4
    assert all(a["이름"] and a["링크"] for a in content["attachments"])


def test_prec_body_present_when_source_is_court(fx):
    """데이터출처명=대법원 인 판례는 본문이 온다(국세법령정보시스템은 안 온다)."""
    content, meta = parse_body(fx("body_prec_ok.xml"), TARGETS["prec"])
    assert "판시사항" in meta["narrative_fields"]
    assert "판결요지" in meta["narrative_fields"]
    assert meta["text_chars"] > 5_000


@pytest.mark.parametrize("code,expect", [
    ("expc", ("질의요지", "회답", "이유")),
    ("detc", ("판시사항", "결정요지", "전문")),
])
def test_narrative_fields_present(fx, code, expect):
    _, meta = parse_body(fx(f"body_{code}.xml"), TARGETS[code])
    for name in expect:
        assert name in meta["narrative_fields"]


# ── 정제: 내용을 태그로 오인하지 않는가 ─────────────────────────────────────
def test_clean_text_strips_html_but_keeps_angle_content():
    """🔴 법령 텍스트는 꺾쇠를 **내용으로** 쓴다. 자매 저장소가 이걸로 표제를 망쳤다."""
    assert clean_text("<br/> 판시사항") == "판시사항"
    assert clean_text('<img id="1"></img>가나') == "가나"
    # 지우면 안 되는 것들 — 개정 표기·부칙 일자
    assert "<개정 2010.7.6>" in clean_text("제1조(목적) … 한다. <개정 2010.7.6>")
    assert "<2010.7.5>" in clean_text("부칙 <2010.7.5> 제1조(시행일)")
    assert "<표 124>" in clean_text("<표 124> 학교 현황")


def test_clean_text_on_real_body_keeps_amendment_marks(fx):
    content, _ = parse_body(fx("body_law.xml"), TARGETS["law"])
    assert any("<개정" in (a["내용"] or "") for a in content["articles"])


@pytest.mark.parametrize("raw,expected", [
    ("20190715", "2019-07-15"),      # 목록·본문 공통(법령)
    ("2026.04.23", "2026-04-23"),    # 🔴 판례 **목록**은 점 구분
    ("20260212", "2026-02-12"),      # 🔴 판례 **본문**은 붙임 — 같은 필드가 다른 꼴
    ("2016. 10. 27.", "2016-10-27"),
    ("", ""),
    ("미상", "미상"),                 # 모르는 꼴은 비우지 않고 그대로 — 지우면 사라진다
])
def test_normalize_date(raw, expected):
    assert normalize_date(raw) == expected


# ── 호출 전 방어선 ──────────────────────────────────────────────────────────
def test_empty_query_is_refused():
    """🔴 빈 검색어는 오류가 아니라 전체 카탈로그(5,614건)를 부른다."""
    with pytest.raises(ValueError) as e:
        validate_query("   ")
    assert "전체 카탈로그" in str(e.value)


def test_wildcard_requires_explicit_optin():
    with pytest.raises(ValueError):
        validate_query("*")
    assert validate_query("*", allow_wildcard=True) == "*"


def test_validate_query_returns_normalized_value():
    """반환값을 버리고 원문을 보내면 검증이 무의미해진다(자매 저장소 적대적 검토)."""
    assert validate_query("  교육  ") == "교육"


def test_unknown_target_is_refused_before_the_call():
    with pytest.raises(ValueError) as e:
        resolve_target("zzz")
    assert "빈 응답" in str(e.value)


def test_case_typo_target_gets_a_hint():
    with pytest.raises(ValueError) as e:
        resolve_target("Law")
    assert "'law'" in str(e.value)


def test_html_only_targets_are_refused_with_reason():
    for code in ("lsHistory", "couseLs"):
        with pytest.raises(ValueError) as e:
            resolve_target(code)
        assert "XML" in str(e.value)


# ── 탐침이 잡은 레지스트리 오류 3종 (초판은 `law` 계열과 같으리라 짐작했다) ──────
def test_lsStmd_record_tag_is_law():
    """🔴 법령체계도의 레코드 태그도 `<law>` 다 — ordin 과 같은 함정.

    초판은 `lsStmd` 로 짐작해 **totalCnt 159 인데 레코드 0건**을 회수했다.
    `scripts/probe_api.py envelopes` 가 잡았다.
    """
    assert TARGETS["lsStmd"].record_tag == "law"


def test_elaw_body_root_collides_with_the_not_found_envelope():
    """🔴 영문법령 본문의 루트는 `<Law>` — '없음' 봉투와 **같은 태그**다.

    자식이 있는지로만 구분된다. 텍스트만 보고 판단하면 19KB 짜리 정상 본문을
    '없음'으로 버린다.
    """
    assert TARGETS["elaw"].body_root == "Law"
    body = ("<Law><InfSection><x>1</x></InfSection><JoSection/>"
            "<ArSection/><BylSection/></Law>").encode()
    content, meta = parse_body(body, TARGETS["elaw"])   # NotFound 가 나면 안 된다
    assert meta["root_tag"] == "Law"
    assert "InfSection" in content["raw_tree"]


def test_empty_Law_root_is_still_not_found():
    """반대로 자식이 없는 `<Law>` 는 '없음' 이다 — 구분이 자식 유무여야 하는 이유."""
    body = "<Law>일치하는 영문법령이 없습니다.  영문법령명을 확인하여 주십시오.</Law>".encode()
    with pytest.raises(NotFound):
        parse_body(body, TARGETS["elaw"])


def test_eflaw_declares_the_extra_body_param():
    """🔴 시행일법령 본문은 `MST` 만으로는 **HTML** 이 온다 — `efYd` 가 함께 필요하다.

    같은 법령이 시행일마다 다른 판본이라 (MST, efYd) 한 쌍이 신원이다
    (실측: 같은 법령일련번호가 시행예정·현행·연혁으로 여러 줄 나온다).
    """
    assert TARGETS["eflaw"].body_extra == (("efYd", "시행일자"),)
    assert TARGETS["law"].body_extra == ()
