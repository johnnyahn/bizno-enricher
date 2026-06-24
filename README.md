# 사업자정보 일괄조회 (bizno_enricher)

회사명과 (있으면) 홈페이지 주소 목록을 넣으면 **사업자등록번호 + 부가정보**
(대표자·회사주소·업태·종목·기업규모·이메일·전화)를 일괄 조회하는 Streamlit 웹앱.

별도 데이터 소스 없이 **회사명·홈페이지 2개 칼럼만**으로 동작한다.

## 조회 방식
1. 홈페이지가 있으면 그 사이트(푸터·회사소개·약관)에서 사업자번호 직접 추출 — *신뢰도 높음*
2. 못 찾으면 bizno.net 회사명 검색
   - 같은 이름 회사가 하나뿐 → 채택 *(중간)*
   - 여럿이면 입력 홈페이지 도메인이 일치하는 회사 선택 *(높음)*
   - 못 좁히면 후보를 참고용으로 표시 *(낮음/확인필요)*
3. 사업자번호로 bizno 직접조회 → 부가정보 취득

> 신뢰도 `높음`은 신뢰, `중간`은 동명업체가 있으면 다를 수 있어 확인 권장,
> `낮음/확인필요`는 반드시 검증.

## 로컬 실행
```bash
pip install -r requirements.txt
streamlit run app.py
```

## 배포 (Streamlit Community Cloud, 개인 계정)
1. 개인 GitHub(johnnyahn)에 이 폴더를 repo로 올린다.
2. https://share.streamlit.io → New app → repo 선택, main file `app.py`.
3. 자동 배포. `requirements.txt`로 의존성 설치됨.

## 파일
- `app.py` — Streamlit UI (붙여넣기 / 파일 업로드 → 결과 표·엑셀 다운로드)
- `lookup.py` — 조회 핵심 로직 (CLI로도 실행 가능: `python3 lookup.py "회사명" "홈페이지"`)
