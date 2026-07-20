# -*- coding: utf-8 -*-
"""
# rerun4: 2026-07-20 익일 키 동기화 확인
bldg.py — 건축물대장(건축HUB) 표제부 대조로 상가·빌딩(통건물) 마스킹 지번 특정
- 입력: data/nrg_*.csv (국토부 상업업무용 실거래, collect.py 산출물)
        data/rtms_*.csv (서울시 주택 실거래 — 법정동명→법정동코드 매핑용)
- 출력: data/bldg/{시군구코드}_{법정동코드}.csv  (동별 표제부 캐시, 1회 수집 후 재사용)
        data/bldg_match.csv                      (마스킹 지번 → 후보 필지 매칭 결과)
        data/bldg_unmapped_dongs.csv             (법정동코드 매핑 실패 동 — 수동 보완용)
- 원칙: 신고 원본만 사용, 추정 금지. 매칭 조건(지번 패턴 + 대지면적 + 준공년도)을 모두
        만족하는 후보만 기록하고, 후보 수를 그대로 남긴다(후보 1건 = 사실상 특정).
"""
import csv, glob, os, re, sys, time
import urllib.request, urllib.parse
import xml.etree.ElementTree as ET

KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()
if not KEY:
    sys.exit("환경변수 DATA_GO_KR_KEY 가 없습니다 (GitHub Secret 확인)")

API = "http://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo"  # 주의: 이 서비스는 http (PublicDataReader 검증 구현과 동일)
MAX_CALLS = int(os.environ.get("BLDG_MAX_CALLS", "8000"))   # 일일 트래픽 보호(10,000/일 한도 가정)
ROWS_PER_PAGE = 100
AREA_TOL_PCT = 0.02      # 대지면적 허용 오차 ±2%
AREA_TOL_MIN = 1.0       # 최소 허용 오차 ±1㎡
SLEEP = 0.15

os.makedirs("data/bldg", exist_ok=True)
calls = 0

def api_get(params):
    """XML 응답 파싱. 반환: (totalCount, [item dict...])"""
    global calls
    calls += 1
    q = urllib.parse.urlencode({**params, "serviceKey": KEY, "numOfRows": ROWS_PER_PAGE})
    url = f"{API}?{q}"
    body, last_err = "", ""
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (rtms-bldg)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
            root = ET.fromstring(body)
            if root.tag == "OpenAPI_ServiceResponse":  # data.go.kr 표준 오류(키 미승인 등)
                msg = (root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or "").strip()
                code = (root.findtext(".//returnReasonCode") or "").strip()
                raise PermissionError(f"API 거부 [{code}] {msg} — 건축HUB 활용신청 승인 여부 확인 필요")
            rc = (root.findtext(".//header/resultCode") or "").strip()
            if rc not in ("", "00", "0"):
                raise RuntimeError(f"API 오류 {rc}: {root.findtext('.//header/resultMsg')}")
            total = int(root.findtext(".//body/totalCount") or 0)
            items = [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
            return total, items
        except PermissionError:
            raise
        except Exception as e:
            last_err = repr(e)
            if attempt == 2:
                raise RuntimeError(f"호출 실패: {last_err} / 원문: {body[:300]!r}")
            time.sleep(2 * (attempt + 1))
    return 0, []

def fetch_dong(sgg, bjd):
    """동 전체 표제부 수집(페이지네이션). 완료 시에만 캐시 파일 생성."""
    global calls
    path = f"data/bldg/{sgg}_{bjd}.csv"
    if os.path.exists(path):
        return path
    rows, page, total = [], 1, 0
    while True:
        if calls >= MAX_CALLS:
            print(f"  [예산 소진] {sgg}/{bjd} 중단 — 다음 실행에서 이어서 수집")
            return None
        total, items = api_get({"sigunguCd": sgg, "bjdongCd": bjd, "pageNo": page})
        if not items:
            break
        rows.extend(items)
        if page * ROWS_PER_PAGE >= total:
            break
        page += 1
        time.sleep(SLEEP)
    cols = ["sigunguCd", "bjdongCd", "platGbCd", "bun", "ji", "bldNm", "splotNm",
            "regstrKindCdNm", "mainPurpsCdNm", "etcPurps", "platArea", "archArea",
            "totArea", "useAprDay", "grndFlrCnt", "ugrndFlrCnt", "platPlc"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])
    print(f"  캐시 완료 {sgg}/{bjd}: {len(rows)}건 (신고 {total})")
    return path

