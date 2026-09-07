"""환경설정·엔드포인트·대상(target) 레지스트리 — 법제처 OPEN API(DRF).

이 파일의 상수는 **전부 라이브 왕복으로 확정했다**(2026-09-08). 근거와 재현 방법은
docs/LAW_API_GUIDE.md · scripts/probe_api.py.

🔴 **법제처 API 는 둘이고 서로 다른 물건이다. 여기서 헷갈리면 반나절을 버린다.**

| | data.go.kr 공유서비스(1170000) | 법제처 OPEN API(DRF) ← **이 저장소** |
|---|---|---|
| 인증 | `serviceKey` | **`OC`** |
| 범위 | 목록조회 8종 | 카탈로그 전부 |
| 본문 | **없음** | **있다** |
| 판례 | 없음 | 있다 |

공유서비스로는 조문 본문도 판례도 못 얻는다. 이 저장소는 **DRF 만** 쓴다.
(공유서비스를 쓸 일이 생기면 `serviceKey` 를 **맨 앞에** 둬야 한다 — 뒤에 붙이면
 `NO_OPENAPI_SERVICE_ERROR`(12) "해당 오픈API 서비스가 없거나 폐기됨" 이 와서
 방금 승인받은 키를 승인 실패로 오인한다. 실측으로 확인된 함정이다.)
"""
from __future__ import annotations

import logging
import os
import re
from typing import NamedTuple

from dotenv import load_dotenv

load_dotenv(override=False)

BASE_URL = os.environ.get("LAW_BASE_URL", "https://www.law.go.kr/DRF")
SEARCH_URL = f"{BASE_URL}/lawSearch.do"      # 목록 조회
SERVICE_URL = f"{BASE_URL}/lawService.do"    # 본문 조회

# ── 상한 (2026-09-08 라이브 실측) ───────────────────────────────────────────
# `display` 상한은 **500**. 1000 을 요청하면 오류가 아니라 조용히 500 으로 깎이는데,
# 봉투의 `numOfRows` 는 **정직하게 500 을 에코한다**(실측: display=1000 → numOfRows=500,
# 레코드 500건). 그래서 에코를 보면 절삭을 탐지할 수 있다.
MAX_DISPLAY = int(os.environ.get("LAW_MAX_DISPLAY", "500"))
DEFAULT_DISPLAY = int(os.environ.get("LAW_DEFAULT_DISPLAY", "100"))

# 🔴 **`page` 에는 하드 상한이 없다** — 자매 API(국회도서관)의 `pageno<=99` 를 이식하지 말 것.
#    실측(ordin, total 8,517 · display=100): page=2 ○ / 50 ○ / 86 ○(마지막, 17건) / 200 → 0건.
#    즉 **totalCnt 전량을 회수할 수 있다**. 회수 한계는 API 가 아니라 우리가 거는 예산뿐이다.
PAGE_HARD_CAP: int | None = None

# 한 번의 도구 호출이 태울 수 있는 최대 요청 수(폭주 방지 — 쿼터가 아니라 예의).
MAX_CALLS_PER_TOOL_CALL = int(os.environ.get("LAW_MAX_CALLS_PER_TOOL_CALL", "300"))


