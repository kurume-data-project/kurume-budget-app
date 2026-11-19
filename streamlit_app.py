import io
import re
from pathlib import Path

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(page_title="久留米市 予算・地域分析", page_icon="🏙️", layout="wide")

POP_DATASET = "402036_0000200_00001"
AGE_DATASET = "402036_0000200_00031"
CKAN_API = "https://data.bodik.jp/api/3/action/package_show?id={}"
BASE_DIR = Path(__file__).resolve().parent
BUDGET_FILE = BASE_DIR / "kurume_budget.csv"
URBAN_FILE = BASE_DIR / "urban_area_master.csv"

st.title("🏙️ 久留米市 予算・地域分析")
st.caption("校区別人口・年齢構成と、令和8年度予算事業の属性を確認する試作アプリ")

with st.sidebar:
    st.header("データ設定")
    st.write("人口データ：BODIKから最新CSVを取得")
    refresh = st.button("人口データを再取得", use_container_width=True)
    if refresh:
        st.cache_data.clear()
        st.rerun()
    st.caption("予算データは同梱CSVを読み込みます。更新時はCSVを差し替えてください。")

def clean(v):
    if pd.isna(v):
        return ""
    return re.sub(r"\s+", "", str(v)).replace("\ufeff", "")

def find_col(df, candidates):
    norm = {clean(c): c for c in df.columns}
    for cand in candidates:
        cand = clean(cand)
        for n, original in norm.items():
            if cand == n or cand in n:
                return original
    return None

def to_num(s):
    return pd.to_numeric(
        s.astype(str).str.replace(",", "", regex=False)
         .str.replace("人", "", regex=False)
         .str.replace("世帯", "", regex=False)
         .str.replace("－", "", regex=False)
         .str.replace("-", "", regex=False),
        errors="coerce"
    )

