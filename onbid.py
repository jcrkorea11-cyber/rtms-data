# -*- coding: utf-8 -*-
"""
onbid.py — 캠코 차세대 온비드 공매 딜 플로우 수집 (apis.data.go.kr/B010003)
승인 API 5종: 부동산 물건목록(OnbidRlstListSrvc2) / 물건상세(OnbidRlstDtlSrvc2)
             입찰결과목록(OnbidCltrBidRsltListSrvc2) / 입찰결과상세(OnbidCltrBidRsltDtlSrvc2)
             공고목록(OnbidPbancListSrvc2, op: getPbancList2)
목적: 서울 상가·업무·토지 공매 물건을 매일 수집 → 감정가·최저입찰가·유찰현황 → 저평가 스크리닝 재료
로그: data/onbid_log.txt — 1차 실행은 연산명·파라미터 자동 탐색 겸함
"""
import csv, os, re, sys, time
import urllib.request, urllib.parse
import xml.etree.ElementTree as ET

KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()
if not KEY:
    print("DATA_GO_KR_KEY 시크릿 없음")
    sys.exit(0)

BASE = "https://apis.data.go.kr/B010003"
BASE_PARAMS = {}
os.makedirs("data/onbid", exist_ok=True)
calls = 0
MAX_CALLS = 800   # 일일 트래픽 1000/서비스 보호

def call(service, op, **params):
    global calls
    calls += 1
    q = urllib.parse.urlencode({"serviceKey": KEY, "numOfRows": params.pop("numOfRows", 100),
                                "pageNo": params.pop("pageNo", 1), **params})
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
        return None, []
    if root.tag == "OpenAPI_ServiceResponse":
        return None, []
    total = root.findtext(".//totalCount") or root.findtext(".//TotalCount") or "0"
    items = []
    for tag in ("item", "Item", "rlstList", "cltrList"):
        found = list(root.iter(tag))
        if found:
            items = [{c.tag: (c.text or "").strip() for c in it} for it in found]
            break
    try:
        total = int(re.sub(r"\D", "", total) or 0)
    except ValueError:
        total = 0
    return total, items

def discover(service, candidates):
    """연산명 후보를 시도해 작동하는 것을 찾는다"""
    for op in candidates:
        st, body = call(service, op, numOfRows=3)
        head = re.sub(r"\s+", " ", body[:500])
        total, items = parse_items(body)
        print(f"  [{service}/{op}] status={st} total={total} items={len(items)} 앞200자={head!r}")
        if items or (total and total > 0):
            return op, items
    return None, []

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


def param_discover(service, op):
    """필수 파라미터 조합 탐색 — resultCode 00/데이터 반환 조합을 찾는다"""
    combos = [
        {"DPSL_MTD_CD": "0001"},
        {"DPSL_MTD_CD": "0001", "CTGR_HIRK_ID": "10000"},
        {"CTGR_HIRK_ID": "10000"},
        {"SIDO": "서울특별시"},
        {"DPSL_MTD_CD": "0001", "SIDO": "서울특별시"},
        {"PBCT_BEGN_DTM": "202607010000", "PBCT_CLS_DTM": "202608312359"},
        {"DPSL_MTD_CD": "0001", "PBCT_BEGN_DTM": "202607010000", "PBCT_CLS_DTM": "202608312359"},
        {"BID_BEGN_YMD": "20260701", "BID_CLS_YMD": "20260831"},
        {"PBNC_BGNG_YMD": "20260701", "PBNC_END_YMD": "20260831"},
        {"RQST_BGNG_YMD": "20260701", "RQST_END_YMD": "20260831"},
    ]
    for c in combos:
        st, body = call(service, op, numOfRows=3, **c)
        total, items = parse_items(body)
        rc = ""
        m = re.search(r"<resultCode>([^<]*)</resultCode>", body)
        if m: rc = m.group(1)
        print(f"  [파라미터 {c}] status={st} rc={rc} total={total} items={len(items)}")
        if items:
            return c, items
    return None, []

def main():
    # ---- 1) 연산명 탐색 (공고목록은 op 확정: getPbancList2) ----
    print("== 연산명 탐색 ==")
    op_rlst, sample = discover("OnbidRlstListSrvc2",
        ["getRlstList2", "getOnbidRlstList2", "getRlstList", "getOnbidRlstList",
         "getRlstCltrList2", "getOnbidRlstCltrList2", "getRealEstateList2",
         "getRlstBasisList2", "getOnbidRlstListInfo2", "getRlstListInfo2"])
    op_pbanc, _ = discover("OnbidPbancListSrvc2", ["getPbancList2"])
    op_bid, _ = discover("OnbidCltrBidRsltListSrvc2",
        ["getCltrBidRsltList2", "getOnbidCltrBidRsltList2", "getCltrBidRsltList"])
    if sample:
        print("  물건목록 필드:", sorted(sample[0].keys()))

    if not op_rlst:
        # 연산명은 응답했지만 필수 파라미터 미충족(rc=11)인 경우 → getRlstCltrList2로 파라미터 탐색
        op_rlst = "getRlstCltrList2"
        print("== 필수 파라미터 탐색 (getRlstCltrList2) ==")
        pc, sample = param_discover("OnbidRlstListSrvc2", op_rlst)
        if not pc:
            print("[중단] 필수 파라미터 조합을 찾지 못함 — 활용가이드 docx 필요 (사용자에게 미리보기 화면 요청)")
            return
        global BASE_PARAMS
        BASE_PARAMS = pc
        print(f"  확정 파라미터: {pc}")

    # ---- 2) 부동산 물건목록 수집 (전체 페이지 → 서울만 저장) ----
    print("== 물건목록 수집 ==")
    allrows, page = [], 1
    while calls < MAX_CALLS:
        st, body = call("OnbidRlstListSrvc2", op_rlst, numOfRows=100, pageNo=page, **BASE_PARAMS)
        total, items = parse_items(body)
        if not items:
            break
        allrows.extend(items)
        if page == 1:
            print(f"  전체 물건 수(신고): {total}")
        if page * 100 >= total or page >= 60:
            break
        page += 1
        time.sleep(0.2)
    # 서울 필터 (주소 필드 자동 탐지)
    addr_keys = [k for k in (allrows[0].keys() if allrows else []) if any(x in k.upper() for x in ("ADRES", "ADDR", "LDNM", "NMRD"))]
    seoul = []
    for r in allrows:
        blob = " ".join(str(r.get(k, "")) for k in addr_keys) if addr_keys else " ".join(map(str, r.values()))
        if "서울" in blob:
            seoul.append(r)
    n1 = save_csv("data/onbid/rlst_all.csv", allrows)
    n2 = save_csv("data/onbid/rlst_seoul.csv", seoul)
    print(f"물건목록: 전체 {n1}건 저장 / 서울 {n2}건 (주소필드 추정: {addr_keys})")
    print(f"API 호출 {calls}회")

if __name__ == "__main__":
    main()
