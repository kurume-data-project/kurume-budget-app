import io
import re
import requests
import pandas as pd
import streamlit as st
import plotly.express as px

# ============================================================
# 久留米市 予算・人口分析アプリ
# 人口データはBODIKのCSVを直接取得します（Excel不要）
# ============================================================

st.set_page_config(
    page_title="久留米市 予算・人口分析",
    page_icon="🏙️",
    layout="wide",
)

POP_DATASET = "402036_0000200_00001"   # 校区別人口・世帯数
AGE_DATASET = "402036_0000200_00031"   # 校区別年齢別人口
CKAN_API = "https://data.bodik.jp/api/3/action/package_show?id={}"

st.title("🏙️ 久留米市 予算・人口分析")
st.caption(
    "久留米市の公開データを使った校区別分析です。"
    "統計上の旧校区名を保持し、現行校区への統合は行いません。"
)

# ---------- 共通処理 ----------

@st.cache_data(ttl=3600, show_spinner=False)
def get_dataset_csv(dataset_id: str) -> tuple[pd.DataFrame, str, str]:
    """BODIK CKAN APIから最新のCSVリソースを取得する。"""
    api_url = CKAN_API.format(dataset_id)
    response = requests.get(api_url, timeout=30)
    response.raise_for_status()
    payload = response.json()

    if not payload.get("success"):
        raise ValueError("BODIKのデータセット情報を取得できませんでした。")

    resources = payload["result"].get("resources", [])
    csv_resources = [
        r for r in resources
        if str(r.get("format", "")).upper() == "CSV"
        or str(r.get("mimetype", "")).lower().find("csv") >= 0
        or str(r.get("url", "")).lower().endswith(".csv")
    ]

    if not csv_resources:
        raise ValueError("データセット内にCSVファイルが見つかりません。")

    # 先頭のCSVリソースを利用。最新年のリソースが先頭に掲載される構成。
    resource = csv_resources[0]
    csv_response = requests.get(resource["url"], timeout=30)
    csv_response.raise_for_status()
    raw = csv_response.content

    df = None
    last_error = None
    for encoding in ("utf-8-sig", "cp932", "shift_jis", "utf-8"):
        try:
            df = pd.read_csv(io.BytesIO(raw), encoding=encoding)
            break
        except Exception as exc:
            last_error = exc

    if df is None:
        raise ValueError(f"CSVを読み込めませんでした: {last_error}")

    title = resource.get("name") or resource.get("description") or "BODIK CSV"
    modified = resource.get("last_modified") or resource.get("metadata_modified") or ""
    return df, title, modified


def clean_text(value):
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", "", str(value)).replace("\ufeff", "")


def find_column(df, candidates):
    """候補文字列を含む列名を探す。"""
    cols = {clean_text(c): c for c in df.columns}
    for candidate in candidates:
        candidate = clean_text(candidate)
        for normalized, original in cols.items():
            if candidate == normalized or candidate in normalized:
                return original
    return None


def numeric_series(series):
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False)
        .str.replace("人", "", regex=False)
        .str.replace("世帯", "", regex=False)
        .str.replace(" ", "", regex=False),
        errors="coerce",
    )


def normalize_population(raw):
    """校区別人口CSVの列名の違いを吸収する。列が不明なら推測せず停止する。"""
    area_col = find_column(raw, ["校区名", "校区", "小学校区"])
    household_col = find_column(raw, ["世帯数", "世帯"])
    population_col = find_column(raw, ["人口", "総人口"])
    male_col = find_column(raw, ["男性", "男"])
    female_col = find_column(raw, ["女性", "女"])

    if area_col is None:
        raise ValueError(
            "校区名の列を特定できません。取得したCSVの列名を「元データ確認」に表示します。"
        )

    # 総計行などを除き、校区名がある行だけを使う
    result = pd.DataFrame()
    result["校区"] = raw[area_col].map(clean_text)
    result = result[result["校区"] != ""].copy()

    # 人口データに男女列がある場合は男女合計も確認できるようにする
    if population_col is not None:
        result["人口"] = numeric_series(raw.loc[result.index, population_col])
    if male_col is not None:
        result["男性"] = numeric_series(raw.loc[result.index, male_col])
    if female_col is not None:
        result["女性"] = numeric_series(raw.loc[result.index, female_col])
    if household_col is not None:
        result["世帯数"] = numeric_series(raw.loc[result.index, household_col])

    # 人口列がなく、男女列がある場合だけ男女合計を人口として扱う
    if "人口" not in result.columns and {"男性", "女性"}.issubset(result.columns):
        result["人口"] = result["男性"].fillna(0) + result["女性"].fillna(0)

    if "人口" not in result.columns:
        raise ValueError(
            "人口の列を特定できません。列名を自動変換せず、元データを確認してください。"
        )

    result = result.dropna(subset=["人口"])
    result = result[~result["校区"].str.contains("総数|合計|久留米市全体", na=False)]
    result = result.drop_duplicates(subset=["校区"], keep="first")
    return result.reset_index(drop=True)


