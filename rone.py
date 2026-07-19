# -*- coding: utf-8 -*-
"""
rone.py — 한국부동산원 R-ONE 부동산통계 수집 (상업용부동산 임대동향조사)
목적: 상권별 임대료 / 공실률 / 소득수익률(실측 캡레이트) / 전환율 자동 수집
1단계(자동): 통계표 목록 전체 수집 → data/rone/tables.csv
2단계(자동): 이름에 '상업용' + (임대료|공실|수익률|전환율) 포함 통계표를 자동 선별해
             각 표의 데이터를 data/rone/{STATBL_ID}.csv 로 저장
로그: data/rone_log.txt (워크플로가 커밋) — 키는 로그에 출력하지 않음
"""
import csv, json, os, sys, time
import urllib.request, urllib.parse

KEY = os.environ.get("RONE_KEY", "").strip()
if not KEY:
    print("RONE_KEY 시크릿이 없습니다 — GitHub 저장소 Settings > Secrets and variables > Actions 에 RONE_KEY 등록 필요")
    sys.exit(0)  # 시크릿 등록 전이라도 워크플로 자체는 성공 처리

BASE = "https://www.reb.or.kr/r-one/openapi"
os.makedirs("data/rone", exist_ok=True)

def call(api, **params):
    q = urllib.parse.urlencode({"KEY": KEY, "Type": "json", **params})
    url = f"{BASE}/{api}?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (rtms-rone)"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                body = r.read().decode("utf-8", "replace")
            return json.loads(body), body
        except Exception as e:
            if attempt == 2:
                raise RuntimeError(f"{api} 호출 실패: {e!r} / 원문: {body[:200]!r}" if 'body' in dir() else f"{api} 호출 실패: {e!r}")
            time.sleep(2 * (attempt + 1))

def extract_rows(obj):
    """응답 구조가 어떤 형태든 'row' 키 아래 dict 리스트를 전부 수집"""
    rows = []
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "row" and isinstance(v, list):
                    rows.extend(x for x in v if isinstance(x, dict))
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(obj)
    return rows

def save_csv(path, rows):
    if not rows:
        return 0
    cols = sorted({k for r in rows for k in r})
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])
    return len(rows)

def fetch_all(api, max_pages=6, psize=1000, **params):
    allrows = []
    for p in range(1, max_pages + 1):
        j, raw = call(api, pIndex=p, pSize=psize, **params)
        rows = extract_rows(j)
        if p == 1 and not rows:
            print(f"  [주의] {api} 첫 페이지 row 없음 — 원문 앞 300자: {raw[:300]}")
        if not rows:
            break
        allrows.extend(rows)
        if len(rows) < psize:
            break
        time.sleep(0.3)
    return allrows

def main():
    # ---- 1단계: 통계표 목록 ----
    tables = fetch_all("SttsApiTbl.do")
    n = save_csv("data/rone/tables.csv", tables)
    print(f"통계표 목록: {n}건 → data/rone/tables.csv")
    name_key = None
    if tables:
        for k in tables[0]:
            if "NM" in k.upper() and "STATBL" in k.upper():
                name_key = k
                break
        if not name_key:
            cand = [k for k in tables[0] if "NM" in k.upper()]
            name_key = cand[0] if cand else None
    if not name_key:
        print("[중단] 통계표 이름 컬럼을 찾지 못함 — tables.csv 확인 필요")
        return
    id_key = next((k for k in tables[0] if k.upper() == "STATBL_ID"), None) or \
             next((k for k in tables[0] if "ID" in k.upper()), None)

    # ---- 2단계: 상업용 임대동향 표 자동 선별 ----
    WANT = ["임대료", "공실", "수익률", "전환율", "임대가격지수", "순영업소득"]
    targets = []
    for t in tables:
        nm = str(t.get(name_key, ""))
        if ("상업용" in nm or "상가" in nm or "오피스" in nm) and any(w in nm for w in WANT):
            targets.append((str(t.get(id_key, "")), nm, str(t.get("DTACYCLE_CD", ""))))
    print(f"선별된 상업용 임대동향 통계표: {len(targets)}개")
    for tid, nm, cyc in targets[:60]:
        print(f"  - {tid} [{cyc}] {nm}")

    fetched = 0
    for tid, nm, cyc in targets[:40]:
        if not tid:
            continue
        try:
            params = {"STATBL_ID": tid}
            if cyc:
                params["DTACYCLE_CD"] = cyc
            rows = fetch_all("SttsApiTblData.do", **params)
            c = save_csv(f"data/rone/{tid}.csv", rows)
            print(f"  수집 {tid}: {c}행 — {nm}")
            if c:
                fetched += 1
        except Exception as e:
            print(f"  [오류] {tid}: {e}")
        time.sleep(0.3)
    print(f"완료: 데이터 수집 {fetched}개 표")

if __name__ == "__main__":
    main()
