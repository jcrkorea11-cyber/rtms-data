# -*- coding: utf-8 -*-
"""정찰: ① 서울 건축물대장 서비스명 ② 온비드 활용가이드 docx 파라미터 추출"""
import io, os, re, zipfile
import urllib.request, urllib.parse

os.makedirs("data/debug", exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"}

def get(url, binary=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        b = r.read()
    return b if binary else b.decode("utf-8", "replace")

# ---------- ① 서울 건축물대장 (OA-15389) ----------
print("== 서울 OA-15389 정찰 ==")
try:
    html = get("https://data.seoul.go.kr/dataList/OA-15389/S/1/datasetView.do")
    open("data/debug/oa15389.html", "w", encoding="utf-8").write(html[:300000])
    print(f"  페이지 저장 ({len(html)}자)")
    for pat in (r"openapi\.seoul\.go\.kr[^\"'<> ]*", r'infId["\']?\s*[:=]\s*["\']OA-\d+', r"srvNm[^,}]{0,60}", r"tbLn[A-Za-z0-9_]+", r'"serviceNm"[^,}]{0,60}'):
        m = sorted(set(re.findall(pat, html)))[:8]
        if m:
            print(f"  패턴 {pat[:20]}: {m}")
except Exception as e:
    print(f"  실패: {e!r}")
# 데이터셋 AJAX 후보들
for u in ("https://data.seoul.go.kr/dataList/selectDataSetView.do?infId=OA-15389&srvType=S",
          "https://data.seoul.go.kr/dataService/selectInfoView.do?infId=OA-15389",
          "https://data.seoul.go.kr/dataList/openApiView.do?infId=OA-15389&srvType=S"):
    try:
        b = get(u)
        m = sorted(set(re.findall(r"[A-Za-z][A-Za-z0-9_]{6,40}", b)))
        svc = [x for x in m if re.match(r"(tbLn|Open|Bld|bld).*", x)][:10]
        print(f"  [AJAX] {u.split('/')[-1][:40]} len={len(b)} 서비스명 후보={svc}")
        if len(b) < 200000 and ("서비스명" in b or "OA-15389" in b):
            open(f"data/debug/ajax_{u.split('/')[-1].split('?')[0]}.txt", "w", encoding="utf-8").write(b[:100000])
    except Exception as e:
        print(f"  [AJAX] {u[:60]} 예외: {e!r}")

# ---------- ② 온비드 활용가이드 docx ----------
print("== 온비드 가이드 정찰 ==")
try:
    # data.go.kr 검색 (서버 렌더링)
    su = "https://www.data.go.kr/tcs/dss/selectDataSetList.do?dType=API&keyword=" + urllib.parse.quote("온비드 부동산 물건목록")
    html = get(su)
    ids = sorted(set(re.findall(r"/data/(\d{8})/openapi\.do", html)))
    print(f"  검색결과 데이터셋 ID: {ids[:6]}")
    for did in ids[:3]:
        page = get(f"https://www.data.go.kr/data/{did}/openapi.do")
        title = re.search(r"<title>([^<]*)</title>", page)
        print(f"  [{did}] {title.group(1).strip() if title else '?'}")
        # 참고문서 다운로드 링크
        files = sorted(set(re.findall(r"(/cmm/cmm/fileDownload\.do[^\"'<> ]*)", page)))
        fids = sorted(set(re.findall(r"atchFileId=([A-Za-z0-9_]+)", page)))
        print(f"    파일링크 {len(files)}개, atchFileId {fids[:3]}")
        if "물건목록" in page and files:
            for f in files[:2]:
                url = "https://www.data.go.kr" + f.replace("&amp;", "&")
                try:
                    blob = get(url, binary=True)
                    print(f"    다운로드 {len(blob)}바이트: {url[:100]}")
                    if blob[:2] == b"PK":  # docx(zip)
                        z = zipfile.ZipFile(io.BytesIO(blob))
                        xml = z.read("word/document.xml").decode("utf-8", "replace")
                        text = re.sub(r"<[^>]+>", "\n", xml)
                        text = re.sub(r"\n{2,}", "\n", text)
                        open("data/debug/onbid_guide.txt", "w", encoding="utf-8").write(text[:120000])
                        # 파라미터명 추출 (영대문자+언더스코어)
                        params = sorted(set(re.findall(r"\b[A-Z][A-Z_]{3,25}\b", text)))
                        print(f"    docx 텍스트 추출 → data/debug/onbid_guide.txt / 파라미터 후보: {params[:40]}")
                        break
                except Exception as e:
                    print(f"    다운로드 실패: {e!r}")
except Exception as e:
    print(f"  실패: {e!r}")
print("정찰 완료")
