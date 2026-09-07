"""법제처 DRF HTTP 클라이언트 — 페이징·재시도·절단 메타.

설계에서 값을 치른 두 가지:

1. **검색어 하나가 실패해도 앞서 모은 것을 버리지 않는다.**
   자매 저장소(na-openapi-mcp)의 적대적 검토가 잡은 결함이다 — 첫 페이지 실패를
   그대로 올려 수집 전체가 예외로 끝났고, 이미 회수한 수백 건과 태운 쿼터가 함께
   사라졌다. 여기서는 갈래·검색어마다 결과를 **부분적으로라도 보존**하고 실패는
   `axes[].error` 와 `failed_axes` 로 보고한다.

2. **모든 실패가 HTTP 200 이다.** 상태코드로 판단하지 않는다 — 판단은 parser 가 한다.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Iterable

import requests

from . import __version__
from .config import (
    DEFAULT_DISPLAY,
    MAX_DISPLAY,
    SEARCH_URL,
    SERVICE_URL,
    Target,
    get_oc,
    install_log_scrubber,
    resolve_target,
    scrub,
    use_os_trust,
    validate_query,
)
from .models import Record
from .parser import ApiError, NotFound, ParseError, parse_body, parse_list

log = logging.getLogger("law_mcp")


class LawError(RuntimeError):
    """네트워크·HTTP·파싱을 아우르는 클라이언트 오류."""


class LawClient:
    def __init__(self, *, oc: str | None = None, throttle: float = 0.35,
                 timeout: int = 30, max_retries: int = 3) -> None:
        use_os_trust()          # 등록 명령줄이 아니라 코드에서 — .mcpb/바이너리 경로 대응
        install_log_scrubber()
        self.oc = (oc or get_oc() or "").strip()
        self.throttle = max(0.0, throttle)
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self._session = requests.Session()
        self._session.headers["User-Agent"] = (
            f"law-openapi-mcp/{__version__} "
            f"(+https://github.com/rubatoyd/law-openapi-mcp)")
        self._last = 0.0
        self.calls = 0          # 이 클라이언트가 태운 요청 수(예산 감시용)

    # ── 저수준 ───────────────────────────────────────────────────────────────
    def _require_oc(self) -> None:
        """🔴 OC 누락은 **영구 조건**이다 — 재시도 루프에 들여보내면 안 된다.

        초판은 `_call` 에서만 확인해, OC 가 없을 때 `_page` 의 재시도 3회를 전부
        태우고도 `search` 는 예외 대신 빈 결과 + meta['error'] 를 돌려줬다
        (수집 경로를 계속 굴리려고 1페이지 실패를 삼키게 해 둔 설계와 겹친 것이다).
        설정 오류가 '결과 0건'처럼 보이는 것은 이 저장소가 막겠다는 실패 양식 그대로다.
        """
        if not self.oc:
            raise LawError(
                "OC 가 설정되지 않았습니다. open.law.go.kr 에서 OPEN API 를 신청할 때 "
                "지정한 값(가입 이메일의 @ 앞부분)을 환경변수 LAW_OC 로 주세요.")

    def _sleep(self) -> None:
        gap = time.monotonic() - self._last
        if gap < self.throttle:
            time.sleep(self.throttle - gap)
        self._last = time.monotonic()

    def _call(self, url: str, params: dict) -> bytes:
        """1회 호출 → 본문 **바이트**.

        ⚠️ `resp.text` 를 쓰지 않는다. 이 API 는 Content-Type 에 charset 을 붙여 주지만
           (자매 API 와 다른 점이다) 헤더는 바뀔 수 있고, 바이트를 넘기면 ElementTree 가
           XML 선언을 존중한다. 사실을 이식하지 않고 안전한 쪽을 고른다.
        ⚠️ `raise_for_status()` 를 쓰지 않는다 — requests 가 전체 URL 을 예외에 박는다.
           requests 예외도 **타입만** 남긴다.
        """
        self._require_oc()   # 백스톱 — 정상 경로는 search/body 가 미리 막는다
        self._sleep()
        self.calls += 1
        q = {"OC": self.oc, "type": "XML", **params}
        try:
            resp = self._session.get(url, params=q, timeout=self.timeout)
        except requests.RequestException as e:
            raise LawError(f"요청 실패: {type(e).__name__}") from None
        if resp.status_code == 404:
            # 실측: couseLs 를 lawService.do 로 부르면 404 다.
            raise LawError(
                f"HTTP 404 — 이 target 은 이 엔드포인트에 없습니다"
                f"(실측: couseLs 는 lawService.do 에서 404).")
        if resp.status_code != 200:
            raise LawError(f"HTTP {resp.status_code}")
        return resp.content or b""

    def _page(self, tgt: Target, params: dict, *, expect_records: bool
              ) -> tuple[int, list[Record], dict]:
        """재시도를 포함한 1페이지 조회."""
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return parse_list(self._call(SEARCH_URL, params), tgt,
                                  expect_records=expect_records)
            except ApiError as e:
                last = e
                if not e.retryable:
                    raise LawError(str(e)) from None
                log.warning("일시 오류(%s) — 재시도 %d/%d", e.kind, attempt + 1,
                            self.max_retries)
            except (ParseError, LawError) as e:
                last = e
                log.warning("응답 오류(%s) — 재시도 %d/%d", type(e).__name__,
                            attempt + 1, self.max_retries)
            if attempt < self.max_retries - 1:
                time.sleep(self.throttle * (2 ** attempt) + 0.3)
        raise LawError(scrub(str(last) if last else "알 수 없는 오류"))

    # ── 단일 검색 ────────────────────────────────────────────────────────────
    def search(self, target: str, query: str, *, max_records: int = 100,
               page_size: int | None = None, scope: int = 1,
               allow_full_catalog: bool = False,
               extra: dict | None = None) -> tuple[list[Record], dict[str, Any]]:
        """한 갈래를 한 검색어로 조회 → (레코드, 메타).

        메타에는 **절단 사유를 반드시 싣는다** — 조용히 줄어드는 것을 막는 유일한 방법이다.
        """
        self._require_oc()          # 설정 오류를 재시도 루프에 들여보내지 않는다
        tgt = resolve_target(target)
        # 🔴 검증기가 돌려주는 정규화 문자열을 **그대로 전송한다**(반환값을 버리면 검증이 무의미).
        query = validate_query(query, allow_wildcard=allow_full_catalog)

        size = min(max(1, page_size or DEFAULT_DISPLAY), MAX_DISPLAY)
        want = max(1, int(max_records))

        reserved = {"oc", "type", "target", "query", "page", "display", "search"}
        if extra:
            clash = sorted(k for k in extra if str(k).strip().lower() in reserved)
            if clash:
                raise LawError(
                    f"extra 로 예약 파라미터를 덮어쓸 수 없습니다: {', '.join(clash)}. "
                    f"검증·페이징·인증을 무력화하고 meta 가 거짓을 보고하게 됩니다.")

        records: list[Record] = []
        seen: set[str] = set()
        meta: dict[str, Any] = {
            "target": tgt.code, "target_label": tgt.label, "query": query,
            "page_size": size, "requested": want, "scope": scope,
            "pages_fetched": 0, "failed_pages": [],
        }
        total = 0
        page = 1
        while len(records) < want:
            params = {"target": tgt.code, "query": query, "display": size,
                      "page": page, "search": scope}
            if extra:
                params.update(extra)
            try:
                total, recs, env = self._page(tgt, params, expect_records=(page == 1))
            except LawError as e:
                meta["failed_pages"].append({"page": page, "error": scrub(str(e))})
                if page == 1:
                    # 🔴 1페이지 실패라도 **예외로 올리지 않는다** — 호출자(수집)가 다른
                    #    갈래·검색어를 계속할 수 있어야 한다. 사실은 meta 에 남긴다.
                    meta["total"] = 0
                    meta["fetched"] = 0
                    meta["error"] = scrub(str(e))
                    return [], meta
                break

            meta["pages_fetched"] += 1
            meta.setdefault("envelope", env)
            # display 절삭 탐지.
            # 🔴 `numOfRows` 는 요청한 페이지 크기가 아니라 **실제로 돌려준 건수**다
            #    (실측: display=100·total=3 → numOfRows=3). 그래서 `echo != size` 만
            #    보면 결과가 적을 때마다 "서버가 3으로 깎았다"는 거짓 경고가 나고,
            #    더 나쁘게는 size 를 3으로 줄여 이후 페이징이 3건씩 기어간다.
            #    진짜 절삭은 **줄 것이 더 있는데 덜 준** 경우뿐이다.
            echo = env.get("numOfRows")
            if echo and str(echo).isdigit():
                echoed = int(echo)
                if echoed < size and total > echoed:
                    meta["page_size_note"] = (
                        f"요청한 display={size} 가 서버에서 {echoed} 로 깎였습니다"
                        f"(실측 상한 {MAX_DISPLAY}). 남은 건수는 페이지를 넘겨 받습니다.")
                    size = echoed

            new = 0
            for r in recs:
                k = r.dedup_key()
                if k in seen:
                    continue
                seen.add(k)
                records.append(r)
                new += 1
                if len(records) >= want:
                    break

            if not recs or new == 0:
                if total and len(records) < min(total, want):
                    meta["early_stop_note"] = (
                        f"page {page} 에서 새 레코드가 0건이라 중단했습니다 — "
                        f"total {total:,}건 중 {len(records):,}건만 회수했습니다. "
                        f"전수가 아닙니다(중복 응답 또는 서버 이상 가능).")
                break
            if total and len(records) >= total:
                break                    # 다 받았다 — 끝을 지난 페이지를 부르지 않는다
            page += 1

        meta["total"] = total
        meta["fetched"] = len(records)
        # 🔴 이 API 에는 회수 한계가 없다(page 하드 상한 없음 — 실측). 그래서 절단은
        #    오직 우리가 건 예산(max_records) 때문이다. 자매 API 의 cap_hit 과 구분된다.
        meta["truncated"] = total > len(records)
        if meta["truncated"]:
            meta["truncated_note"] = (
                f"total {total:,}건 중 {len(records):,}건만 회수했습니다 — "
                f"max_records({want:,})가 예산입니다. 이 API 는 page 상한이 없으므로 "
                f"max_records 를 올리면 전량을 받을 수 있습니다.")
        if meta["failed_pages"]:
            meta["incomplete_note"] = (
                f"{len(meta['failed_pages'])}개 페이지가 재시도 후에도 실패해 결손입니다 — "
                f"전수가 아닙니다.")
        return records, meta

    # ── 갈래 × 검색어 합집합 ─────────────────────────────────────────────────
    def collect(self, targets: Iterable[str], queries: Iterable[str], *,
                max_records: int = 200, page_size: int | None = None,
                scope: int = 1, allow_full_catalog: bool = False,
                per_axis_cap: int | None = None,
                ) -> tuple[list[Record], dict[str, Any]]:
        """갈래 × 검색어의 **합집합**을 모은다.

        🔴 **한 축이 실패해도 나머지는 계속한다.** 실패는 `axes[].error` 로 남기고
           `failed_axes` 에 모아 최상위로 올린다 — 조용히 사라지지 않게.
        ⚠️ `max_records` 는 **전체에 걸친 예산**이다. 앞선 축이 다 쓰면 뒤 축은 아예
           조회되지 않으므로 그 사실을 `axes_unsearched` 로 반드시 알린다.
        """
        tlist = [t.strip() for t in targets if str(t).strip()]
        qlist = [q.strip() for q in queries if str(q).strip()]
        if not tlist or not qlist:
            raise LawError("targets 와 queries 를 각각 하나 이상 주세요.")
        self._require_oc()
        for t in tlist:
            resolve_target(t)      # 호출 전에 전부 검증 — 하나라도 틀리면 시작하지 않는다

        pairs = [(t, q) for t in tlist for q in qlist]
        cap = per_axis_cap or max(1, max_records // max(1, len(pairs)) * 2)

        merged: list[Record] = []
        seen: set[str] = set()
        axes: list[dict] = []
        unsearched: list[dict] = []

        for i, (t, q) in enumerate(pairs):
            remaining = max_records - len(merged)
            if remaining <= 0:
                unsearched = [{"target": a, "query": b} for a, b in pairs[i:]]
                break
            recs, m = self.search(t, q, max_records=min(remaining, cap),
                                  page_size=page_size, scope=scope,
                                  allow_full_catalog=allow_full_catalog)
            new = 0
            for r in recs:
                k = r.dedup_key()
                if k in seen:
                    continue
                seen.add(k)
                merged.append(r)
                new += 1
            axis = {"target": t, "query": q, "total": m.get("total", 0),
                    "fetched": m.get("fetched", 0), "new": new}
            # 축별 경고를 **여기서 버리면 수집 경로에는 방어선이 사라진다**.
            for key in ("error", "truncated_note", "early_stop_note",
                        "incomplete_note", "page_size_note"):
                if m.get(key):
                    axis[key] = m[key]
            axes.append(axis)

        meta: dict[str, Any] = {
            "targets": tlist, "queries": qlist,
            "axes": axes, "axes_planned": len(pairs), "axes_searched": len(axes),
            "axes_unsearched": unsearched,
            "failed_axes": [f"{a['target']}/{a['query']}" for a in axes if a.get("error")],
            "fetched": len(merged), "requested": max_records,
            "api_calls": self.calls,
        }
        if unsearched:
            meta["stopped_early_note"] = (
                f"max_records({max_records:,})를 앞선 축에서 모두 소진해 "
                f"{len(unsearched)}개 축을 **조회하지 않았습니다**. 합집합이 완전하지 "
                f"않습니다 — max_records 를 올리거나 나눠 실행하세요.")
        if meta["failed_axes"]:
            meta["failed_axes_note"] = (
                f"다음 축이 실패했습니다(나머지는 정상 수집됐습니다): "
                f"{', '.join(meta['failed_axes'])}")
        for key in ("truncated_note", "early_stop_note", "incomplete_note"):
            hits = [f"{a['target']}/{a['query']}" for a in axes if a.get(key)]
            if hits:
                sample = next(a[key] for a in axes if a.get(key))
                meta[key] = f"[{', '.join(hits)}] {sample}"
        return merged, meta

    # ── 본문 ─────────────────────────────────────────────────────────────────
    def body(self, target: str, doc_id: str, *, ef_date: str | None = None,
             ) -> tuple[dict[str, Any], dict[str, Any]]:
        """식별자 1건의 본문.

        🔴 **`NotFound` 는 사고가 아닐 수 있다.** 판례는 데이터출처에 따라 본문이 없다
           (실측: 데이터출처명=국세법령정보시스템 → 목록에는 있는데 본문은 "일치하는
           판례가 없습니다"). 호출자가 결손으로 기록하도록 예외 종류를 구분해 올린다.

        `ef_date` — 시행일법령(`eflaw`) 전용. 🔴 `MST` 만 주면 **HTML 이 온다**(실측).
        시행일법령은 같은 법령의 시행일별 판본이라 (MST, efYd) 한 쌍이 신원이다.
        """
        self._require_oc()
        tgt = resolve_target(target)
        ident = (str(doc_id) or "").strip()
        if not ident:
            raise LawError(
                f"식별자가 비었습니다 — 목록 결과의 `{tgt.id_field}` 를 주세요 "
                f"(본문 조회 파라미터는 {tgt.id_param} 입니다).")

        params = {"target": tgt.code, tgt.id_param: ident}
        for param, source_field in tgt.body_extra:
            value = (ef_date or "").strip() if param == "efYd" else ""
            if not value:
                raise LawError(
                    f"`{tgt.label}`({tgt.code}) 본문에는 `{param}` 가 함께 필요합니다 — "
                    f"목록 결과의 `{source_field}` 값을 주세요(ef_date 인자). "
                    f"🔴 없이 부르면 오류가 아니라 **HTML 페이지**가 옵니다(실측). "
                    f"같은 법령이 시행일마다 다른 판본이라 "
                    f"({tgt.id_param}, {param}) 한 쌍이 신원입니다.")
            params[param] = value.replace("-", "")   # YYYYMMDD 로 되돌린다
        last: Exception | None = None
        for attempt in range(min(2, self.max_retries)):   # 단건은 재시도를 줄인다
            try:
                return parse_body(self._call(SERVICE_URL, params), tgt)
            except NotFound:
                raise                      # 재시도 무의미 — 사실이다
            except ApiError as e:
                last = e
                if not e.retryable:
                    raise LawError(str(e)) from None
            except (ParseError, LawError) as e:
                last = e
            time.sleep(self.throttle * 2 + 0.3)
        raise LawError(scrub(f"{tgt.label} 본문 조회 실패({tgt.id_param}={ident}): {last}"))

    def status(self) -> dict[str, Any]:
        """연결 점검 — 실제 왕복 1회."""
        info: dict[str, Any] = {
            "has_oc": bool(self.oc),
            "api": "법제처 국가법령정보 OPEN API (www.law.go.kr/DRF)",
            "max_display": MAX_DISPLAY,
            "page_hard_cap": None,
        }
        if not self.oc:
            info["ok"] = False
            info["note"] = ("LAW_OC 미설정 — open.law.go.kr 에서 OPEN API 신청 시 지정한 "
                            "값(가입 이메일의 @ 앞부분)을 환경변수로 주세요.")
            return info
        try:
            recs, m = self.search("law", "교육", max_records=1, page_size=1)
            info["ok"] = True
            info["probe"] = {"target": "law", "query": "교육",
                             "total": m.get("total"), "returned": len(recs)}
            info["note"] = "OC 유효 — 목록 조회 정상."
        except Exception as e:  # noqa: BLE001
            info["ok"] = False
            info["note"] = scrub(f"{type(e).__name__}: {e}")
        return info
