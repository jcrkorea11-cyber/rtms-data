# -*- coding: utf-8 -*-
"""정찰 2차: ① 서울 건축물대장 데이터셋 현재 위치·서비스명 ② 온비드 15157207 페이지 원본 저장"""
import os, re
import urllib.request, urllib.parse

os.makedirs("data/debug", exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"}

def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")

# ---------- ① 서울 데이터셋 검색 ----------
print("== 서울 검색 ==")
for kw in ("건축물대장 표제부", "건축물대장"):
    try:
        u = "https://data.seoul.go.kr/dataList/datasetList.do?datasetKind=1&searchFlag=M&searchWord=" + urllib.parse.quote(kw)
        html = get(u)
        open(f"data/debug/seoul_search_{kw[:5]}.html", "w", encoding="utf-8").write(html[:400000])
        links = re.findall(r'href="(/dataList/[^"]*OA-\d+[^"]*)"[^>]*>([^<]{2,60})', html)
        ids = sorted(set(re.findall(r"OA-\d+", html)))
        print(f"  [{kw}] len={len(html)} OA목록={ids[:15]}")
        for l, t in links[:10]:
            print(f"    {l} | {t.strip()}")
        if ids:
            break
    except Exception as e:
        print(f"  [{kw}] 예외: {e!r}")

# 발견된 첫 데이터셋 페이지 저장 + 서비스명 추출
try:
    if ids:
        for oa in ids[:4]:
            for tp in ("A", "S"):
                try:
                    page = get(f"https://data.seoul.go.kr/dataList/{oa}/{tp}/1/datasetView.do")
                    if oa in page or "표제부" in page or "건축물" in page:
                        open(f"data/debug/seoul_{oa}_{tp}.html", "w", encoding="utf-8").write(page[:400000])
                        svc = sorted(set(re.findall(r"[a-zA-Z]+/(?:json|xml|xls)/([A-Za-z0-9_]{5,40})/", page)
                                        + re.findall(r'infSeq[^A-Za-z]{0,5}([A-Za-z0-9_]{5,40})', page)))
                        title = re.search(r"<title>([^<]*)</title>", page)
                        print(f"  [{oa}/{tp}] 제목={title.group(1)[:40] if title else '?'} 서비스명후보={svc[:6]}")
                except Exception:
                    pass
except Exception as e:
    print(f"  상세 예외: {e!r}")

# ---------- ② 온비드 15157207 페이지 원본 ----------
print("== 온비드 15157207 ==")
try:
    page = get("https://www.data.go.kr/data/15157207/openapi.do")
    open("data/debug/onbid_15157207.html", "w", encoding="utf-8").write(page[:500000])
    print(f"  저장 len={len(page)}")
    # 문서/스웨거 흔적
    for pat in (r'atchFileId[^"\']{0,40}', r'fileDetailSn[^"\']{0,20}', r'/tcs/dss/[^"\']{5,80}', r'swagger[^"\']{0,60}', r'getRlst[A-Za-z0-9]*', r'"prmisnNm"[^,]{0,50}'):
        m = sorted(set(re.findall(pat, page)))[:8]
        if m:
            print(f"  패턴 {pat[:18]}: {m}")
except Exception as e:
    print(f"  예외: {e!r}")
print("정찰2 완료")
