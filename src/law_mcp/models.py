"""레코드 스키마와 정규화 — 실측 응답 기반.

## 설계의 축: **인용 단위가 곧 레코드 단위다** (T41 ① · 사용자 지시)

검색·수집 단위는 인용 관행을 따른다. 서지 메타데이터에 맞아야 하고 학술 문헌에
인용 가능한 형태여야 하기 때문이다.

    **법령 하나가 문헌 하나**이고, 조문은 인용할 때의 **위치**(쪽 자리)로 넣는다.
    판례는 사건 하나, 법령해석례는 안건 하나, 조약은 조약 하나.

🔴 **조문 단위로 쪼개 색인하지 않는다.** 「초·중등교육법」은 조문단위 135개짜리
   309KB 문서지만 문헌으로는 **하나**다. 조문마다 레코드를 만들면 서지가 아니라
   말뭉치가 되고, 참고문헌 목록에 「초·중등교육법 제23조」가 135줄 생긴다.
   본문이 필요하면 `law_body` 로 따로 받는다(그때는 조문이 구조로 온다).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ── 표제·본문 정제 ──────────────────────────────────────────────────────────
# 🔴 **임의의 `<...>` 를 지우면 안 된다.** 법령 텍스트는 꺾쇠를 **내용으로** 쓴다:
#      「부칙 <2010.7.5> 제1조(시행일) 이 조례는 …」   ← 실측(자치법규 부칙내용)
#    자매 저장소(na-openapi-mcp)가 정확히 이 실수로 표제 18건을 손상시켰고 적대적
#    리뷰에서 잡혔다. 그래서 **알려진 HTML 태그 이름만** 지운다.
_HTML_BLOCK = (
    "br", "p", "div", "li", "tr", "table", "tbody", "thead", "h1", "h2", "h3",
    "h4", "h5", "h6", "hr", "blockquote",
)
_HTML_INLINE = (
    "img", "span", "a", "b", "i", "u", "em", "strong", "font", "sup", "sub",
    "td", "th", "pre", "code", "small", "center",
)
_ALL_TAGS = _HTML_BLOCK + _HTML_INLINE

# `<br/>`·`<img id="1">`·`</p>` 는 잡고, `<2010.7.5>`·`<개정 2019. 7. 15.>` 는 남긴다.
_BLOCK_RE = re.compile(
    r"</?\s*(?:" + "|".join(_HTML_BLOCK) + r")\b[^>]*>", re.IGNORECASE)
_TAG_RE = re.compile(
    r"</?\s*(?:" + "|".join(_ALL_TAGS) + r")\b[^>]*>", re.IGNORECASE)


def clean_text(value: str | None) -> str:
    """HTML 마크업만 걷어낸다 — 꺾쇠를 쓴 **내용은 보존**한다.

    실측: 판례 본문의 `판시사항`·`판결요지` 는 `<br/>` 로 시작하고, 행정규칙
    `조문내용` 에는 `<img id="149458663">` 가 박혀 있다. 반면 부칙의 `<2010.7.5>` 는
    지우면 안 되는 내용이다.
    """
    if not value:
        return ""
    s = _BLOCK_RE.sub("\n", str(value))
    s = _TAG_RE.sub("", s)
    s = s.replace("\xa0", " ").replace("　", " ")
    # 연속 빈 줄만 접는다 — 들여쓰기(계층 정보)는 보존한다.
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# ── 날짜 ────────────────────────────────────────────────────────────────────
# 🔴 **같은 필드가 목록과 본문에서 다른 꼴로 온다**(실측):
#      판례 `선고일자`  — 목록 '2026.04.23'  / 본문 '20260212'
#      헌재 `종국일자`  — 목록 '2016.10.27'  / 본문 '20161027'
#      법령 `공포일자`  — 목록·본문 모두 '20190715'
#    한쪽만 보고 파서를 쓰면 다른 쪽에서 조용히 빈 값이 된다.
_DATE_COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_DATE_DOTTED = re.compile(r"^(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})\.?$")


def normalize_date(value: str | None) -> str:
    """'20190715' · '2026.04.23' · '2016. 10. 27.' → '2019-07-15' 꼴로.

    모르는 꼴은 **원문 그대로 돌려준다** — 조용히 비우면 데이터가 사라진다.
    """
    s = (str(value or "")).strip()
    if not s:
        return ""
    m = _DATE_COMPACT.match(s)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{mo}-{d}" if mo != "00" and d != "00" else y
    m = _DATE_DOTTED.match(s)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return s


# ── 필드 매핑 ───────────────────────────────────────────────────────────────
# 실측 필드명 → 정규화 이름. **여러 갈래가 같은 정규화 칸을 공유한다**(그것이 요점이다 —
# Ibis 의 `legislation` 유형은 발령주체·호·시행일·제정기관 한 벌로 전 갈래를 담는다).
#
# ⚠️ 여기에 없는 필드도 **전부 `raw` 에 남고 내보내기에도 나간다**(exporters 참조).
#    자매 저장소는 미매핑 필드가 MCP 응답·csv·xlsx 어디에도 안 나와서
#    국회의안의 '제안이유 및 주요내용'(97% 채워진 서술형 본문)을 통째로 잃었다.
#    같은 실수를 되풀이하지 않으려고 이 저장소는 **미매핑 필드를 열로 승격**한다.
# ⚠️ 갈래가 72종이 되면서 표제 필드 이름도 늘었다. **순서가 곧 우선순위**다 —
#    `기관명` 같은 이름이 앞에 오면 결정문의 표제가 기관 이름으로 바뀐다(실제로 겪었다).
TITLE_FIELDS = (
    "법령명한글", "법령명_한글", "행정규칙명", "자치법규명", "사건명", "안건명",
    "조약명", "조약명_한글", "법령명", "별표명", "법령용어명", "제목", "사건",
    "민원표시명",
)
NUMBER_FIELDS = (
    "공포번호", "발령번호", "사건번호", "안건번호", "조약번호",
    "의결번호", "의안번호", "청구번호", "별표번호",
)
PROMULGATED_FIELDS = (
    "공포일자", "발령일자", "선고일자", "종국일자", "해석일자", "회신일자", "서명일자",
    "의결일자", "의결일", "처분일자", "등록일",
)
EFFECTIVE_FIELDS = ("시행일자", "발효일자", "자치법규시행일자")
AUTHORITY_FIELDS = (
    "소관부처명", "소관부처", "지자체기관명", "법원명", "해석기관명", "회신기관명",
    "상위부처명", "체결대상국가한글", "재결청", "처분청", "기관명", "전체기관명",
)
KIND_FIELDS = (
    "법령구분명", "법종구분", "행정규칙종류", "자치법규종류", "사건종류명",
    "조약구분명", "판결유형", "재결구분명", "별표종류", "결정구분", "회의종류",
    "법령종류", "법령분류명",
)
REVISION_FIELDS = ("제개정구분명", "제개정구분", "제개정정보")
STATUS_FIELDS = ("현행연혁코드", "현행연혁구분", "현행여부")
LINK_FIELDS = tuple()   # '…상세링크' 는 접미사로 찾는다(갈래마다 이름이 다르다)

# 정규화 열 순서 — csv/xlsx 의 앞머리. 뒤에 미매핑 열이 붙는다.
COLUMNS = [
    "doc_id", "target", "doc_type", "title", "number", "promulgated",
    "effective", "authority", "kind", "revision", "status", "link",
]


def _first(fields: dict[str, str], names: tuple[str, ...]) -> str:
    for n in names:
        v = (fields.get(n) or "").strip()
        if v:
            return v
    return ""


@dataclass
class Record:
    """한 건의 법령·판례·해석례 등 — **인용 가능한 문헌 하나**."""
    doc_id: str = ""
    target: str = ""
    doc_type: str = ""     # 사람이 읽는 갈래 이름(현행법령·판례 …)
    title: str = ""
    number: str = ""
    promulgated: str = ""  # 공포·선고·종국·해석일 (YYYY-MM-DD)
    effective: str = ""    # 시행·발효일
    authority: str = ""    # 발령주체·소관부처·법원
    kind: str = ""
    revision: str = ""
    status: str = ""
    link: str = ""
    raw: dict[str, str] = field(default_factory=dict)

    def dedup_key(self) -> str:
        """중복 판정 키 — 일련번호가 있으면 그것, 없으면 갈래+표제+번호."""
        if self.doc_id:
            return f"{self.target}:{self.doc_id}"
        return f"{self.target}:{self.title}:{self.number}:{self.promulgated}"

    def to_row(self) -> dict[str, str]:
        return {c: getattr(self, c, "") for c in COLUMNS}

    def unmapped(self) -> dict[str, str]:
        """정규화 칸으로 안 간 원본 필드 — **버리지 않고 돌려준다**."""
        used = set(TITLE_FIELDS) | set(NUMBER_FIELDS) | set(PROMULGATED_FIELDS) \
            | set(EFFECTIVE_FIELDS) | set(AUTHORITY_FIELDS) | set(KIND_FIELDS) \
            | set(REVISION_FIELDS) | set(STATUS_FIELDS)
        return {k: v for k, v in self.raw.items()
                if k not in used and not k.endswith("상세링크")}

    def citation_fields(self) -> dict[str, str]:
        """Ibis `legislation` 유형으로 넘길 칸 — 이름을 Ibis 쪽에 맞춘다.

        Ibis 의 legislation 서식은 이미 완비돼 있다(발령주체·호·시행일·제정기관).
        여기서 이름만 맞춰 주면 매핑이 끝난다(T41 ④).
        """
        return {
            "title": self.title,
            "발령주체": self.authority,
            "제정기관": self.authority,
            "호": self.number,
            "공포일": self.promulgated,
            "시행일": self.effective,
            "종류": self.kind or self.doc_type,
            "제개정": self.revision,
            "url": self.link,
        }


BASE_SITE = "https://www.law.go.kr"


def record_from_element(el, *, target: str, label: str, id_field: str) -> Record:
    """목록 레코드 XML 요소 → Record.

    ⚠️ **자식 태그 이름으로만** 읽는다 — 순서에 의존하지 않는다.
    ⚠️ 값이 빈 요소(`<법령약칭명/>`)도 raw 에 빈 문자열로 남긴다. '없는 필드'와
       '빈 필드'는 다른 사실이고, 뒤에 census 를 뜰 때 그 차이가 필요하다.
    """
    raw: dict[str, str] = {}
    for child in el:
        name = child.tag
        value = clean_text(child.text)
        raw[name] = f"{raw[name]}; {value}" if raw.get(name) and value else (
            raw.get(name) or value)

    link = ""
    for k, v in raw.items():
        if k.endswith("상세링크") and v:
            link = v if v.startswith("http") else BASE_SITE + v
            break

    return Record(
        doc_id=(raw.get(id_field) or "").strip(),
        target=target,
        doc_type=label,
        title=_first(raw, TITLE_FIELDS),
        number=_first(raw, NUMBER_FIELDS),
        promulgated=normalize_date(_first(raw, PROMULGATED_FIELDS)),
        effective=normalize_date(_first(raw, EFFECTIVE_FIELDS)),
        authority=_first(raw, AUTHORITY_FIELDS),
        kind=_first(raw, KIND_FIELDS),
        revision=_first(raw, REVISION_FIELDS),
        status=_first(raw, STATUS_FIELDS),
        link=link,
        raw=raw,
    )