@st.cache_data(ttl=3600, show_spinner=False)
def get_dataset_csv(dataset_id):
    response = requests.get(CKAN_API.format(dataset_id), timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise ValueError("BODIKデータセット情報を取得できません。")
    resources = payload["result"].get("resources", [])
    resources = [r for r in resources if "csv" in (
        str(r.get("format", "")) + str(r.get("mimetype", "")) + str(r.get("url", ""))
    ).lower()]
    if not resources:
        raise ValueError("CSVリソースが見つかりません。")
    # 年度が明記されたリソースを優先し、令和8年を優先する
    resources.sort(key=lambda r: (
        "令和8年" in str(r.get("name", "")) or "令和8年" in str(r.get("description", "")),
        str(r.get("last_modified", "")) or str(r.get("metadata_modified", ""))
    ), reverse=True)
    resource = resources[0]
    raw = requests.get(resource["url"], timeout=30)
    raw.raise_for_status()
    last_error = None
    for enc in ("utf-8-sig", "cp932", "shift_jis", "utf-8"):
        try:
            df = pd.read_csv(io.BytesIO(raw.content), encoding=enc)
            return df, resource.get("name", "BODIK CSV"), resource.get("url", "")
        except Exception as e:
            last_error = e
    raise ValueError(f"CSV読込エラー: {last_error}")

def normalize_population(raw):
    area = find_col(raw, ["校区名", "校区", "小学校区"])
    household = find_col(raw, ["世帯数", "世帯"])
    population = find_col(raw, ["人口", "総人口"])
    male = find_col(raw, ["男性", "男"])
    female = find_col(raw, ["女性", "女"])
    if area is None:
        raise ValueError("校区名列を特定できません。元データを「データ確認」で確認してください。")
    d = pd.DataFrame({"校区": raw[area].map(clean)})
    if population is not None:
        d["人口"] = to_num(raw[population])
    if male is not None:
        d["男性"] = to_num(raw[male])
    if female is not None:
        d["女性"] = to_num(raw[female])
    if household is not None:
        d["世帯数"] = to_num(raw[household])
    if "人口" not in d and {"男性", "女性"}.issubset(d.columns):
        d["人口"] = d["男性"].fillna(0) + d["女性"].fillna(0)
    if "人口" not in d:
        raise ValueError("人口列を特定できません。")
    d = d[(d["校区"] != "") & (~d["校区"].str.contains("総数|合計|久留米市全体", na=False))]
    d = d.dropna(subset=["人口"]).drop_duplicates("校区")
    return d.reset_index(drop=True)

def normalize_age(raw):
    area = find_col(raw, ["校区名", "校区", "小学校区"])
    if area is None:
        return None, "校区名列を特定できません。"
    age = find_col(raw, ["年齢階級", "年齢区分", "年齢"])
    count = find_col(raw, ["人口", "人数", "計"])
    sex = find_col(raw, ["性別", "男女"])
    if age is not None and count is not None:
        d = pd.DataFrame({"校区": raw[area].map(clean), "年齢区分": raw[age].map(clean), "人口": to_num(raw[count])})
        if sex is not None:
            d["性別"] = raw[sex].map(clean)
        return d.dropna(subset=["人口"]), None
    age_cols = [c for c in raw.columns if re.search(r"\d+\s*[-～〜]\s*\d+|\d+歳|未満|以上", clean(c))]
    if age_cols:
        d = raw[[area] + age_cols].melt(id_vars=[area], var_name="年齢区分", value_name="人口")
        d.columns = ["校区", "年齢区分", "人口"]
        d["校区"] = d["校区"].map(clean)
        d["人口"] = to_num(d["人口"])
        return d.dropna(subset=["人口"]), None
    return None, "年齢階級の列構成を自動判定できません。"

@st.cache_data
def load_local_csv(path):
    return pd.read_csv(path, encoding="utf-8-sig")

# Load bundled budget and classification master
try:
    budget = load_local_csv(BUDGET_FILE)
    budget_error = None
except Exception as e:
    budget = pd.DataFrame()
    budget_error = str(e)

try:
    urban_master = load_local_csv(URBAN_FILE)
except Exception:
    urban_master = pd.DataFrame()

# Live population data
pop_raw = pd.DataFrame()
age_raw = pd.DataFrame()
population = pd.DataFrame()
age_data = None
pop_error = age_error = None
try:
    pop_raw, pop_title, pop_url = get_dataset_csv(POP_DATASET)
    population = normalize_population(pop_raw)
except Exception as e:
    pop_error = str(e)
try:
    age_raw, age_title, age_url = get_dataset_csv(AGE_DATASET)
    age_data, age_error = normalize_age(age_raw)
except Exception as e:
    age_error = str(e)

tabs = st.tabs(["概要", "校区別人口", "年齢構成", "予算事業", "地域・都市計画", "データ確認"])

with tabs[0]:
    st.header("分析の全体像")
    c1, c2, c3 = st.columns(3)
    c1.metric("人口データ", f"{len(population):,}校区" if not population.empty else "未取得")
    c2.metric("予算事業サンプル", f"{len(budget):,}件" if not budget.empty else "未登録")
    c3.metric("都市計画区域区分", "7分類")
    st.info("このアプリは政策分析の試作版です。予算事業サンプルは確認済みの6件であり、久留米市の全予算事業を網羅していません。")
    st.markdown("""
    **分析上の原則**
    - 予算額は予算書に記載された事業額です。住民一人ひとりの受益額ではありません。
    - 事業所在地が不明なものは校区・都市計画区域を「未判定」とします。
    - 人口比で配分する場合は「推計」とし、確定実績と区別します。
    - 旧校区名は統計の表記を維持し、自動統合しません。
    """)

with tabs[1]:
    st.header("校区別人口・世帯数")
    if pop_error:
        st.error(f"人口データ取得エラー：{pop_error}")
    elif population.empty:
        st.warning("人口データがありません。")
    else:
        st.success(f"{len(population)}行を取得：{pop_title}")
        area_list = population["校区"].tolist()
        selected = st.selectbox("校区", area_list)
        row = population[population["校区"] == selected].iloc[0]
        metrics = st.columns(4)
        for col, label in zip(metrics, ["人口", "男性", "女性", "世帯数"]):
            val = row.get(label)
            col.metric(label, f"{int(val):,}" if pd.notna(val) else "データなし")
        fig = px.bar(population.sort_values("人口", ascending=False), x="校区", y="人口", title="校区別人口")
        fig.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)
        if {"男性", "女性"}.issubset(population.columns):
            sex = population.melt(id_vars="校区", value_vars=["男性", "女性"], var_name="性別", value_name="人口")
            st.plotly_chart(px.bar(sex, x="校区", y="人口", color="性別", barmode="group", title="校区別男女別人口"), use_container_width=True)
        st.dataframe(population, use_container_width=True, hide_index=True)
        st.download_button("人口CSVを保存", population.to_csv(index=False).encode("utf-8-sig"), "kurume_population.csv", "text/csv")

with tabs[2]:
    st.header("校区別・年齢別人口")
    if age_error:
        st.warning(f"年齢別人口を表示できません：{age_error}")
        if not age_raw.empty:
            st.write("取得CSVの列名", list(age_raw.columns))
    elif age_data is None or age_data.empty:
        st.warning("年齢別人口データがありません。")
    else:
        area = st.selectbox("校区", sorted(age_data["校区"].dropna().unique()), key="age_district")
        view = age_data[age_data["校区"] == area].copy()
        if "性別" in view.columns:
            sexes = ["すべて"] + sorted(view["性別"].dropna().unique().tolist())
            chosen = st.selectbox("性別", sexes)
            if chosen != "すべて":
                view = view[view["性別"] == chosen]
        st.plotly_chart(px.bar(view, x="年齢区分", y="人口", color="性別" if "性別" in view.columns else None, title=f"{area} 年齢別人口"), use_container_width=True)
        st.dataframe(view, use_container_width=True, hide_index=True)
        st.download_button("年齢別CSVを保存", view.to_csv(index=False).encode("utf-8-sig"), "kurume_age_population.csv", "text/csv")

