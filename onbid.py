# -*- coding: utf-8 -*-
"""
onbid.py — 캠코 차세대 온비드 공매 딜 플로우 수집 (apis.data.go.kr/B010003)
확정 명세(내장 swagger에서 추출, 2026-07):
  GET /OnbidRlstListSrvc2/getRlstCltrList2
  필수: serviceKey, pageNo, numOfRows, resultType, prptDivCd(재산구분), pvctTrgtYn(수의계약 대상 여부)
  옵션: lctnSdnm(시도) lctnSggnm(시군구) apslEvlAmtStart/End(감정가) lowstBidPrcStart/End(최저입찰가)
        usbdNftStart/End(유찰횟수) bidPrdYmdStart/End(입찰기간) dspsMthodCd cltrUsg*(용도) 등
산출: data/onbid/rlst_seoul.csv — 서울 공매 부동산 물건 (감정가·최저입찰가·유찰횟수 포함)
"""
import csv, os, re, sys, time
import urllib.request, urllib.parse
import xml.etree.ElementTree as ET

KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()
if not KEY:
    print("DATA_GO_KR_KEY 시크릿 없음")
    sys.exit(0)

BASE = "https://apis.data.go.kr/B010003"
os.makedirs("data/onbid", exist_ok=True)
calls = 0
MAX_CALLS = 700

def call(service, op, **params):
    global calls
    calls += 1
    q = urllib.parse.urlencode({"serviceKey": KEY, **params})
    url = f"{BASE}/{service}/{op}?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (rtms-onbid)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
    except Exception as e:
        return -1, repr(e)

def parse_items(body):
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None, [], ""
    rc = (root.findtext(".//resultCode") or "").strip()
    total_txt = root.findtext(".//totalCount") or "0"
    items = [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
    try:
        total = int(re.sub(r"\D", "", total_txt) or 0)
    except ValueError:
        total = 0
    return total, items, rc

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

def main():
    svc, op = "OnbidRlstListSrvc2", "getRlstCltrList2"
    base = {"numOfRows": 100, "resultType": "xml", "lctnSdnm": "서울특별시"}
    # ---- 재산구분코드 × 수의계약여부 탐색 ----
    working = []
    print("== 재산구분코드 탐색 ==")
    for prpt in ("0001", "0002", "0003", "0004", "0005", "0006", "1", "2", "3", "4"):
        for pvct in ("N", "Y"):
            st, body = call(svc, op, pageNo=1, prptDivCd=prpt, pvctTrgtYn=pvct, **base)
            total, items, rc = parse_items(body)
            if items or (rc in ("00", "0", "000") and total):
                print(f"  prptDivCd={prpt} pvctTrgtYn={pvct}: rc={rc} total={total} → 사용")
                working.append((prpt, pvct, total))
            elif rc not in ("", None):
                m = re.search(r"<resultMsg>([^<]*)</resultMsg>", body)
                print(f"  prptDivCd={prpt} pvctTrgtYn={pvct}: rc={rc} ({m.group(1)[:40] if m else ''})")
            time.sleep(0.15)
    if not working:
        print("[중단] 유효한 재산구분코드 없음 — 응답 원문 확인 필요")
        st, body = call(svc, op, pageNo=1, prptDivCd="0001", pvctTrgtYn="N", **base)
        print("  원문 500자:", re.sub(r"\s+", " ", body[:500]))
        return

    # ---- 수집 ----
    allrows, seen = [], set()
    for prpt, pvct, total in working:
        page = 1
        while calls < MAX_CALLS:
            st, body = call(svc, op, pageNo=page, prptDivCd=prpt, pvctTrgtYn=pvct, **base)
            t, items, rc = parse_items(body)
            if not items:
                break
            for r in items:
                key = r.get("cltrMnmtNo") or r.get("cltrHstrNo") or str(sorted(r.items()))
                if key not in seen:
                    seen.add(key)
                    r["_prptDivCd"] = prpt
                    r["_pvctTrgtYn"] = pvct
                    allrows.append(r)
            if page * 100 >= t:
                break
            page += 1
            time.sleep(0.15)
    n = save_csv("data/onbid/rlst_seoul.csv", allrows)
    print(f"서울 공매 부동산 물건: {n}건 저장 (API 호출 {calls}회)")
    if allrows:
        print("필드:", sorted(allrows[0].keys()))

if __name__ == "__main__":
    main()