def normalize_age(raw):
    """年齢別CSVは形式が異なる場合があるため、列構成を確認してから表示する。"""
    area_col = find_column(raw, ["校区名", "校区", "小学校区"])
    if area_col is None:
        return None, "校区名の列を特定できませんでした。元データを確認してください。"

    age_col = find_column(raw, ["年齢階級", "年齢区分", "年齢", "歳"])
    count_col = find_column(raw, ["人口", "人数", "計"])
    sex_col = find_column(raw, ["男女", "性別", "男女人口"])

    if age_col is not None and count_col is not None:
        out = pd.DataFrame({
            "校区": raw[area_col].map(clean_text),
            "年齢区分": raw[age_col].map(clean_text),
            "人口": numeric_series(raw[count_col]),
        })
        if sex_col is not None:
            out["性別"] = raw[sex_col].map(clean_text)
        out = out.dropna(subset=["人口"])
        return out, None

    # 横持ち形式（0～4歳、5～9歳等）なら年齢階級列を抽出
    age_columns = [
        c for c in raw.columns
        if re.search(r"\d+\s*[-～〜]\s*\d+|\d+歳|未満|以上", clean_text(c))
    ]
    if age_columns:
        work = raw[[area_col] + age_columns].copy()
        long_df = work.melt(
            id_vars=[area_col],
            value_vars=age_columns,
            var_name="年齢区分",
            value_name="人口",
        )
        long_df.columns = ["校区", "年齢区分", "人口"]
        long_df["校区"] = long_df["校区"].map(clean_text)
        long_df["人口"] = numeric_series(long_df["人口"])
        return long_df.dropna(subset=["人口"]), None

    return None, "年齢階級・人口の列構成を自動判定できませんでした。元CSVを確認してください。"


# ---------- データ取得 ----------

with st.sidebar:
    st.header("データ")
    st.write("人口データはBODIKから直接取得します。")
    if st.button("データを再取得", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption("取得できない場合は、時間をおいて再取得してください。")

population = pd.DataFrame()
population_raw = pd.DataFrame()
population_source = ""
population_error = ""

try:
    population_raw, population_source, _ = get_dataset_csv(POP_DATASET)
    population = normalize_population(population_raw)
except Exception as exc:
    population_error = str(exc)

age_raw = pd.DataFrame()
age_data = None
age_source = ""
age_error = ""
try:
    age_raw, age_source, _ = get_dataset_csv(AGE_DATASET)
    age_data, age_error = normalize_age(age_raw)
except Exception as exc:
    age_error = str(exc)


# ---------- タブ ----------

tab1, tab2, tab3, tab4 = st.tabs(
    ["人口分析", "年齢分析", "予算分析", "データ・分類ルール"]
)

with tab1:
    st.header("校区別人口・世帯数")

    if population_error:
        st.error(f"人口データを取得・整理できませんでした: {population_error}")
        st.info("「元データ確認」タブでCSVの列名を確認できます。")
    elif population.empty:
        st.warning("人口データがありません。")
    else:
        st.success(f"{len(population)}行の校区データを取得しました。")
        area_options = population["校区"].tolist()
        selected_area = st.selectbox("校区を選択", area_options)
        selected = population[population["校区"] == selected_area].iloc[0]

        cols = st.columns(4)
        metrics = [
            ("人口", "人口", "人"),
            ("男性", "男性", "人"),
            ("女性", "女性", "人"),
            ("世帯数", "世帯数", "世帯"),
        ]
        for col, (label, key, unit) in zip(cols, metrics):
            if key in population.columns and pd.notna(selected.get(key)):
                col.metric(label, f"{int(selected[key]):,}{unit}")
            else:
                col.metric(label, "データなし")

        st.subheader("校区別人口")
        chart = population.sort_values("人口", ascending=False)
        fig = px.bar(
            chart, x="校区", y="人口",
            title="校区別人口（多い順）",
            labels={"校区": "統計上の校区名", "人口": "人口（人）"},
        )
        fig.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)

        if {"男性", "女性"}.issubset(population.columns):
            sex_df = population[["校区", "男性", "女性"]].melt(
                id_vars="校区", var_name="性別", value_name="人口"
            )
            fig2 = px.bar(
                sex_df, x="校区", y="人口", color="性別",
                barmode="group", title="校区別・男女別人口",
            )
            fig2.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig2, use_container_width=True)

        st.subheader("人口データ一覧")
        st.dataframe(population, use_container_width=True, hide_index=True)
        st.download_button(
            "人口データをCSVでダウンロード",
            population.to_csv(index=False).encode("utf-8-sig"),
            file_name="kurume_population_by_school_district.csv",
            mime="text/csv",
        )

