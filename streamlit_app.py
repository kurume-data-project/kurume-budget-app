import re
import requests
import pandas as pd
import plotly.express as px
import streamlit as st

# ---------------------------------------
# 基本設定
# ---------------------------------------
st.set_page_config(
    page_title="久留米市 予算・人口分析",
    page_icon="🏙️",
    layout="wide"
)

st.title("🏙️ 久留米市 予算・人口分析")
st.caption(
    "久留米市の公開データを使った校区別分析。"
    "統計上の旧校区名もそのまま扱います。"
)

# BODIK公開データのリソースID
POP_RESOURCE_ID = "a02c75d8-3a7e-430f-9acc-32708f87beff"
AGE_RESOURCE_ID = "698a5ca0-5463-4972-abad-bf8861ef3c35"

API_URL = "https://data.bodik.jp/api/3/action/datastore_search"

POP_SOURCE = (
    "https://data.bodik.jp/dataset/402036_0000200_00001"
)
AGE_SOURCE = (
    "https://data.bodik.jp/dataset/402036_0000200_00031"
)

# ---------------------------------------
# CSVデータ取得
# ---------------------------------------
@st.cache_data(ttl=3600)
def fetch_bodik_data(resource_id):
    records = []
    offset = 0
    limit = 5000

    while True:
        response = requests.get(
            API_URL,
            params={
                "resource_id": resource_id,
                "limit": limit,
                "offset": offset
            },
            timeout=30
        )
        response.raise_for_status()

        result = response.json()

        if not result.get("success"):
            raise ValueError("公開データの取得に失敗しました")

        data = result["result"]["records"]

        if not data:
            break

        records.extend(data)
        offset += len(data)

        total = result["result"].get("total", 0)
        if offset >= total or len(data) < limit:
            break

    return pd.DataFrame(records)


# ---------------------------------------
# 列名を探す
# ---------------------------------------
def find_column(df, candidates):
    for col in df.columns:
        name = str(col).strip()
        for candidate in candidates:
            if candidate in name:
                return col
    return None


def clean_number(value):
    if pd.isna(value):
        return None

    text = str(value).strip()
    text = text.replace(",", "").replace("人", "").replace("世帯", "")

    if text in ["", "-", "－", "None", "nan"]:
        return None

    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None

    return int(float(match.group()))


# ---------------------------------------
# 人口データの整形
# ---------------------------------------
def normalize_population(raw):
    if raw.empty:
        raise ValueError("人口データが空です")

    school_col = find_column(
        raw,
        ["校区名", "校区名称", "小学校区", "校区"]
    )

    household_col = find_column(raw, ["世帯数"])
    population_col = find_column(raw, ["人口"])
    male_col = find_column(raw, ["男性", "男"])
    female_col = find_column(raw, ["女性", "女"])

    if school_col is None:
        raise ValueError(
            "校区名の列を特定できません。"
            "取得した列名を確認してください。"
        )

    if population_col is None:
        raise ValueError("人口の列を特定できません")

    result = pd.DataFrame()
    result["校区"] = raw[school_col].astype(str).str.strip()

    # 「1 西国分」のような先頭番号だけを除去
    result["校区"] = result["校区"].str.replace(
        r"^\s*\d+(?:\.0)?\s*", "", regex=True
    )

    result["人口"] = raw[population_col].apply(clean_number)

    if household_col is not None:
        result["世帯数"] = raw[household_col].apply(clean_number)
    else:
        result["世帯数"] = None

    if male_col is not None:
        result["男性"] = raw[male_col].apply(clean_number)
    else:
        result["男性"] = None

    if female_col is not None:
        result["女性"] = raw[female_col].apply(clean_number)
    else:
        result["女性"] = None

    # 空欄・合計行・番号だけの行を除外
    result = result[
        result["校区"].notna()
        & (result["校区"] != "")
        & (result["校区"].str.lower() != "nan")
        & (~result["校区"].str.fullmatch(r"\d+(?:\.\d+)?"))
    ].copy()

    result = result[
        ~result["校区"].str.contains(
            "合計|総数|久留米市計", na=False
        )
    ]

    result = result.dropna(subset=["人口"])
    result = result.drop_duplicates(subset=["校区"], keep="first")

    result["人口"] = result["人口"].astype(int)

    return result.reset_index(drop=True)


# ---------------------------------------
# データ読み込み
# ---------------------------------------
try:
    raw_population = fetch_bodik_data(POP_RESOURCE_ID)
    population = normalize_population(raw_population)

    if population.empty:
        raise ValueError("校区データが見つかりません")

    population_loaded = True

except Exception as e:
    population_loaded = False
    population = pd.DataFrame()
    raw_population = pd.DataFrame()
    st.error(f"人口データを取得できませんでした：{e}")


