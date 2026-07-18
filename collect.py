#!/usr/bin/env python3
"""서울시 부동산 실거래가(tbLnOpendataRtmsV) 일일 수집기 — GitHub Actions에서 실행.
빌딩류(아파트·오피스텔·연립다세대 제외) & 100억 이하만 걸러 구별 CSV로 누적 저장.
환경변수 SEOUL_API_KEY 필요 (GitHub Secret).
"""
import csv, json, os, sys, urllib.request
from pathlib import Path

KEY = os.environ.get("SEOUL_API_KEY", "").strip()
if not KEY:
    sys.exit("SEOUL_API_KEY 시크릿이 없습니다")

GUS = {  # 서울 25개 자치구 전체
    "11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구",
    "11215": "광진구", "11230": "동대문구", "11260": "중랑구", "11290": "성북구",
    "11305": "강북구", "11320": "도봉구", "11350": "노원구", "11380": "은평구",
    "11410": "서대문구", "11440": "마포구", "11470": "양천구", "11500": "강서구",
    "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구",
    "11740": "강동구",
}
YEARS = ["2025", "2026"]
EXCLUDE_USE = ("아파트", "오피스텔", "연립다세대", "연립", "다세대")
MAX_PRICE = 1_000_000  # 만원 = 100억
BATCH = 1000

def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

def get_rows(year, gu):
    rows, start = [], 1
    while True:
        url = f"http://openapi.seoul.go.kr:8088/{KEY}/json/tbLnOpendataRtmsV/{start}/{start+BATCH-1}/{year}/{gu}"
        data = fetch(url)
        body = data.get("tbLnOpendataRtmsV")
        if not body:  # 오류 응답
            res = data.get("RESULT", {})
            print(f"  [{year}/{gu}] 응답 오류: {res}", file=sys.stderr)
            break
        rows += body.get("row", [])
        total = body.get("list_total_count", 0)
        if start + BATCH > total:
            break
        start += BATCH
    return rows

def keep(r):
    use = (r.get("BLDG_USG") or "").strip()
    if any(x in use for x in EXCLUDE_USE):
        return False
    try:
        price = int(str(r.get("THING_AMT", "0")).replace(",", ""))
    except ValueError:
        return False
    return 0 < price <= MAX_PRICE

FIELDS = ["RCPT_YR","CGG_NM","STDG_NM","LOTNO_SE_NM","MNO","SNO","BLDG_USG",
          "LAND_AREA","ARCH_AREA","THING_AMT","CTRT_DAY","ARCH_YR","DCLR_SE","OPBIZ_RESTAGNT_SGG_NM"]

def main():
    out_dir = Path("data"); out_dir.mkdir(exist_ok=True)
    summary = {}
    for gu, name in GUS.items():
        all_rows = []
        for y in YEARS:
            got = get_rows(y, gu)
            kept = [r for r in got if keep(r)]
            all_rows += kept
            print(f"[{name} {y}] 수신 {len(got)} → 필터 후 {len(kept)}")
        # 전량 재작성(원천이 진실) — 시계열 비교는 git 히스토리가 보존
        path = out_dir / f"rtms_{gu}_{name}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            for r in sorted(all_rows, key=lambda x: str(x.get("CTRT_DAY",""))):
                w.writerow(r)
        summary[name] = len(all_rows)
    Path("data/summary.json").write_text(
        json.dumps({"counts": summary}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("완료:", summary)

if __name__ == "__main__":
    main()
