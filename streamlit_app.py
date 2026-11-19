
import streamlit as st

st.set_page_config(
    page_title="久留米市予算・人口分析",
    page_icon="🏙️",
    layout="wide"
)

st.title("🏙️ 久留米市 予算・人口分析")
st.caption("久留米市の公開データを活用した分析アプリ")

st.header("校区別の人口分析")

districts = ["荘島", "日吉", "篠山", "京町", "南薫"]

district = st.selectbox(
    "校区を選択してください",
    districts
)

st.info(f"選択中の校区：{district}")

tab1, tab2, tab3 = st.tabs(
    ["人口分析", "予算分析", "地域分析"]
)

with tab1:
    st.write("年代別・男女別の人口を分析します。")

with tab2:
    st.write("款・項・目・事業別の予算を分析します。")

with tab3:
    st.write("校区別の地図と地域別の分析を表示します。")
