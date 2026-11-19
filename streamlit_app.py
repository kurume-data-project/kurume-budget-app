import io
import re
import requests
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="久留米市 予算・人口分析", page_icon="🏙️", layout="wide")

POP_XLS = "https://www.city.kurume.fukuoka.jp/1100keikaku/2010shoukai/3040toukei/4010koukujinkou/files/p10811.xls"
AGE_XLS = "https://www.city.kurume.fukuoka.jp/1100keikaku/2010shoukai/3040toukei/4040koukunenrei/files/p40810.xls"
POP_PDF = "https://www.city.kurume.fukuoka.jp/1100keikaku/2010shoukai/3040toukei/4010koukujinkou/files/p10811.pdf"
AGE_PDF = "https://www.city.kurume.fukuoka.jp/1100keikaku/2010shoukai/3040toukei/4040koukunenrei/files/p40810.pdf"

st.title("🏙️ 久留米市 予算・人口分析")
st.caption("久留米市の公開資料を使った校区別分析。統計上の旧校区名を保持します。")

with st.sidebar:
    st.header("データ設定")
    st.write("人口データ基準日：令和8年11月1日（校区別人口）")
    st.write("年齢別データ基準日：令和8年10月1日")
    st.markdown("[校区別人口・世帯数（公式PDF）](%s)" % POP_PDF)
    st.markdown("[校区別年齢別人口（公式PDF）](%s)" % AGE_PDF)
    st.markdown("[令和8年度予算資料](https://www.city.kurume.fukuoka.jp/1100keikaku/2070zaisei/3010yosan/4230yosanr08/2026-0212-1407-6.html)")
    st.info("人口と年齢別人口は公表日が異なるため、画面上でも基準日を分けて表示します。")

