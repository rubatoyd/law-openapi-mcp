# 법제처 DRF 전체 카탈로그 — 안내 문서에서 뽑은 target 목록 (99종)

> 출처: `open.law.go.kr/LSO/openApi/guideList.do` 의 안내 195건을 각각 열어
> `요청 URL : …?target=<값>` 을 읽었다(2026-09-08, 브라우저).
> **이 표는 '문서에 있다'까지다**(📄). 실제 응답 모양은 `docs/LAW_API_GUIDE.md` §3 이
> 권위이고, 그쪽은 라이브 실측(✅)이다. 이 파일은 **무엇이 있는지의 지도**다.

## 🔴 부처 법령해석 target 은 `<부처><b>CgmExpc</b>` 다 — 순서가 뒤집혀 있다

T41 이 미해결로 남긴 것이 이것이다. 안내 페이지의 **함수 이름**은 `cgmExpcMoeListGuide`
인데 **실제 target 은 `moeCgmExpc`** 로 순서가 반대다. T41 이 시도한 후보 9개
(`moe`·`moel`·`moleg` …)가 전부 빈 응답이었던 이유가 이것이다 — 부처 코드 **단독으로는
아무것도 아니고**, `CgmExpc` 접미가 붙어야 한다.

안내 페이지가 자바스크립트로 그려져 본문만 받아서는 링크를 얻을 수 없다.
**브라우저로 열어야** 나온다(그래서 여기까지 오는 데 한 번의 브라우저 왕복이 필요했다).

⚠️ 안내 문서는 `display` 를 `default=20 max=100` 이라고 적는다. 그러나 실측 상한은
**500** 이다(GUIDE §5). 자매 저장소에서도 문서가 100, 실제가 1000이었다 —
**문서의 상한을 믿지 말 것.**

## 갈래 39종 — 부처 1차 법령해석 (`…CgmExpc`)

| target | 부처 | 목록 | 본문 |
|---|---|:--:|:--:|
| `moeCgmExpc` | 교육부 | ○ | ○ |
| `moelCgmExpc` | 고용노동부 | ○ | ○ |
| `molitCgmExpc` | 국토교통부 | ○ | ○ |
| `moefCgmExpc` | 재정경제부 | ○ | ✕ |
| `mofCgmExpc` | 해양수산부 | ○ | ○ |
| `moisCgmExpc` | 행정안전부 | ○ | ○ |
| `meCgmExpc` | 기후에너지환경부 | ○ | ○ |
| `kcsCgmExpc` | 관세청 | ○ | ○ |
| `ntsCgmExpc` | 국세청 | ○ | ✕ |
| `msitCgmExpc` | 과학기술정보통신부 | ○ | ○ |
| `mpvaCgmExpc` | 국가보훈부 | ○ | ○ |
| `mndCgmExpc` | 국방부 | ○ | ○ |
| `mafraCgmExpc` | 농림축산식품부 | ○ | ○ |
| `mcstCgmExpc` | 문화체육관광부 | ○ | ○ |
| `mojCgmExpc` | 법무부 | ○ | ○ |
| `mohwCgmExpc` | 보건복지부 | ○ | ○ |
| `motieCgmExpc` | 산업통상부 | ○ | ○ |
| `mogefCgmExpc` | 성평등가족부 | ○ | ○ |
| `mofaCgmExpc` | 외교부 | ○ | ○ |
| `mssCgmExpc` | 중소벤처기업부 | ○ | ○ |
| `mouCgmExpc` | 통일부 | ○ | ○ |
| `molegCgmExpc` | 법제처 | ○ | ○ |
| `mfdsCgmExpc` | 식품의약품안전처 | ○ | ○ |
| `mpmCgmExpc` | 인사혁신처 | ○ | ○ |
| `kmaCgmExpc` | 기상청 | ○ | ○ |
| `khsCgmExpc` | 국가유산청 | ○ | ○ |
| `rdaCgmExpc` | 농촌진흥청 | ○ | ○ |
| `npaCgmExpc` | 경찰청 | ○ | ○ |
| `dapaCgmExpc` | 방위사업청 | ○ | ○ |
| `mmaCgmExpc` | 병무청 | ○ | ○ |
| `kfsCgmExpc` | 산림청 | ○ | ○ |
| `nfaCgmExpc` | 소방청 | ○ | ○ |
| `okaCgmExpc` | 재외동포청 | ○ | ○ |
| `ppsCgmExpc` | 조달청 | ○ | ○ |
| `kdcaCgmExpc` | 질병관리청 | ○ | ○ |
| `kostatCgmExpc` | 국가데이터처 | ○ | ○ |
| `kipoCgmExpc` | 지식재산처 | ○ | ○ |
| `kcgCgmExpc` | 해양경찰청 | ○ | ○ |
| `naaccCgmExpc` | 행정중심복합도시건설청 | ○ | ○ |