with tabs[3]:
    st.header("予算事業・対象属性")
    if budget_error:
        st.error(f"予算CSV読込エラー：{budget_error}")
    elif budget.empty:
        st.warning("kurume_budget.csv がありません。")
    else:
        st.warning("現在の収録は確認済みサンプル6事業です。全事業の一覧ではありません。")
        if "予算額_千円" in budget:
            total = pd.to_numeric(budget["予算額_千円"], errors="coerce").sum()
            st.metric("表示中サンプルの予算額合計", f"{total:,.0f} 千円")
        cols = st.columns(3)
        for col, field in zip(cols, ["政策分類", "性別", "都市計画区域区分"]):
            if field in budget:
                options = ["すべて"] + sorted(budget[field].fillna("不明").astype(str).unique().tolist())
                val = col.selectbox(field, options, key=f"filter_{field}")
                if val != "すべて":
                    budget = budget[budget[field].fillna("不明").astype(str) == val]
        search = st.text_input("事業名・款・項・目で検索")
        if search:
            mask = budget.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)
            budget = budget[mask]
        if "予算額_千円" in budget and not budget.empty:
            fig = px.bar(budget.sort_values("予算額_千円", ascending=False), x="事業名", y="予算額_千円", color="政策分類", title="事業別予算額（千円）")
            st.plotly_chart(fig, use_container_width=True)
        st.dataframe(budget, use_container_width=True, hide_index=True)
        st.download_button("表示中の予算データをCSV保存", budget.to_csv(index=False).encode("utf-8-sig"), "kurume_budget_filtered.csv", "text/csv")
        st.caption("校区別・都市計画区域別の予算配分は、所在地や事業対象区域との照合が済むまで表示しません。")

with tabs[4]:
    st.header("地域・都市計画区域")
    st.markdown("[久留米市公開型GIS「くるめMAP」](https://www.city.kurume.fukuoka.jp/1500soshiki/9010jimukan/3010oshirase/2025-0325-1024-14.html)")
    st.markdown("[久留米市 都市計画図](https://www.city.kurume.fukuoka.jp/1050kurashi/2070machi/3030toshi/4020toshikei/2020-0521-2002-88.html)")
    st.markdown("[国土交通省 都市計画決定GISデータ](https://www.mlit.go.jp/toshi/tosiko/toshi_tosiko_tk_000087.html)")
    st.dataframe(urban_master, use_container_width=True, hide_index=True)
    st.warning("境界ポリゴンはまだアプリに接続していません。ここでは分類マスターを表示しています。地点の区域判定や校区境界の塗り分けは未実装です。API利用申請は後回しにし、まず既存公開データで進めます。")

with tabs[5]:
    st.header("取得データ・出典")
    st.subheader("人口データ")
    st.markdown(f"- [校区別人口・世帯数（BODIK）](https://data.bodik.jp/dataset/{POP_DATASET})")
    st.markdown(f"- [校区別年齢別人口（BODIK）](https://data.bodik.jp/dataset/{AGE_DATASET})")
    st.markdown("- [久留米市公式・校区別人口](https://www.city.kurume.fukuoka.jp/1100keikaku/2010shoukai/3040toukei/4010koukujinkou/)")
    st.markdown("- [久留米市公式・校区別年齢別人口](https://www.city.kurume.fukuoka.jp/1100keikaku/2010shoukai/3040toukei/4040koukunenrei/)")
    if not pop_raw.empty:
        st.write("人口CSV列名", list(pop_raw.columns))
        st.dataframe(pop_raw.head(10), use_container_width=True)
    if not age_raw.empty:
        st.write("年齢CSV列名", list(age_raw.columns))
        st.dataframe(age_raw.head(10), use_container_width=True)
    st.subheader("予算データ")
    if not budget.empty:
        st.write("同梱の確認済み事業サンプル（6件）")
        st.dataframe(budget, use_container_width=True, hide_index=True)
        st.markdown("令和8年度予算書の款別事項別明細書を出典欄に記録しています。")
    st.caption("校区統合：令和3年 下田・浮島→城島、令和7年 青峰→高良内、令和8年 大橋→善導寺。統計表の旧校区名はそのまま保持します。")