def read_excel_url(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return pd.read_excel(io.BytesIO(r.content), header=None)

@st.cache_data(ttl=3600, show_spinner=False)
def load_population():
    return read_excel_url(POP_XLS)

@st.cache_data(ttl=3600, show_spinner=False)
def load_age():
    return read_excel_url(AGE_XLS)

def normalize_columns(df):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df

def detect_population_table(raw):
    # 公開Excelのレイアウト差に備え、校区名・人口・男女の列を推定する
    rows = []
    for _, row in raw.iterrows():
        vals = [str(v).strip() for v in row.tolist()]
        vals = ["" if v.lower() == "nan" else v for v in vals]
        text = " ".join(vals)
        if not text:
            continue
        nums = []
        for v in vals:
            s = re.sub(r"[,，]", "", v)
            if re.fullmatch(r"\d+", s):
                nums.append(int(s))
        name = next((v for v in vals if v and not re.fullmatch(r"[\d,，]+", v)
                     and not any(k in v for k in ["校区名", "世帯数", "人口", "男", "女", "総数"])), "")
        if name and len(nums) >= 4 and name not in ["うち日本人", "うち外国人"]:
            # 公開表の並び：世帯数、人口、男、女
            rows.append({"校区": name, "世帯数": nums[-4], "人口": nums[-3],
                         "男性": nums[-2], "女性": nums[-1]})
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.drop_duplicates("校区", keep="first")
        out = out[~out["校区"].str.contains("総数|旧久留米市|旧田主丸|旧北野|旧城島|旧三潴|１世帯", na=False)]
    return out

def detect_age_table(raw):
    # 年齢別Excelは原表の列構成を保持して表示し、未確認の列を推測で変換しない
    raw = raw.dropna(how="all").copy()
    return raw

st.subheader("データの読み込み")
left, right = st.columns(2)
with left:
    if st.button("公式人口Excelを読み込む", use_container_width=True):
        try:
            raw = load_population()
            pop = detect_population_table(raw)
            if pop.empty:
                st.session_state["pop_raw"] = raw
                st.warning("Excelは取得できましたが、自動列判定ができません。原表を下に表示します。")
            else:
                st.session_state["population"] = pop
                st.success(f"{len(pop)}行の校区データを読み込みました。")
        except Exception as e:
            st.error(f"人口Excelを取得できませんでした：{e}")
            st.caption("下のファイルアップロードから、市公式ページのExcelを保存して読み込めます。")
with right:
    if st.button("公式年齢別人口Excelを読み込む", use_container_width=True):
        try:
            st.session_state["age_raw"] = load_age()
            st.success("年齢別人口Excelを取得しました。原表を表示します。")
        except Exception as e:
            st.error(f"年齢別人口Excelを取得できませんでした：{e}")

c1, c2 = st.columns(2)
with c1:
    pop_file = st.file_uploader("校区別人口Excel（市公式）", type=["xls", "xlsx"], key="pop_upload")
    if pop_file:
        try:
            raw = pd.read_excel(pop_file, header=None)
            pop = detect_population_table(raw)
            if not pop.empty:
                st.session_state["population"] = pop
                st.success(f"{len(pop)}行を読み込みました。")
            else:
                st.session_state["pop_raw"] = raw
                st.warning("列の自動判定ができません。原表データを表示します。")
        except Exception as e:
            st.error(f"読み込みエラー：{e}")
with c2:
    age_file = st.file_uploader("校区別年齢別人口Excel（市公式）", type=["xls", "xlsx"], key="age_upload")
    if age_file:
        try:
            st.session_state["age_raw"] = pd.read_excel(age_file, header=None)
            st.success("年齢別人口を読み込みました。")
        except Exception as e:
            st.error(f"読み込みエラー：{e}")

tabs = st.tabs(["人口分析", "予算分析", "地域分析", "データ・分類ルール"])

with tabs[0]:
    st.header("校区別の人口分析")
    pop = st.session_state.get("population")
    if pop is not None and not pop.empty:
        names = pop["校区"].tolist()
        selected = st.selectbox("校区を選択", names)
        rec = pop[pop["校区"] == selected].iloc[0]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("人口", f'{int(rec["人口"]):,}人')
        m2.metric("男性", f'{int(rec["男性"]):,}人')
        m3.metric("女性", f'{int(rec["女性"]):,}人')
        m4.metric("世帯数", f'{int(rec["世帯数"]):,}世帯')
        chart = pop.sort_values("人口", ascending=False)
        st.plotly_chart(px.bar(chart, x="校区", y="人口", title="校区別人口", text_auto=","),
                        use_container_width=True)
        st.dataframe(pop, use_container_width=True, hide_index=True)
        st.download_button("人口データCSVをダウンロード", pop.to_csv(index=False).encode("utf-8-sig"),
                           "kurume_population.csv", "text/csv")
    else:
        st.info("公式人口Excelを読み込むか、ファイルをアップロードしてください。")
    age_raw = st.session_state.get("age_raw")
    if age_raw is not None:
        st.subheader("校区別・男女別・5歳階級人口（公式原表）")
        st.caption("原表の数値・列順を保持しています。グラフ化は列構造を確認してから行います。")
        st.dataframe(age_raw, use_container_width=True, height=420)

with tabs[1]:
    st.header("予算分析")
    st.warning("予算書は款・項・目・事業別に整理する必要があります。金額を校区別に割り振れる根拠がない事業は、校区別予算として表示しません。")
    budget_file = st.file_uploader("予算データCSV/Excel（事項別明細書から整理したもの）",
                                   type=["csv", "xlsx"], key="budget_upload")
    if budget_file:
        try:
            if budget_file.name.endswith(".csv"):
                budget = pd.read_csv(budget_file)
            else:
                budget = pd.read_excel(budget_file)
            st.dataframe(budget, use_container_width=True)
            st.caption("推奨列：款、項、目、事業名、所管部署、予算額（円）、対象年代、対象性別、対象地域、分類根拠、データ区分")
            if "予算額（円）" in budget.columns and "款" in budget.columns:
                budget["予算額（億円）"] = pd.to_numeric(budget["予算額（円）"], errors="coerce") / 100000000
                st.plotly_chart(px.bar(budget, x="款", y="予算額（億円）", color="データ区分" if "データ区分" in budget.columns else None,
                                       title="款別予算（アップロードデータ）"), use_container_width=True)
        except Exception as e:
            st.error(f"予算ファイルを読み込めません：{e}")
    st.markdown("[久留米市・令和8年度一般会計予算書／事項別明細書](https://www.city.kurume.fukuoka.jp/1100keikaku/2070zaisei/3010yosan/4230yosanr08/2026-0212-1407-6.html)")

with tabs[2]:
    st.header("地域分析・地図")
    st.info("校区境界のGISデータを読み込んでいないため、この版では境界塗り分け地図は未実装です。公開GISの境界データを確認後に接続します。")
    st.markdown("[久留米市 公開型GIS「くるめMAP」](https://www.city.kurume.fukuoka.jp/)")
    geo = st.file_uploader("校区境界GeoJSON（GISデータ）", type=["geojson", "json"], key="geojson")
    if geo:
        st.success("GeoJSONを受け取りました。次段階で校区名と人口・予算データを結合します。")
        st.download_button("GeoJSONを保存", geo.getvalue(), "kurume_school_districts.geojson", "application/geo+json")

with tabs[3]:
    st.header("データの扱いと分類ルール")
    st.markdown("""
**実績**：公式資料に金額・対象地域等が明記されているもの。  
**推計**：事業内容や人口比等を使って配分したもの。推計方法を必ず表示。  
**不明**：対象者・実施場所・配分根拠を特定できないもの。

- 年代：事業説明・対象者要件に根拠がある場合だけ分類
- 性別：女性向け等の明確な根拠がある場合だけ分類。その他は「男女共通／不明」
- 地域：施設・工事等の実施場所が確認できる場合だけ校区に割当
- 全市対象：特定校区へ無理に配分せず「全市共通」
- 旧校区：公式統計の表記を維持し、統合前名称を消さない
""")
    st.caption("人口基準日：令和8年11月1日／年齢別人口基準日：令和8年10月1日。異なる基準日の数値を同一時点として比較しないでください。")

st.divider()
st.caption("出典：久留米市公式統計・令和8年度予算資料。データ取得・列判定に失敗した場合は、推測値を表示せずエラーを表示します。")