def build_dong_map():
    """rtms_*.csv 의 STDG_NM/STDG_CD 로 (구코드, 동명) → 법정동코드5 매핑."""
    m = {}
    for p in glob.glob("data/rtms_*.csv"):
        gu = os.path.basename(p).split("_")[1]
        with open(p, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                nm = (row.get("STDG_NM") or "").strip()
                cd = re.sub(r"\D", "", (row.get("STDG_CD") or ""))
                if not nm or not cd:
                    continue
                bjd = cd[5:10] if len(cd) >= 10 else cd.zfill(5)
                m[(gu, nm)] = bjd
    return m

def jibun_str(bun, ji):
    try:
        b, j = int(bun or 0), int(ji or 0)
    except ValueError:
        return ""
    return f"{b}-{j}" if j else str(b)

def mask_to_re(mask):
    return re.compile("^" + re.escape(mask).replace(r"\*", ".*") + "$")

def load_masked_deals():
    deals = []
    for p in glob.glob("data/nrg_*.csv"):
        with open(p, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                jb = (row.get("jibun") or "").strip()
                btype = (row.get("buildingType") or "").strip()
                if "*" not in jb or (btype and "일반" not in btype):
                    continue  # 통건물(일반)만, 마스킹 지번만
                deals.append({
                    "sgg": (row.get("sggCd") or "").strip(),
                    "gu": (row.get("estateAgentSggNm") or row.get("sggNm") or "").strip(),
                    "dong": (row.get("umdNm") or "").strip(),
                    "jibun": jb.replace("산", "").strip() if jb.startswith("산") else jb,
                    "san": jb.startswith("산"),
                    "area": (row.get("plottageAr") or "").strip(),
                    "byear": re.sub(r"\D", "", (row.get("buildYear") or ""))[:4],
                    "ymd": f"{row.get('dealYear','')}-{str(row.get('dealMonth','')).zfill(2)}-{str(row.get('dealDay','')).zfill(2)}",
                    "amt": (row.get("dealAmount") or "").replace(",", "").strip(),
                    "use": (row.get("buildingUse") or "").strip(),
                })
    return deals

def selftest():
    """같은 키로 A/B 비교: NrgTrade(정상 작동 확인됨) vs 건축HUB. 키는 로그에 출력하지 않음."""
    tests = [
        ("NrgTrade(대조군)", f"https://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade?serviceKey={KEY}&LAWD_CD=11680&DEAL_YMD=202501&numOfRows=1"),
        ("건축HUB 표제부", f"http://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo?serviceKey={KEY}&sigunguCd=11680&bjdongCd=10800&numOfRows=1&pageNo=1"),
        ("건축HUB 표제부(bun지정)", f"http://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo?serviceKey={KEY}&sigunguCd=11680&bjdongCd=10800&platGbCd=0&bun=0001&ji=0000&numOfRows=1&pageNo=1"),
        ("건축HUB 기본개요", f"http://apis.data.go.kr/1613000/BldRgstHubService/getBrBasisOulnInfo?serviceKey={KEY}&sigunguCd=11680&bjdongCd=10800&numOfRows=1&pageNo=1"),
        ("구버전 BldRgstService_v2", f"http://apis.data.go.kr/1613000/BldRgstService_v2/getBrTitleInfo?serviceKey={KEY}&sigunguCd=11680&bjdongCd=10800&numOfRows=1&pageNo=1"),
    ]
    for name, url in tests:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (rtms-bldg)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                b = r.read()
                hdrs = {k: v for k, v in r.getheaders() if k.lower() in ("content-type", "content-length", "server", "x-forwarded-for", "location", "set-cookie", "cmcd-error")}
            print(f"[진단 {name}] status={r.status} len={len(b)} headers={hdrs} 앞200바이트={b[:200]!r}")
        except Exception as e:
            print(f"[진단 {name}] 예외: {e!r}")

def main():
    selftest()
    deals = load_masked_deals()
    print(f"마스킹 지번 통건물 거래: {len(deals)}건")
    dmap = build_dong_map()

    # 동별 거래 수 집계 → 거래 많은 동부터 수집(예산 효율)
    need, unmapped = {}, {}
    for d in deals:
        key = (d["sgg"], d["dong"])
        bjd = dmap.get(key)
        if not bjd:
            unmapped[key] = unmapped.get(key, 0) + 1
            continue
        need.setdefault((d["sgg"], bjd), 0)
        need[(d["sgg"], bjd)] += 1
    if unmapped:
        with open("data/bldg_unmapped_dongs.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f); w.writerow(["sggCd", "동명", "거래수"])
            for (sgg, nm), n in sorted(unmapped.items(), key=lambda x: -x[1]):
                w.writerow([sgg, nm, n])
        print(f"법정동코드 매핑 실패 동 {len(unmapped)}개 → data/bldg_unmapped_dongs.csv")

    fetched, errors = {}, 0
    for (sgg, bjd), n in sorted(need.items(), key=lambda x: -x[1]):
        try:
            p = fetch_dong(sgg, bjd)
        except PermissionError as e:
            print(f"[중단] {e}")
            break
        except Exception as e:
            errors += 1
            print(f"  [오류] {sgg}/{bjd}: {e}")
            if errors >= 5:
                print("[중단] 연속 오류 과다 — 원인 확인 필요")
                break
            continue
        if p:
            fetched[(sgg, bjd)] = p
        if calls >= MAX_CALLS:
            break
    print(f"API 호출 {calls}회 / 캐시 보유 동 {len(fetched)} / 필요 동 {len(need)}")

    # 매칭
    out = []
    cache_rows = {}
    for (sgg, bjd), p in fetched.items():
        with open(p, encoding="utf-8-sig") as f:
            cache_rows[(sgg, bjd)] = list(csv.DictReader(f))
    for d in deals:
        bjd = dmap.get((d["sgg"], d["dong"]))
        rows = cache_rows.get((d["sgg"], bjd))
        if rows is None:
            continue  # 아직 캐시 없는 동
        try:
            area = float(d["area"])
        except ValueError:
            continue
        tol = max(AREA_TOL_MIN, area * AREA_TOL_PCT)
        rx = mask_to_re(d["jibun"])
        cands = []
        for r in rows:
            if d["san"] != (str(r.get("platGbCd", "0")).strip() == "1"):
                continue
            js = jibun_str(r.get("bun"), r.get("ji"))
            if not js or not rx.match(js):
                continue
            try:
                pa = float(r.get("platArea") or 0)
            except ValueError:
                continue
            if pa <= 0 or abs(pa - area) > tol:
                continue
            if d["byear"]:
                apr = re.sub(r"\D", "", r.get("useAprDay") or "")[:4]
                if apr and apr != d["byear"]:
                    continue
            cands.append((js, r))
        # 동일 지번의 대장(일반/집합 등) 중복 → 지번 단위로 축약, 일반 우선
        by_jb = {}
        for js, r in cands:
            cur = by_jb.get(js)
            if cur is None or ("일반" in (r.get("regstrKindCdNm") or "") and "일반" not in (cur.get("regstrKindCdNm") or "")):
                by_jb[js] = r
        cand_txt = "; ".join(
            f"{js}({r.get('platArea')}㎡,{(r.get('useAprDay') or '')[:4]},{r.get('bldNm') or r.get('mainPurpsCdNm') or ''})"
            for js, r in sorted(by_jb.items()))
        out.append([d["gu"], d["dong"], d["ymd"], d["amt"], d["use"], d["jibun"],
                    d["area"], d["byear"], len(by_jb), cand_txt])

    with open("data/bldg_match.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["구", "법정동", "계약일", "거래금액(만원)", "건물용도", "지번(마스킹)",
                    "대지면적㎡", "준공년도", "후보수", "후보필지(지번,대지㎡,준공,건물명)"])
        w.writerows(out)

    n1 = sum(1 for r in out if r[8] == 1)
    n0 = sum(1 for r in out if r[8] == 0)
    print(f"매칭 완료: 처리 {len(out)}건 / 단일 특정 {n1}건 / 후보 없음 {n0}건 → data/bldg_match.csv")

if __name__ == "__main__":
    main()
