# -*- coding: utf-8 -*-
"""
bldg.py — 건축물대장(건축HUB) 표제부 대조로 상가·빌딩(통건물) 마스킹 지번 특정
- 입력: data/nrg_*.csv (국토부 상업업무용 실거래, collect.py 산출물)
        data/rtms_*.csv (서울시 주택 실거래 — 법정동명→법정동코드 매핑용)
- 출력: data/bldg/{시군구코드}_{법정동코드}.csv  (동별 표제부 캐시, 1회 수집 후 재사용)
        data/bldg_match.csv                      (마스킹 지번 → 후보 필지 매칭 결과)
        data/bldg_unmapped_dongs.csv             (법정동코드 매핑 실패 동 — 수동 보완용)
- 원칙: 신고 원본만 사용, 추정 금지. 매칭 조건(지번 패턴 + 대지면적 + 준공년도)을 모두
        만족하는 후보만 기록하고, 후보 수를 그대로 남긴다(후보 1건 = 사실상 특정).
"""
import csv, glob, json, os, re, sys, time
import urllib.request, urllib.parse

KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()
if not KEY:
    sys.exit("환경변수 DATA_GO_KR_KEY 가 없습니다 (GitHub Secret 확인)")

API = "https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo"
MAX_CALLS = int(os.environ.get("BLDG_MAX_CALLS", "8000"))   # 일일 트래픽 보호(10,000/일 한도 가정)
ROWS_PER_PAGE = 100
AREA_TOL_PCT = 0.02      # 대지면적 허용 오차 ±2%
AREA_TOL_MIN = 1.0       # 최소 허용 오차 ±1㎡
SLEEP = 0.15

os.makedirs("data/bldg", exist_ok=True)
calls = 0

def api_get(params):
    global calls
    calls += 1
    q = urllib.parse.urlencode({**params, "serviceKey": KEY, "_type": "json",
                                "numOfRows": ROWS_PER_PAGE})
    url = f"{API}?{q}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
            if body.lstrip().startswith("<"):  # 키 미승인/오류 시 XML 에러 반환
                raise RuntimeError(f"XML 응답(키 미승인/한도초과 의심): {body[:200]}")
            j = json.loads(body)
            hdr = j["response"]["header"]
            if hdr.get("resultCode") not in ("00", "0"):
                raise RuntimeError(f"API 오류 {hdr.get('resultCode')}: {hdr.get('resultMsg')}")
            return j["response"]["body"]
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    return None

def fetch_dong(sgg, bjd):
    """동 전체 표제부 수집(페이지네이션). 완료 시에만 캐시 파일 생성."""
    global calls
    path = f"data/bldg/{sgg}_{bjd}.csv"
    if os.path.exists(path):
        return path
    rows, page, total = [], 1, None
    while True:
        if calls >= MAX_CALLS:
            print(f"  [예산 소진] {sgg}/{bjd} 중단 — 다음 실행에서 이어서 수집")
            return None
        body = api_get({"sigunguCd": sgg, "bjdongCd": bjd, "pageNo": page})
        total = int(body.get("totalCount", 0))
        items = (body.get("items") or {})
        item = items.get("item") if isinstance(items, dict) else None
        if item is None:
            break
        if isinstance(item, dict):
            item = [item]
        rows.extend(item)
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

def main():
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

    fetched = {}
    for (sgg, bjd), n in sorted(need.items(), key=lambda x: -x[1]):
        p = fetch_dong(sgg, bjd)
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