# ---------------------------------------
# タブ
# ---------------------------------------
tab1, tab2, tab3, tab4 = st.tabs([
    "人口分析",
    "予算分析",
    "地域分析",
    "データ・分類ルール"
])


# ---------------------------------------
# 1 人口分析
# ---------------------------------------
with tab1:
    st.header("校区別の人口分析")

    if population_loaded:

        st.success(
            f"公式データを取得しました：{len(population)}行"
        )

        st.caption(
            "出典：久留米市オープンデータ "
            "校区別人口及び世帯数"
        )

        school_list = population["校区"].tolist()

        selected_school = st.selectbox(
            "校区を選択",
            school_list
        )

        selected = population[
            population["校区"] == selected_school
        ].iloc[0]

        c1, c2, c3, c4 = st.columns(4)

        c1.metric("人口", f"{selected['人口']:,}人")

        if pd.notna(selected["男性"]):
            c2.metric("男性", f"{int(selected['男性']):,}人")
        else:
            c2.metric("男性", "データなし")

        if pd.notna(selected["女性"]):
            c3.metric("女性", f"{int(selected['女性']):,}人")
        else:
            c3.metric("女性", "データなし")

        if pd.notna(selected["世帯数"]):
            c4.metric(
                "世帯数",
                f"{int(selected['世帯数']):,}世帯"
            )
        else:
            c4.metric("世帯数", "データなし")

        st.divider()

        st.subheader(f"{selected_school}校区の人口")

        chart = px.bar(
            population.sort_values("人口", ascending=False),
            x="校区",
            y="人口",
            title="校区別人口",
            labels={"校区": "校区", "人口": "人口（人）"}
        )
        chart.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(chart, use_container_width=True)

        st.subheader("校区別人口データ")

        st.dataframe(
            population,
            use_container_width=True,
            hide_index=True
        )

        csv = population.to_csv(
            index=False,
            encoding="utf-8-sig"
        )

        st.download_button(
            "人口データCSVをダウンロード",
            csv,
            file_name="kurume_population.csv",
            mime="text/csv"
        )

    else:
        st.warning("人口データを読み込めていません")


# ---------------------------------------
# 2 予算分析
# ---------------------------------------
with tab2:
    st.header("予算分析")

    st.info(
        "予算書データとの接続は次の工程です。"
        "現時点では予算額を推測して表示しません。"
    )

    st.markdown("""
    今後取り込む項目：

    - 款・項・目
    - 事業名
    - 所管部署
    - 予算額
    - 事業対象（子ども・高齢者など）
    - 対象地域
    """)

    st.caption(
        "分類は予算書の記載内容に基づいて行い、"
        "推計と実績を区別します。"
    )


# ---------------------------------------
# 3 地域分析
# ---------------------------------------
with tab3:
    st.header("地域分析")

    st.info(
        "校区別の人口データを基礎にした地域分析です。"
    )

    if population_loaded:
        st.subheader("人口の多い校区")

        top = population.sort_values(
            "人口", ascending=False
        ).head(10)

        st.dataframe(
            top[["校区", "人口", "世帯数"]],
            use_container_width=True,
            hide_index=True
        )

    st.markdown(
        "[久留米市公開型GIS「くるめMAP」を確認する]"
        "(https://www.city.kurume.fukuoka.jp/)"
    )

    st.caption(
        "校区境界ポリゴンは未接続です。"
        "この画面は校区境界を描画した地図ではありません。"
    )


# ---------------------------------------
# 4 データ・分類ルール
# ---------------------------------------
with tab4:
    st.header("データ・分類ルール")

    st.subheader("人口データ")

    st.markdown(f"""
    - 出典：久留米市オープンデータ
    - データセット：[校区別人口及び世帯数]({POP_SOURCE})
    - 年齢別データ：[校区別年齢別人口]({AGE_SOURCE})
    - 校区名：公式統計の名称を保持
    """)

    st.subheader("データの扱い")

    st.markdown("""
    | 区分 | 扱い |
    |---|---|
    | 実績 | 公式資料に記載された数値 |
    | 推計 | 分類や按分によって算出した数値 |
    | 不明 | 対象地域・対象者を特定できないもの |

    旧校区名は統計上の区分として保持します。
    現行校区との統合は、この段階では行いません。
    """)

    st.subheader("取得した人口データの列名")

    if population_loaded:
        st.write(list(raw_population.columns))

        st.write(
            f"取得レコード数：{len(raw_population)}"
        )
        st.write(
            f"校区データ数：{len(population)}"
        )

        st.subheader("取得元データの確認")
        st.dataframe(
            raw_population.head(10),
            use_container_width=True
        )

    st.markdown("""
    ---
    **次の開発予定**

    1. 校区別年齢人口の分析
    2. 予算書の事業別データ取り込み
    3. GIS校区境界の表示
    4. 年代・性別・地域別の政策分析
    """)


