#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""사업자정보 일괄조회 — 회사명 + 홈페이지 → 사업자등록번호 + 부가정보

회사명·홈페이지 목록(엑셀/CSV 업로드 또는 표 붙여넣기)을 넣으면
bizno.net에서 사업자등록번호와 대표자·주소·업태·종목·규모·이메일·전화를
일괄 조회해 결과 표를 다운로드한다. (조회 로직은 lookup.py)
"""
import io
import time
import pandas as pd
import streamlit as st

import lookup

st.set_page_config(page_title="사업자정보 일괄조회", page_icon="🏢", layout="wide")

st.title("🏢 사업자정보 일괄조회")
st.caption("회사명 + 홈페이지 주소 → 사업자등록번호 · 대표자 · 주소 · 업태/종목 · 규모 · 이메일 · 전화")

with st.expander("ℹ️ 사용법 / 동작 방식", expanded=False):
    st.markdown(
        """
**입력**: 회사명과 (있으면) 홈페이지 주소 목록. 홈페이지는 비어 있어도 됩니다.

**조회 순서**
1. 홈페이지가 있으면 그 사이트(푸터·회사소개·약관 페이지)에서 사업자번호를 직접 추출
2. 못 찾으면 bizno.net에서 회사명으로 검색
   - 같은 이름 회사가 하나뿐이면 채택 *(신뢰도: 중간)*
   - 같은 이름이 여럿이면 입력한 홈페이지 도메인이 일치하는 회사 선택 *(신뢰도: 높음)*
   - 끝까지 못 좁히면 가장 비슷한 후보를 참고용으로 표시 *(신뢰도: 낮음)*
3. 사업자번호를 찾으면 그 번호로 부가정보(대표자·주소·업태 등)를 가져옵니다

**신뢰도 보는 법** — `높음`(홈페이지·도메인 일치)은 신뢰, `중간`(유일일치)은 동명업체가
있으면 다를 수 있어 확인 권장, `낮음/확인필요`는 반드시 검증하세요.

⚠️ 외부 사이트를 한 건씩 조회하므로 건수가 많으면 시간이 걸립니다(건당 약 1~2초).
        """
    )

st.divider()

# ---------- 입력 ----------
tab_paste, tab_upload = st.tabs(["📋 표 붙여넣기", "📁 파일 업로드 (엑셀/CSV)"])

df_in = None

with tab_paste:
    st.write("엑셀에서 **회사명·홈페이지 두 열**을 복사해 붙여넣거나, 한 줄에 하나씩 입력하세요.")
    sample = "회사명\t홈페이지\n비디오몬스터\thttps://videomonster.com\n쉐코\thttps://shecco.com"
    txt = st.text_area("회사명 [탭/쉼표] 홈페이지", value="", height=180,
                       placeholder=sample)
    if txt.strip():
        rows = []
        for line in txt.strip().splitlines():
            parts = [p.strip() for p in
                     (line.split("\t") if "\t" in line else line.split(","))]
            if not parts or not parts[0]:
                continue
            name = parts[0]
            hp = parts[1] if len(parts) > 1 else ""
            rows.append({"회사명": name, "홈페이지": hp})
        if rows:
            df_in = pd.DataFrame(rows)
            # 헤더 줄로 보이면 제거
            if df_in.iloc[0]["회사명"] in ("회사명", "기업명", "상호", "회사"):
                df_in = df_in.iloc[1:].reset_index(drop=True)

with tab_upload:
    up = st.file_uploader("엑셀(.xlsx) 또는 CSV 파일", type=["xlsx", "xls", "csv"])
    if up is not None:
        try:
            raw = (pd.read_csv(up) if up.name.lower().endswith("csv")
                   else pd.read_excel(up))
        except Exception as e:
            st.error(f"파일을 읽지 못했습니다: {e}")
            raw = None
        if raw is not None and len(raw.columns):
            cols = list(raw.columns)

            def guess(keys, default_idx=0):
                for i, c in enumerate(cols):
                    if any(k in str(c) for k in keys):
                        return i
                return default_idx

            c1, c2 = st.columns(2)
            name_col = c1.selectbox("회사명 열", cols,
                                    index=guess(["회사", "기업", "상호", "업체"]))
            hp_default = guess(["홈페이지", "url", "URL", "사이트", "web", "주소"],
                               min(1, len(cols) - 1))
            hp_col = c2.selectbox("홈페이지 열 (없으면 회사명과 같은 열로 두면 무시)",
                                  cols, index=hp_default)
            df_in = pd.DataFrame({
                "회사명": raw[name_col].astype(str).str.strip(),
                "홈페이지": ("" if hp_col == name_col
                          else raw[hp_col].fillna("").astype(str).str.strip()),
            })
            df_in = df_in[df_in["회사명"].str.len() > 0].reset_index(drop=True)

# ---------- 미리보기 & 실행 ----------
if df_in is not None and len(df_in):
    st.success(f"입력 {len(df_in)}건 인식됨")
    st.dataframe(df_in.head(20), use_container_width=True, hide_index=True)

    if st.button("🔎 사업자정보 조회 시작", type="primary"):
        prog = st.progress(0.0, text="조회 준비 중…")
        results = []
        total = len(df_in)
        for i, row in df_in.iterrows():
            name, hp = row["회사명"], row["홈페이지"]
            try:
                res = lookup.lookup_one(name, hp)
            except Exception as e:
                res = {k: "" for k in lookup.RESULT_FIELDS}
                res["조회출처"] = f"오류:{e}"
            results.append({"회사명": name, "홈페이지": hp, **res})
            prog.progress((i + 1) / total,
                          text=f"{i + 1}/{total} — {str(name)[:20]} → "
                               f"{res.get('사업자등록번호') or '미발견'}")
            time.sleep(0.3)  # 외부 사이트 과부하 방지
        prog.empty()

        out = pd.DataFrame(results)
        found = (out["사업자등록번호"].str.len() > 0).sum()
        high = out["신뢰도"].eq("높음").sum()
        st.success(f"완료 — {total}건 중 사업자번호 {found}건 발견 "
                   f"(신뢰도 높음 {high}건)")

        def color(v):
            return {"높음": "background-color:#d4f7d4",
                    "중간": "background-color:#fff3cd",
                    "낮음": "background-color:#f8d7da"}.get(v, "")

        st.dataframe(out.style.applymap(color, subset=["신뢰도"]),
                     use_container_width=True, hide_index=True)

        # 다운로드(엑셀)
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            out.to_excel(w, index=False, sheet_name="조회결과")
        st.download_button("⬇️ 결과 엑셀 다운로드", data=buf.getvalue(),
                           file_name="사업자정보_조회결과.xlsx",
                           mime="application/vnd.openxmlformats-officedocument."
                                "spreadsheetml.sheet")
else:
    st.info("위에서 회사명·홈페이지 목록을 붙여넣거나 파일을 업로드하세요.")
