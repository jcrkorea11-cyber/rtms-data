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
START = time.time()
DEADLINE = 900  # 전체 10분 제한 — 초과 시 수집분만 저장하고 종료
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
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read().decode("utf-8", "replace")
            return json.loads(body), body
        except Exception as e:
            if attempt == 1:
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
    if time.time() - START > DEADLINE:
        raise RuntimeError("전체 시간제한 초과")
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


# 확정 수집 대상 (2026-07-19 통계표 목록에서 확인한 최신 표 ID)
TARGETS = {
  # 수익률 (소득·자본·투자수익률 — 실측 캡레이트 근거)
  "T245883135037859": "수익률_오피스", "T242083134887473": "수익률_중대형상가",
  "T246253134913401": "수익률_소규모상가", "T246393134978815": "수익률_집합상가",
  # 순영업소득 (NOI ㎡당)
  "TT242303134253883": "순영업소득_오피스", "T248383134665433": "순영업소득_중대형상가",
  "T248663134928155": "순영업소득_소규모상가", "T243693134953154": "순영업소득_집합상가",
  # 지역별 임대료 (㎡당)
  "TT249843134237374": "임대료_오피스", "T244363134858603": "임대료_중대형상가",
  "T248223134698125": "임대료_소규모상가", "T244913134948657": "임대료_집합상가",
  # 층별임대료·층별효용비율
  "T241873134863890": "층별임대료_중대형상가", "T246233134891629": "층별임대료_소규모상가",
  "T249023134703697": "층별임대료_집합상가",
  # 지역별 공실률
  "TT244763134428698": "공실률_오피스", "T249633134845544": "공실률_중대형상가",
  "T241833134686576": "공실률_소규모상가", "T243283134931290": "공실률_집합상가",
  "T262303140824764": "공실률_일반상가", "T268603140832693": "공실률_일반상가1층",
  # 전환율
  "T241883134877452": "전환율_중대형상가", "T246253134905233": "전환율_소규모상가",
  # 임대가격지수 시계열 (모멘텀)
  "TT248473134635539": "임대가격지수_중대형상가", "TT246323134644307": "임대가격지수_소규모상가",
  "TT247193134654396": "임대가격지수_집합상가", "TT249683134828248": "임대가격지수_통합상가",
}

def main():
    if not os.path.exists("data/rone/tables.csv"):
        tables = fetch_all("SttsApiTbl.do")
        print(f"통계표 목록: {save_csv('data/rone/tables.csv', tables)}건")
    ok, fail = 0, 0
    # 미수집 표 우선, 이후 기존 표 갱신 (시간제한 대비)
    order = sorted(TARGETS.items(), key=lambda kv: os.path.exists(f"data/rone/{kv[0]}.csv"))
    for tid, label in order:
        try:
            rows = []
            for cyc in ("QY", "YY", "MM"):
                rows = fetch_all("SttsApiTblData.do", max_pages=15, STATBL_ID=tid, DTACYCLE_CD=cyc)
                if rows:
                    break
            c = save_csv(f"data/rone/{tid}.csv", rows)
            print(f"  수집 {label} ({tid}): {c}행")
            ok += 1 if c else 0
            fail += 0 if c else 1
        except Exception as e:
            fail += 1
            print(f"  [오류] {label} ({tid}): {e}")
        time.sleep(0.4)
    print(f"완료: 성공 {ok} / 실패·빈값 {fail} (총 {len(TARGETS)}개 표)")

if __name__ == "__main__":
    main()
