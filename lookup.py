#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""회사명 + 홈페이지 주소 → 사업자등록번호 + 부가정보 조회 (핵심 로직)

조회 전략(우선순위)
  1) 홈페이지 푸터/하위페이지에서 사업자번호 직접 추출          → 출처 '홈페이지', 신뢰도 '높음'
  2) bizno.net 회사명 검색
       - 정규화 상호가 '유일하게 정확일치'하면 채택             → 출처 '유일일치', 신뢰도 '중간'
       - 동명 후보가 여럿이면, 각 후보 페이지에 입력 홈페이지
         도메인이 있는지로 식별                                → 출처 '도메인일치', 신뢰도 '높음'
       - 끝까지 못 좁히면 최상위 후보를 참고용으로 반환          → 출처 '확인필요', 신뢰도 '낮음'
  3) 사업자번호를 찾으면 bizno 직접조회로 대표자·주소·업태·
     종목·규모·이메일·전화 등 부가정보 취득(번호=article id라 정확)

SWGO 같은 별도 소스 없이 입력 2칼럼(회사명·홈페이지)만으로 동작한다.
"""
import re
import time
import urllib.parse
import requests
from bs4 import BeautifulSoup

HDR = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    # 한국어 페이지를 받기 위해(루트→영문 자동전환 사이트 대응). 사업자번호는 한글 페이지에만 있는 경우가 많음.
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
}

BIZNO_BASE = "https://bizno.net"


def _get(url, timeout=15):
    return requests.get(url, headers=HDR, timeout=timeout)


# ---------- 상호 정규화 ----------
def name_norm(s):
    s = s or ""
    s = re.sub(r"\(.*?\)|（.*?）", "", s)
    for w in ["주식회사", "(주)", "㈜", "(유)", "유한회사", "유한책임회사",
              "(재)", "(사)", "주식 회사"]:
        s = s.replace(w, "")
    return re.sub(r"\s+", "", s).lower()


def domain_of(url):
    """홈페이지 URL → 비교용 도메인(www. 제거, 호스트만)."""
    if not url:
        return ""
    u = url.strip()
    if not u.startswith("http"):
        u = "http://" + u
    try:
        host = urllib.parse.urlparse(u).netloc.lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


# ---------- 1) 홈페이지에서 사업자번호 직접 추출 ----------
BIZ_NEAR = re.compile(r"사업자[^\d]{0,25}(\d{3}\s*[-‐]\s*\d{2}\s*[-‐]\s*\d{5})")
BIZ_ANY = re.compile(r"\d{3}-\d{2}-\d{5}")

SUBPAGE_HINTS = ["회사소개", "회사정보", "company", "about", "이용약관", "약관",
                 "terms", "개인정보", "privacy", "agreement", "provision",
                 "contact", "오시는길", "footer"]


def _extract_bizno_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    m = BIZ_NEAR.search(text)
    if m:
        return re.sub(r"\s", "", m.group(1)).replace("‐", "-")
    nums = set(BIZ_ANY.findall(text))
    if "사업자" in text and len(nums) == 1:
        return next(iter(nums))
    return ""


def _find_subpages(base_url, html, limit=3):
    soup = BeautifulSoup(html, "html.parser")
    cands = []
    for a in soup.find_all("a", href=True):
        href, txt = a["href"], a.get_text(" ", strip=True).lower()
        if any(h in txt or h in href.lower() for h in SUBPAGE_HINTS):
            full = urllib.parse.urljoin(base_url, href)
            if full.startswith("http") and full not in cands:
                cands.append(full)
        if len(cands) >= limit:
            break
    return cands


# 홈페이지 이메일 추출 — bizno에 이메일이 없는 회사를 홈페이지로 보완
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# 회사 이메일이 아닌 흔한 잡음(예시·라이브러리·이미지·placeholder 등) 제외
EMAIL_JUNK = ("example.", "sentry", "wix.com", "wixpress", "godaddy",
              "yourdomain", "domain.com", "email.com", "schema.org", "w3.org",
              "googleapis", "cloudflare", "@2x", ".png", ".jpg", ".jpeg", ".gif",
              ".svg", "your@", "name@", "test@", "abc@", "user@", "info@example",
              "sentry.io", "@sentry", "react", "webpack")


def _extract_emails(html):
    """HTML에서 이메일 후보 추출(mailto 우선). 잡음 제거 후 중복 없는 리스트."""
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for a in soup.find_all("a", href=True):
        if a["href"].lower().startswith("mailto:"):
            addr = a["href"][7:].split("?")[0].strip()
            if addr:
                found.append(addr)
    for tag in soup(["script", "style"]):
        tag.decompose()
    found += EMAIL_RE.findall(soup.get_text(" ", strip=True))
    out = []
    for e in found:
        el = e.lower().strip().strip(".")
        if any(j in el for j in EMAIL_JUNK) or el in out:
            continue
        out.append(el)
    return out


def _pick_email(emails, homepage):
    """후보 중 회사 대표 이메일로 가장 그럴듯한 것 선택."""
    if not emails:
        return ""
    dom = domain_of(homepage)
    for e in emails:                      # 1) 홈페이지 도메인과 같은 메일 우선
        if dom and e.endswith("@" + dom):
            return e
    for e in emails:                      # 2) 흔한 한국 메일 서비스
        if any(p in e for p in ["naver.com", "gmail.com", "daum.net",
                                "kakao.com", "hanmail.net", "nate.com"]):
            return e
    return emails[0]


def scan_homepage(homepage):
    """홈페이지(+하위 페이지)를 1회 크롤해 사업자번호와 이메일을 함께 추출.
    반환 {'bizno': '', 'email': ''}. (사업자번호 찾으러 어차피 방문하므로 이메일도 같이)"""
    res = {"bizno": "", "email": ""}
    if not homepage or not homepage.strip():
        return res
    try:
        r = _get(homepage, timeout=12)
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception:
        return res
    res["bizno"] = _extract_bizno_from_html(r.text)
    emails = _extract_emails(r.text)
    if res["bizno"] and emails:           # 둘 다 루트에서 확보되면 종료
        res["email"] = _pick_email(emails, homepage)
        return res
    for sub in _find_subpages(r.url, r.text):   # 부족한 것만 하위 페이지에서 보완
        if res["bizno"] and emails:
            break
        try:
            r2 = _get(sub, timeout=10)
            r2.encoding = r2.apparent_encoding or "utf-8"
        except Exception:
            continue
        if not res["bizno"]:
            res["bizno"] = _extract_bizno_from_html(r2.text)
        if not emails:
            emails = _extract_emails(r2.text)
        time.sleep(0.15)
    res["email"] = _pick_email(emails, homepage)
    return res


# ---------- 2) bizno 회사명 검색 + 식별 ----------
def _search_candidates(name):
    """bizno 회사명 검색 → [(사업자번호10자리, 표시상호, 정확일치여부)] (중복 제거)."""
    try:
        r = requests.get(BIZNO_BASE + "/", params={"query": name},
                         headers=HDR, timeout=15)
        r.encoding = "utf-8"
    except Exception:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    tgt = name_norm(name)
    out, seen = [], set()
    if len(tgt) < 2:
        return []
    for a in soup.select('a[href^="/article/"]'):
        aid = a["href"].rstrip("/").split("/")[-1]
        if not re.fullmatch(r"\d{10}", aid) or aid in seen:
            continue
        seen.add(aid)
        txt = a.get_text(" ", strip=True)
        out.append((aid, txt, name_norm(txt) == tgt))
    return out


def _article_has_domain(aid, target_domain):
    if not target_domain:
        return False
    try:
        r = _get(BIZNO_BASE + "/article/" + aid, timeout=12)
        r.encoding = "utf-8"
    except Exception:
        return False
    return target_domain in r.text.lower()


def find_bizno_by_search(name, homepage, max_domain_checks=4):
    """회사명 검색으로 사업자번호 식별. 반환 (사업자번호'하이픈', 출처, 신뢰도)."""
    cands = _search_candidates(name)
    if not cands:
        return "", "", ""
    exact = [c for c in cands if c[2]]
    dom = domain_of(homepage)

    # (a) 동명업체 없이 유일하게 정확일치
    if len(exact) == 1:
        return _hyphen(exact[0][0]), "유일일치", "중간"

    # (b) 후보가 여럿 → 입력 홈페이지 도메인이 박힌 후보 채택
    pool = exact if exact else cands
    for aid, _txt, _ex in pool[:max_domain_checks]:
        if _article_has_domain(aid, dom):
            return _hyphen(aid), "도메인일치", "높음"
        time.sleep(0.2)

    # (c) 못 좁힘 → 최상위 정확일치 후보를 참고용으로(낮은 신뢰도)
    if exact:
        return _hyphen(exact[0][0]), f"확인필요(후보{len(exact)})", "낮음"
    return "", f"확인필요(후보{len(cands)})", ""


def _hyphen(aid):
    return f"{aid[:3]}-{aid[3:5]}-{aid[5:]}"


# ---------- 3) bizno 직접조회(부가정보) ----------
def _clean(v):
    """전화/이메일 끝의 안내문구('※휴대폰번호는…', '(...')를 잘라낸다."""
    if not v:
        return ""
    return re.split(r"[(※]", v)[0].strip()


def bizno_detail(bizno_hyphen):
    aid = bizno_hyphen.replace("-", "")
    rec = {"대표자명": "", "회사주소": "", "업태": "", "종목": "",
           "기업규모": "", "법인등록번호": "", "회사이메일": "", "전화번호": ""}
    try:
        r = _get(BIZNO_BASE + "/article/" + aid, timeout=15)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        info = {}
        for tr in soup.select("table tr"):
            cs = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
            cs = [x for x in cs if x]
            if len(cs) >= 2:
                info[cs[0].replace(" ", "")] = cs[1]
        for k in rec:
            rec[k] = info.get(k, "")
        rec["회사이메일"] = _clean(rec["회사이메일"])
        rec["전화번호"] = _clean(rec["전화번호"])
    except Exception as e:
        rec["error"] = str(e)
    return rec


# ---------- 통합: 한 회사 조회 ----------
RESULT_FIELDS = ["사업자등록번호", "조회출처", "신뢰도", "대표자명", "회사주소",
                 "업태", "종목", "기업규모", "회사이메일", "이메일출처",
                 "전화번호", "법인등록번호"]


def lookup_one(name, homepage):
    """회사명 + 홈페이지 → 결과 dict(RESULT_FIELDS). 못 찾으면 사업자번호 ''."""
    out = {k: "" for k in RESULT_FIELDS}
    name = (name or "").strip()
    homepage = (homepage or "").strip()
    if not name:
        out["조회출처"] = "회사명없음"
        return out

    # 홈페이지 1회 크롤로 사업자번호 + 이메일을 함께 확보
    scan = scan_homepage(homepage) if homepage else {"bizno": "", "email": ""}
    biz = scan["bizno"]
    if biz:
        out["조회출처"], out["신뢰도"] = "홈페이지", "높음"
    else:
        biz, src, conf = find_bizno_by_search(name, homepage)
        out["조회출처"], out["신뢰도"] = src, conf

    if biz:
        out["사업자등록번호"] = biz
        # '확인필요(낮음)'이어도 부가정보는 같은 번호로 채워 참고용 제공
        det = bizno_detail(biz)
        for k in ["대표자명", "회사주소", "업태", "종목", "기업규모",
                  "회사이메일", "전화번호", "법인등록번호"]:
            out[k] = det.get(k, "")
    elif not out["조회출처"]:
        out["조회출처"] = "미발견"

    # 이메일 보완: bizno에 있으면 그 값(출처 bizno), 없으면 홈페이지 추출값
    if out["회사이메일"]:
        out["이메일출처"] = "bizno"
    elif scan["email"]:
        out["회사이메일"] = scan["email"]
        out["이메일출처"] = "홈페이지"
    return out


if __name__ == "__main__":
    # 간단 점검
    import sys, json
    nm = sys.argv[1] if len(sys.argv) > 1 else "쉐코"
    hp = sys.argv[2] if len(sys.argv) > 2 else ""
    print(json.dumps(lookup_one(nm, hp), ensure_ascii=False, indent=2))
