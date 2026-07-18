#!/usr/bin/env python3
"""서울 실거래 통합 수집기 v4 — GitHub Actions 실행
A. 서울열린데이터: 주택(단독다가구) 실거래 (SEOUL_API_KEY)
B. 국토부: 상업업무용(상가·빌딩) 실거래 (DATA_GO_KR_KEY) — XML, 태그 자동 수집
해제(취소)거래 제외, 100억 필터는 주택만(상가는 원본 보존, 분석 단계 필터)
"""
import csv, json, os, sys, urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

SEOUL_KEY = os.environ.get("SEOUL_API_KEY", "").strip()
MOLIT_KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()

GUS = {
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
MAX_PRICE = 1_000_000
BATCH = 1000
OUT = Path("data"); OUT.mkdir(exist_ok=True)

def http(url):
    with urllib.request.urlopen(url, timeout=90) as r:
        return r.read().decode("utf-8")

# ---------- A. 서울시 주택(단독다가구) ----------
def seoul_rows(year, gu):
    rows, start = [], 1
    while True:
        url = f"http://openapi.seoul.go.kr:8088/{SEOUL_KEY}/json/tbLnOpendataRtmsV/{start}/{start+BATCH-1}/{year}/{gu}"
        data = json.loads(http(url))
        body = data.get("tbLnOpendataRtmsV")
        if not body:
            print(f"  [주택 {year}/{gu}] 오류: {data.get('RESULT', {})}", file=sys.stderr)
            break
        rows += body.get("row", [])
        if start + BATCH > body.get("list_total_count", 0):
            break
        start += BATCH
    return rows

def keep_house(r):
    use = (r.get("BLDG_USG") or "").strip()
    if any(x in use for x in EXCLUDE_USE):
        return False
    if str(r.get("RTRCN_DAY") or "").strip():   # 해제거래 제외
        return False
    try:
        price = int(str(r.get("THING_AMT", "0")).replace(",", ""))
    except ValueError:
        return False
    return 0 < price <= MAX_PRICE

H_FIELDS = ["RCPT_YR","CGG_NM","STDG_NM","STDG_CD","LOTNO_SE_NM","MNO","SNO","BLDG_USG",
            "LAND_AREA","ARCH_AREA","THING_AMT","CTRT_DAY","ARCH_YR","RGHT_SE","RTRCN_DAY",
            "DCLR_SE","OPBIZ_RESTAGNT_SGG_NM"]

def run_housing():
    if not SEOUL_KEY:
        print("SEOUL_API_KEY 없음 — 주택 수집 건너뜀"); return {}
    summary = {}
    for gu, name in GUS.items():
        rows = []
        for y in YEARS:
            got = seoul_rows(y, gu)
            kept = [r for r in got if keep_house(r)]
            rows += kept
            print(f"[주택 {name} {y}] {len(got)} → {len(kept)}")
        with open(OUT / f"rtms_{gu}_{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=H_FIELDS, extrasaction="ignore")
            w.writeheader()
            for r in sorted(rows, key=lambda x: str(x.get("CTRT_DAY", ""))):
                w.writerow(r)
        summary[name] = len(rows)
    return summary

# ---------- B. 국토부 상업업무용(상가·빌딩) ----------
def months():
    out, y, m = [], 2025, 1
    today = date.today()
    while (y, m) <= (today.year, today.month):
        out.append(f"{y}{m:02d}")
        m += 1
        if m > 12: y, m = y + 1, 1
    return out

def molit_items(lawd, ymd):
    url = (f"https://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade"
           f"?serviceKey={MOLIT_KEY}&LAWD_CD={lawd}&DEAL_YMD={ymd}&numOfRows={BATCH}&pageNo=1")
    try:
        root = ET.fromstring(http(url))
    except Exception as e:
        print(f"  [상가 {lawd}/{ymd}] 요청 실패: {e}", file=sys.stderr)
        return None
    code = (root.findtext(".//resultCode") or "").strip()
    if code not in ("00", "000", ""):
        msg = (root.findtext(".//resultMsg") or "").strip()
        print(f"  [상가 {lawd}/{ymd}] 응답 코드 {code}: {msg}", file=sys.stderr)
        return None
    return [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]

def run_commercial():
    if not MOLIT_KEY:
        print("DATA_GO_KR_KEY 없음 — 상가 수집 건너뜀"); return {}
    summary = {}
    for gu, name in GUS.items():
        rows, fail = [], 0
        for ymd in months():
            items = molit_items(gu, ymd)
            if items is None:
                fail += 1
                continue
            rows += items
        def cancelled(r):
            for k in ("cdealDay", "cdealType", "해제사유발생일", "해제여부"):
                v = str(r.get(k, "")).strip()
                if v and v not in ("O부재", "-"):
                    return True
            return False
        rows = [r for r in rows if not cancelled(r)]
        headers = sorted({k for r in rows for k in r})
        with open(OUT / f"nrg_{gu}_{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)
        summary[name] = len(rows)
        print(f"[상가 {name}] {len(rows)}건 (실패 월 {fail})")
    return summary

if __name__ == "__main__":
    s1 = run_housing()
    s2 = run_commercial()
    Path("data/summary.json").write_text(
        json.dumps({"housing": s1, "commercial": s2}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print("완료 — 주택:", sum(s1.values()) if s1 else 0, "/ 상가:", sum(s2.values()) if s2 else 0)