## 갈래 60종 — 그 밖

### 인용 가능한 문헌 (이 저장소가 다루거나 다룰 대상)

| target | 갈래 | 목록 | 본문 |
|---|---|:--:|:--:|
| `law` | 현행법령(공포일) | ○ | ○ |
| `eflaw` | 현행법령(시행일) | ○ | ○ |
| `elaw` | 영문법령 | ○ | ○ |
| `admrul` | 행정규칙 | ○ | ○ |
| `ordin` | 자치법규 | ○ | ○ |
| `prec` | 판례 | ○ | ○ |
| `detc` | 헌재결정례 | ○ | ○ |
| `expc` | 법령해석례(법제처) | ○ | ○ |
| `decc` | 행정심판례 | ○ | ○ |
| `trty` | 조약 | ○ | ○ |
| `lstrm` | 법령용어 | ○ | ○ |
| `school` | 학칙·공단·공공기관 | ○ | ○ |
| `licbyl` | 법령 별표·서식 | ○ | ✕ |
| `admbyl` | 행정규칙 별표·서식 | ○ | ✕ |
| `ordinbyl` | 자치법규 별표·서식 | ○ | ✕ |
| `lsStmd` | 법령 체계도 | ○ | ○ |

**위원회 결정문 12종** — 전부 목록·본문 있음:
`ppc`(개인정보보호위) · `eiac`(고용보험심사위) · `ftc`(공정거래위) · `acr`(국민권익위) ·
`fsc`(금융위) · `nlrc`(노동위) · `kcc`(방송미디어통신위) · `iaciac`(산재보험재심사위) ·
`oclt`(중앙토지수용위) · `ecc`(중앙환경분쟁조정위) · `sfc`(증권선물위) · `nhrck`(국가인권위)

**특별행정심판 5종** — 전부 목록·본문 있음:
`ttSpecialDecc`(조세심판원) · `kmstSpecialDecc`(해양안전심판원) ·
`acrSpecialDecc`(국민권익위) · `adapSpecialDecc`(인사혁신처 소청심사위) ·
`baiPvcs`(감사원 사전컨설팅)

### 문헌이 아닌 것 — 연계·분석·검색 보조 (이 저장소의 범위 밖)

인용할 수 있는 '문헌'이 아니라 화면·분석을 돕는 연계 정보다. 수집 단위가 인용 단위라는
원칙(CLAUDE.md §2)에 따라 다루지 않는다.

`lsHistory`(법령 연혁) · `lsHstInf`(법령 변경이력) · `lsJoHstInf`(일자별 조문 개정 이력) ·
`lawjosub`·`eflawjosub`(조항호목 조회) · `lsDelegated`(위임법령) · `oldAndNew`(신구법) ·
`admrulOldAndNew` · `thdCmp`(3단 비교) · `oneview`(한눈보기) · `lsAbrv`(법률명 약칭) ·
`delHst`(삭제 데이터) · `lnkLs`·`lnkOrd`·`drlaw`(법령–자치법규 연계) · `lsRlt`(관련법령) ·
`couseLs`·`couseAdmrul`·`couseOrdin`(맞춤형) · `lstrmAI`·`dlytrm`·`lstrmRlt`·`dlytrmRlt`·
`lstrmRltJo`·`joRltLstrm`(용어 연계) · `aiSearch`·`aiRltLs`(지능형 검색)

⚠️ 이 중 `lsHistory`·`couseLs` 는 **문서에 `type` 이 있는데도 실제로는 HTML 만 준다**
(✅ 실측, GUIDE §10). 나머지 연계 갈래도 같을 수 있으나 확인하지 않았다 — 범위 밖이라서다.