# ── 대상(target) 레지스트리 ─────────────────────────────────────────────────
class Target(NamedTuple):
    """한 갈래의 실측 스키마.

    🔴 **네 가지가 전부 target 마다 다르고, 이름에서 유추할 수 없다.** 실측 없이
       규칙으로 지어내면 조용히 0건을 회수한다(자매 저장소가 `<recode>` 로 겪은 사고).
    """
    code: str            # DRF `target` 값
    label: str           # 사람이 읽는 이름
    list_root: str       # 목록 응답 루트 태그   — 예: LawSearch / Expc(!) / PrecSearch
    record_tag: str      # 목록 레코드 태그      — 예: law / Detc(대문자!) / ordin 은 law(!)
    id_field: str        # 레코드 안 식별자 필드 — 예: 법령일련번호
    id_param: str        # 본문 조회 파라미터명  — **MST 또는 ID**
    body_root: str       # 본문 응답 루트 태그
    title_field: str     # 표제(문헌명) 필드
    has_body: bool       # 본문 조회를 지원하는가
    # 본문 조회에 **추가로 필요한** 파라미터 → 목록 레코드의 어느 필드에서 가져오는가.
    # 🔴 `eflaw`(시행일법령)는 `MST` 만으로는 **HTML** 이 온다(실측 1,649B).
    #    `MST` + `efYd` 를 함께 줘야 XML 본문(317KB)이 온다. 시행일법령은 같은 법령의
    #    시행일별 판본이라 **(MST, efYd) 한 쌍이 문헌의 신원**이기 때문이다 —
    #    실제로 목록에 같은 법령일련번호가 시행예정·현행·연혁으로 여러 줄 나온다.
    body_extra: tuple[tuple[str, str], ...] = ()