with tab2:
    st.header("校区別・年齢別人口")
    if age_error:
        st.warning(f"年齢別データを表示できません: {age_error}")
    elif age_data is None or age_data.empty:
        st.warning("年齢別データがありません。")
    else:
        age_areas = sorted(age_data["校区"].dropna().unique().tolist())
        selected_age_area = st.selectbox("校区を選択", age_areas, key="age_area")
        view = age_data[age_data["校区"] == selected_age_area].copy()

        if "性別" in view.columns:
            sex_options = ["すべて"] + sorted(view["性別"].dropna().unique().tolist())
            selected_sex = st.selectbox("性別", sex_options)
            if selected_sex != "すべて":
                view = view[view["性別"] == selected_sex]

        fig = px.bar(
            view, x="年齢区分", y="人口",
            color="性別" if "性別" in view.columns else None,
            title=f"{selected_age_area}の年齢別人口",
        )
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(view, use_container_width=True, hide_index=True)
        st.download_button(
            "年齢別データをCSVでダウンロード",
            view.to_csv(index=False).encode("utf-8-sig"),
            file_name="kurume_age_by_school_district.csv",
            mime="text/csv",
        )

with tab3:
    st.header("予算分析")
    st.info(
        "人口データとは別に、予算書の事業・款項目データを取り込む領域です。"
        "現時点では、予算額を校区・年代・性別に自動配分していません。"
    )
    st.markdown(
        """
        **分析上のルール**
        - 予算書に記載された款・項・目・事業名・所管部署を基礎に分類します。
        - 事業対象の年代・性別が明記されていない場合は「全世代・男女共通」または「不明」とします。
        - 実施場所が確認できる事業だけ校区に割り当てます。
        - 全市対象の事業は「全市共通」、場所が特定できない事業は「校区不明」とします。
        - 人口比で按分する場合は、実績ではなく「推計」と明記します。
        """
    )
    st.markdown(
        "[久留米市 令和8年度予算書・事項別明細書](https://www.city.kurume.fukuoka.jp/1100keikaku/2070zaisei/3010yosan/4230yosanr08/2026-0212-1407-6.html)"
    )
    st.caption("予算額の校区別実績が公開されているとは限らないため、推計と実績を混同しません。")

with tab4:
    st.header("データ・分類ルール")
    st.subheader("取得元")
    st.markdown(
        f"""
        - 校区別人口・世帯数： [BODIKデータセット](https://data.bodik.jp/dataset/{POP_DATASET})
        - 校区別年齢別人口： [BODIKデータセット](https://data.bodik.jp/dataset/{AGE_DATASET})
        - 久留米市の校区別人口ページ： [市公式ページ](https://www.city.kurume.fukuoka.jp/1100keikaku/2010shoukai/3040toukei/4010koukujinkou/)
        - 久留米市の校区別年齢別人口ページ： [市公式ページ](https://www.city.kurume.fukuoka.jp/1100keikaku/2010shoukai/3040toukei/4040koukunenrei/)
        """
    )
    st.subheader("校区の扱い")
    st.write(
        "統計データに掲載された校区名をそのまま保持します。"
        "学校統合前の旧校区名も、データ上に存在する場合は統合せずに表示します。"
    )
    st.subheader("取得した人口CSVの列")
    if not population_raw.empty:
        st.write("人口CSVの列名")
        st.code(" / ".join(map(str, population_raw.columns)))
        st.dataframe(population_raw.head(15), use_container_width=True)
    else:
        st.warning("人口CSVを取得できていません。")

    st.subheader("取得した年齢別CSVの列")
    if not age_raw.empty:
        st.write("年齢別CSVの列名")
        st.code(" / ".join(map(str, age_raw.columns)))
        st.dataframe(age_raw.head(15), use_container_width=True)
    else:
        st.warning("年齢別CSVを取得できていません。")

    st.subheader("地図")
    st.markdown(
        "[久留米市公開型GIS「くるめMAP」](https://www.city.kurume.fukuoka.jp/)"
    )
    st.caption(
        "この版では校区境界ポリゴンをまだ描画していません。"
        "校区境界データを確認・接続するまでは、地図上の塗り分けを実装済みとは扱いません。"
    )

st.divider()
st.caption(
    "出典：久留米市・BODIKオープンデータ。"
    "データの基準日・更新日は取得元の公開情報を確認してください。"
)