# 전부 라이브로 확인(2026-09-08). `tests/fixtures/*.xml` 이 그때의 실응답이다.
#
# 🔴 **함정 넷 — 규칙이 아니라 표다:**
#   (1) `ordin`(자치법규)의 레코드 태그는 **`<law>`** 다. 제 이름이 아니다.
#   (2) `detc`·`trty` 의 레코드 태그는 **대문자로 시작**한다(`<Detc>`·`<Trty>`).
#       나머지는 소문자다. 대소문자를 정규화하면 안 된다 — XML 태그는 대소문자 구분이다.
#   (3) `expc`(법령해석례)의 목록 루트는 **`<Expc>`** 로, 혼자만 `…Search` 접미가 없다.
#   (4) 본문 조회 파라미터가 **`MST`(법령·자치법규)와 `ID`(나머지)** 로 갈린다.
#   (5) `lsStmd`(법령체계도)의 레코드 태그도 **`<law>`** 다 — ordin 과 같은 함정.
#   (6) `elaw`(영문법령)의 본문 루트는 **`<Law>`** 인데, 이것은 '없음' 봉투의 루트와
#       **같다**(`<Law>일치하는 …이 없습니다</Law>`). 자식이 있는지로만 구분된다.
#   (7) `eflaw` 본문은 `MST` 만으로는 HTML 이 온다 — `efYd`(시행일자)가 함께 필요하다.
#
# ✅ (1)~(7) 전부 `scripts/probe_api.py envelopes` 로 재확인된다. 초판은 (5)(6)(7)을
#    `law` 계열과 같으리라 **짐작해서** 틀렸고, 그 탐침이 잡았다.
#
# 🔴 **그리고 이것은 예외가 아니라 규칙이다.** 2026-09-08 에 후보 62종을 전수 실측한
#    결과(`scripts/probe_catalog.py`), **45종의 레코드 태그가 제 이름이 아니었다**:
#      · 부처 법령해석 39종 → 전부 `<cgmExpc>`(루트는 `CgmExpc`)
#      · 특별행정심판 4종   → 전부 `<decc>`(루트는 `Decc`)
#      · `school` → `<admrul>` · `admbyl` → `<admrulbyl>`(루트 `admRulBylSearch`, 소문자 시작)
#    본문 루트도 20가지로 제각각이다(`PpcService`·`FscService`·`SpecialDeccService`…).
#    식별자 파라미터도 `ID`/`MST` 만이 아니다 — **`lstrm` 은 `trmSeqs`** 다.
#    → 이 표는 손으로 적은 것이 아니라 **측정 결과를 생성한 것**이다. 규칙으로 바꾸지 말 것.
TARGETS: dict[str, Target] = {
    "law":    Target("law",    "현행법령",   "LawSearch",    "law",    "법령일련번호",       "MST", "법령",            "법령명한글", True),
    "eflaw":  Target("eflaw",  "시행일법령", "LawSearch",    "law",    "법령일련번호",       "MST", "법령",            "법령명한글", True,
                     body_extra=(("efYd", "시행일자"),)),
    "elaw":   Target("elaw",   "영문법령",   "LawSearch",    "law",    "법령일련번호",       "MST", "Law",             "법령명한글", True),
    "admrul": Target("admrul", "행정규칙",   "AdmRulSearch", "admrul", "행정규칙일련번호",   "ID",  "AdmRulService",   "행정규칙명", True),
    "ordin":  Target("ordin",  "자치법규",   "OrdinSearch",  "law",    "자치법규일련번호",   "MST", "LawService",      "자치법규명", True),
    "prec":   Target("prec",   "판례",       "PrecSearch",   "prec",   "판례일련번호",       "ID",  "PrecService",     "사건명",     True),
    "detc":   Target("detc",   "헌재결정례", "DetcSearch",   "Detc",   "헌재결정례일련번호", "ID",  "DetcService",     "사건명",     True),
    "expc":   Target("expc",   "법령해석례", "Expc",         "expc",   "법령해석례일련번호", "ID",  "ExpcService",     "안건명",     True),
    "trty":   Target("trty",   "조약",       "TrtySearch",   "Trty",   "조약일련번호",       "ID",  "BothTrtyService", "조약명",     True),
    "lsStmd": Target("lsStmd", "법령체계도", "LsStmdSearch", "law",    "법령일련번호",       "MST", "LsStmd",          "법령명",     True),

    # ── 행정심판·결정문 ──
    "decc": Target("decc", "행정심판례", "Decc", "decc", "행정심판재결례일련번호", "ID", "PrecService", "사건명", True),
    # ── 별표·서식 / 용어 / 학칙 ──
    "lstrm": Target("lstrm", "법령용어", "LsTrmSearch", "lstrm", "법령용어ID", "trmSeqs", "LsTrmService", "법령용어명", True),
    "school": Target("school", "학칙·공단·공공기관", "AdmRulSearch", "admrul", "행정규칙일련번호", "ID", "AdmRulService", "행정규칙명", True),
    "licbyl": Target("licbyl", "법령 별표·서식", "licBylSearch", "licbyl", "별표일련번호", "ID", "", "별표명", False),
    "admbyl": Target("admbyl", "행정규칙 별표·서식", "admRulBylSearch", "admrulbyl", "별표일련번호", "ID", "LicBylService", "별표명", True),
    "ordinbyl": Target("ordinbyl", "자치법규 별표·서식", "licBylSearch", "ordinbyl", "별표일련번호", "ID", "", "별표명", False),
    # ── 위원회 결정문 12종 ──
    "ppc": Target("ppc", "개인정보보호위원회 결정문", "Ppc", "ppc", "결정문일련번호", "ID", "PpcService", "안건명", True),
    "eiac": Target("eiac", "고용보험심사위원회 결정문", "Eiac", "eiac", "결정문일련번호", "ID", "EiacService", "사건명", True),
    "ftc": Target("ftc", "공정거래위원회 결정문", "Ftc", "ftc", "결정문일련번호", "ID", "FtcService", "사건명", True),
    "acr": Target("acr", "국민권익위원회 결정문", "Acr", "acr", "결정문일련번호", "ID", "AcrService", "제목", True),
    "fsc": Target("fsc", "금융위원회 결정문", "Fsc", "fsc", "결정문일련번호", "ID", "FscService", "안건명", True),
    "nlrc": Target("nlrc", "노동위원회 결정문", "Nlrc", "nlrc", "결정문일련번호", "ID", "NlrcService", "제목", True),
    "kcc": Target("kcc", "방송미디어통신위원회 결정문", "Kcc", "kcc", "결정문일련번호", "ID", "KccService", "안건명", True),
    "iaciac": Target("iaciac", "산업재해보상보험재심사위원회 결정문", "Iaciac", "iaciac", "결정문일련번호", "ID", "IaciacService", "사건", True),
    "oclt": Target("oclt", "중앙토지수용위원회 결정문", "Oclt", "oclt", "결정문일련번호", "ID", "OcltService", "제목", True),
    "ecc": Target("ecc", "중앙환경분쟁조정위원회 결정문", "Ecc", "ecc", "결정문일련번호", "ID", "EccService", "사건명", True),
    "sfc": Target("sfc", "증권선물위원회 결정문", "Sfc", "sfc", "결정문일련번호", "ID", "SfcService", "안건명", True),
    "nhrck": Target("nhrck", "국가인권위원회 결정문", "Nhrck", "nhrck", "결정문일련번호", "ID", "NhrckService", "사건명", True),
    # ── 특별행정심판 5종 ──
    "ttSpecialDecc": Target("ttSpecialDecc", "조세심판원", "Decc", "decc", "특별행정심판재결례일련번호", "ID", "SpecialDeccService", "사건명", True),
    "kmstSpecialDecc": Target("kmstSpecialDecc", "해양안전심판원", "Decc", "decc", "특별행정심판재결례일련번호", "ID", "SpecialDeccService", "사건명", True),
    "acrSpecialDecc": Target("acrSpecialDecc", "국민권익위원회 특별행정심판", "Decc", "decc", "특별행정심판재결례일련번호", "ID", "SpecialDeccService", "사건명", True),
    "adapSpecialDecc": Target("adapSpecialDecc", "인사혁신처 소청심사위원회", "Decc", "decc", "특별행정심판재결례일련번호", "ID", "SpecialDeccService", "사건명", True),
    "baiPvcs": Target("baiPvcs", "감사원 사전컨설팅", "BaiPvcs", "baiPvcs", "감사원사전컨설팅일련번호", "ID", "BaiPvcsService", "의견서명", True),
    # ── 부처 1차 법령해석 39종 ──
    "moeCgmExpc": Target("moeCgmExpc", "교육부 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "moelCgmExpc": Target("moelCgmExpc", "고용노동부 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "molitCgmExpc": Target("molitCgmExpc", "국토교통부 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "moefCgmExpc": Target("moefCgmExpc", "재정경제부 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "", "안건명", False),
    "mofCgmExpc": Target("mofCgmExpc", "해양수산부 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "moisCgmExpc": Target("moisCgmExpc", "행정안전부 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "meCgmExpc": Target("meCgmExpc", "기후에너지환경부 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "kcsCgmExpc": Target("kcsCgmExpc", "관세청 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "ntsCgmExpc": Target("ntsCgmExpc", "국세청 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "", "안건명", False),
    "msitCgmExpc": Target("msitCgmExpc", "과학기술정보통신부 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "mpvaCgmExpc": Target("mpvaCgmExpc", "국가보훈부 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "mndCgmExpc": Target("mndCgmExpc", "국방부 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "mafraCgmExpc": Target("mafraCgmExpc", "농림축산식품부 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "mcstCgmExpc": Target("mcstCgmExpc", "문화체육관광부 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "mojCgmExpc": Target("mojCgmExpc", "법무부 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "mohwCgmExpc": Target("mohwCgmExpc", "보건복지부 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "motieCgmExpc": Target("motieCgmExpc", "산업통상부 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "mogefCgmExpc": Target("mogefCgmExpc", "성평등가족부 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "mofaCgmExpc": Target("mofaCgmExpc", "외교부 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "mssCgmExpc": Target("mssCgmExpc", "중소벤처기업부 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "mouCgmExpc": Target("mouCgmExpc", "통일부 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "molegCgmExpc": Target("molegCgmExpc", "법제처 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "mfdsCgmExpc": Target("mfdsCgmExpc", "식품의약품안전처 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "mpmCgmExpc": Target("mpmCgmExpc", "인사혁신처 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "kmaCgmExpc": Target("kmaCgmExpc", "기상청 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "khsCgmExpc": Target("khsCgmExpc", "국가유산청 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "rdaCgmExpc": Target("rdaCgmExpc", "농촌진흥청 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "npaCgmExpc": Target("npaCgmExpc", "경찰청 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "dapaCgmExpc": Target("dapaCgmExpc", "방위사업청 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "mmaCgmExpc": Target("mmaCgmExpc", "병무청 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "kfsCgmExpc": Target("kfsCgmExpc", "산림청 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "nfaCgmExpc": Target("nfaCgmExpc", "소방청 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "okaCgmExpc": Target("okaCgmExpc", "재외동포청 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "ppsCgmExpc": Target("ppsCgmExpc", "조달청 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "kdcaCgmExpc": Target("kdcaCgmExpc", "질병관리청 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "kostatCgmExpc": Target("kostatCgmExpc", "국가데이터처 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "kipoCgmExpc": Target("kipoCgmExpc", "지식재산처 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "kcgCgmExpc": Target("kcgCgmExpc", "해양경찰청 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
    "naaccCgmExpc": Target("naaccCgmExpc", "행정중심복합도시건설청 법령해석", "CgmExpc", "cgmExpc", "법령해석일련번호", "ID", "CgmExpcService", "안건명", True),
}

# 🔴 **XML 을 주지 않는 target — 부르지 말 것.** 실측(2026-09-08):
#   · `lsHistory`(법령 연혁): `type=XML` 을 **무시하고 HTML** 을 준다
#     (lawSearch.do → 200 text/html 21KB · lawService.do → 200 text/html 1.6KB).
#   · `couseLs`(관련법령): lawSearch.do → 200 **HTML** · lawService.do → **HTTP 404**.
#   둘 다 화면용 연계 정보이지 인용 가능한 문헌이 아니므로 이 저장소의 범위 밖이다.
#   (T41 은 이것을 '미해결'로 남겼다 — 미해결이 아니라 **XML 미지원이 사실**이다.)
HTML_ONLY_TARGETS = {
    "lsHistory": "법령 연혁 — type=XML 을 무시하고 HTML 을 반환한다(실측). 화면용이다.",
    "couseLs":   "관련법령 — lawSearch.do 는 HTML, lawService.do 는 HTTP 404(실측).",
}

# 미해결로 남은 것 하나 — 부처 1차 법령해석(교육부·고용노동부 등)의 target 코드.
# open.law.go.kr 의 안내 목록에는 부처 40여 곳이 실려 있으나 **코드 값이 적혀 있지 않고**,
# 안내 페이지가 자바스크립트로 그려져 본문만 받아서는 링크를 얻을 수 없다(실측).
# T41 이 9개 후보(moe·moel·moleg …)를 시도해 전부 빈 응답이었다 — **더 짐작하지 말 것.**
# 법제처 `expc` 만으로도 579건/'교육' 이 나오므로 당장 막히지는 않는다.
MINISTRY_EXPC_NOTE = (
    "부처 1차 법령해석의 target 코드는 미확인이다(안내 페이지가 JS 렌더링이라 링크를 "
    "받을 수 없고, 후보 9개는 전부 빈 응답). 법제처 유권해석은 `expc` 로 조회된다.")


# 갈래를 사람이 읽기 좋게 묶는다 — 72종을 평평하게 늘어놓으면 고를 수가 없다
# (CLI 출력도, LLM 에게 주는 도구 응답도 마찬가지다).
def target_groups() -> dict[str, list[str]]:
    core = ("law", "eflaw", "elaw", "admrul", "ordin", "lsStmd", "school")
    judg = ("prec", "detc", "decc")
    byl = ("licbyl", "admbyl", "ordinbyl")
    groups: dict[str, list[str]] = {
        "법령·규칙": [c for c in core if c in TARGETS],
        "판례·재결": [c for c in judg if c in TARGETS],
        "법령해석(법제처)": ["expc"],
        "법령해석(부처 39종)": sorted(c for c in TARGETS if c.endswith("CgmExpc")),
        "위원회 결정문": sorted(
            c for c in TARGETS
            if c not in judg and TARGETS[c].id_field == "결정문일련번호"),
        "특별행정심판": sorted(c for c in TARGETS if c.endswith("SpecialDecc")),
        "별표·서식": [c for c in byl if c in TARGETS],
        "조약·용어": [c for c in ("trty", "lstrm") if c in TARGETS],
    }
    known = {c for v in groups.values() for c in v}
    rest = [c for c in TARGETS if c not in known]
    if rest:
        groups["그 밖"] = rest
    return {k: v for k, v in groups.items() if v}


def resolve_target(code: str) -> Target:
    """target 코드 검증 — **호출 전에** 막는다.

    🔴 없는 target 은 오류가 아니라 **HTTP 200 + 빈 본문(0바이트)** 이다(실측).
       그대로 두면 '결과 0건'으로 둔갑한다 — 오타와 '자료 없음'을 구분할 수 없게 된다.
    """
    key = (code or "").strip()
    if not key:
        raise ValueError(f"target 이 비었습니다. 가능한 값: {', '.join(TARGETS)}")
    if key in HTML_ONLY_TARGETS:
        raise ValueError(
            f"`{key}` 는 XML 을 반환하지 않습니다 — {HTML_ONLY_TARGETS[key]} "
            f"이 서버가 다루는 갈래: {', '.join(TARGETS)}")
    if key not in TARGETS:
        near = [k for k in TARGETS if k.lower() == key.lower()]
        hint = f" '{near[0]}' 를 뜻하셨나요?" if near else ""
        # ⚠️ 72종을 전부 나열하면 오류 메시지가 화면을 덮는다. 묶음만 보이고
        #    전체는 `law targets` / `law_targets` 로 안내한다.
        summary = "; ".join(
            f"{g}: {', '.join(v[:4])}{' …' if len(v) > 4 else ''}"
            for g, v in target_groups().items())
        raise ValueError(
            f"알 수 없는 target: {key!r}.{hint} "
            f"가능한 값({len(TARGETS)}종) — {summary}. 전체 목록은 `law_targets`. "
            f"⚠️ 없는 target 은 오류가 아니라 **빈 응답(0바이트)** 으로 오므로 "
            f"여기서 막지 않으면 '결과 0건'으로 오인합니다.")
    return TARGETS[key]


# ── 검색어 ──────────────────────────────────────────────────────────────────
# 🔴 **`query` 를 빼면 오류가 아니라 전체 카탈로그가 온다.** 실측: `target=law` 에
#    query 없이 호출 → `<키워드>*</키워드>` · totalCnt **5,614**(현행법령 전량).
#    `query=교육` 은 159건이다. 자매 API(국회도서관)의 '검색어 무시' 사고와 같은 모양이다.
#    → 빈 검색어는 **거부한다**. 전량이 필요하면 호출자가 명시적으로 와일드카드를 준다.
FULL_CATALOG_QUERY = "*"


def validate_query(query: str, *, allow_wildcard: bool = False) -> str:
    """검색어 검증 — 빈 값이면 거부한다. 정규화된 문자열을 **반드시 써야** 한다.

    🔴 반환값을 버리고 원문을 전송하면 검증이 무의미해진다 — 자매 저장소가 적대적
       리뷰에서 그렇게 잡혔다(공백이 붙은 입력이 검증만 통과하고 서버에서는 무시됨).
    """
    q = (query or "").strip()
    if not q:
        raise ValueError(
            "query 가 비었습니다. 🔴 이 API 는 검색어를 빼면 오류가 아니라 **해당 갈래의 "
            "전체 카탈로그**를 반환합니다(실측: 현행법령 5,614건). 검색어를 주거나, "
            "전량이 필요하면 명시적으로 query 를 '*' 로 주세요.")
    if q == FULL_CATALOG_QUERY and not allow_wildcard:
        raise ValueError(
            "검색어가 '*' 입니다 — 해당 갈래의 **전체 카탈로그**를 받게 됩니다. "
            "의도한 것이면 allow_wildcard=True(도구에서는 allow_full_catalog=True)를 주세요.")
    return q


# 검색 범위(`search` 파라미터) — 1=제목, 2=본문 포함. 기본 1.
SEARCH_SCOPE = {1: "제목(법령명·사건명 등)만", 2: "본문 포함"}


# ── 자격증명(이랄 것도 없는 것) ─────────────────────────────────────────────
def get_oc() -> str | None:
    """`OC` 조회.

    ⚠️ **비밀값이 아니다.** 사용자가 open.law.go.kr 가입 이메일의 @ 앞부분으로 직접
       지정하는 식별자이고, 요청 URL 에 평문으로 실리며 응답의 `…상세링크` 에도 그대로
       되돌아온다(실측). 그러므로 `scrub()` 의 대상이 아니다 — 지우면 상세링크가 망가진다.
       다만 사람마다 값이 다르므로 환경변수로 받는다.
    """
    for name in ("LAW_OC", "LAW_API_OC", "MOLEG_OC"):
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    return None


# 응답·로그에서 지울 것 — 이 API 에는 비밀 인증키가 없으므로 대상이 좁다.
# 다만 사용자가 다른 API 키를 환경에 섞어 두는 경우를 대비해 형태로도 막는다.
_SECRETISH = re.compile(
    r"(?i)\b(serviceKey|apiKey|api_key|authKey|auth_key|secret|token)=[^&\s\"'<>]+")


def scrub(text: str) -> str:
    """오류 메시지·봉투에서 자격증명형 파라미터를 지운다.

    ⚠️ **`OC` 는 지우지 않는다** — 비밀값이 아니고 상세링크의 정상적인 일부다.
       지우면 사용자가 브라우저로 열 수 있는 링크가 깨진다.
    """
    return _SECRETISH.sub(lambda m: m.group(1) + "=***", str(text or ""))


class _ScrubFilter(logging.Filter):
    """로그 인자에서 자격증명형 값을 지운다.

    🔴 **문자열만 건드린다.** 초판은 모든 인자를 `str()` 로 바꿨는데, 그러면
       `log.warning("재시도 %d/%d", 1, 3)` 이 `%d format: a real number is
       required, not str` 로 **로깅 자체를 터뜨린다**. 회귀 테스트가 잡았다 —
       숫자 인자를 쓰는 경고 경로가 실제로 있었다.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = scrub(record.msg)
            if isinstance(record.args, tuple):
                record.args = tuple(
                    scrub(a) if isinstance(a, str) else a for a in record.args)
            elif isinstance(record.args, dict):
                record.args = {
                    k: (scrub(v) if isinstance(v, str) else v)
                    for k, v in record.args.items()}
        except Exception:  # noqa: BLE001  — 로깅이 절대 죽지 않게
            pass
        return True


_scrubber_installed = False


def install_log_scrubber() -> None:
    """urllib3 DEBUG 가 URL 을 통째로 찍는 경로를 막는다(이중 방어)."""
    global _scrubber_installed
    if _scrubber_installed:
        return
    for name in ("urllib3", "urllib3.connectionpool", "requests", "law_mcp"):
        logging.getLogger(name).addFilter(_ScrubFilter())
    _scrubber_installed = True


_trust_done = False


def use_os_trust() -> None:
    """교육망·사내망의 SSL 인터셉션 대응 — OS 신뢰저장소를 쓴다(검증은 유지).

    ⚠️ 등록 명령줄이 아니라 **코드에서** 부른다 — .mcpb/바이너리 배포 경로에는
       명령줄 옵션이 닿지 않는다(자매 저장소에서 확인한 것).
    """
    global _trust_done
    if _trust_done or (os.environ.get("LAW_OS_TRUST", "1").strip() == "0"):
        return
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception as e:  # noqa: BLE001
        logging.getLogger("law_mcp").debug("truststore 미적용: %s", type(e).__name__)
    _trust_done = True
