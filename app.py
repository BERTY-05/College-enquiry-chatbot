"""Streamlit front-end for the multilingual college information assistant.

Run with:   streamlit run app.py
"""

import csv
import json
import os
from collections import Counter
from pathlib import Path

import streamlit as st

from chatbot import CollegeAssistant, Translator, LANGUAGES, NATIVE_LANGS

LOG_PATH = Path(__file__).parent / "logs" / "chat_log.csv"
LANG_CHOICES = ["auto", "en", "ta", "hi", "te", "ml", "kn"]


def configured_admin_password() -> str:
    """Read the dashboard password from Streamlit secrets or environment."""
    try:
        secret = st.secrets.get("ADMIN_PASSWORD")
    except (FileNotFoundError, AttributeError):
        secret = None
    return str(secret or os.environ.get("ADMIN_PASSWORD", ""))


ADMIN_PASSWORD = configured_admin_password()

st.set_page_config(page_title="College Information Assistant", page_icon="🎓", layout="centered")


@st.cache_resource
def get_bot() -> CollegeAssistant:
    return CollegeAssistant(translator=Translator(), log_path=LOG_PATH)


bot = get_bot()

# -------------------------------------------------------- Chennai directory
DIRECTORY_PATH = Path(__file__).parent / "data" / "chennai_colleges.json"
with open(DIRECTORY_PATH, encoding="utf-8") as fh:
    directory = json.load(fh)

st.title("🎓 Chennai College Explorer")
st.caption(directory["description"])

search_col = st.text_input("Search by college name or area", placeholder="Try IIT Madras, Tambaram, or Guindy")
categories = sorted({college["category"] for college in directory["colleges"]})
category_col = st.selectbox("College type", ["All types", *categories])

filtered_colleges = [
    college for college in directory["colleges"]
    if (category_col == "All types" or college["category"] == category_col)
    and (not search_col or search_col.casefold() in f"{college['name']} {college['area']} {college['category']}".casefold())
]
st.caption(f"Showing {len(filtered_colleges)} of {len(directory['colleges'])} colleges")

if filtered_colleges:
    for start in range(0, len(filtered_colleges), 2):
        columns = st.columns(2)
        for column, college in zip(columns, filtered_colleges[start:start + 2]):
            with column.container(border=True):
                st.subheader(college["name"])
                st.caption(f"{college['category']} · {college['area']}")
                st.link_button("Visit official website", college["website"])
else:
    st.info("No colleges match those filters. Try a different name, area, or type.")

st.divider()
st.header("Ask about Chennai colleges")
st.info(
    "The directory has college names, types, areas, and official links. For current details like fees, "
    "courses, or admissions, the chatbot searches the web and shows source links; verify important facts "
    "with the college itself."
)

# ---------------------------------------------------------------- state
choice = st.session_state.get("lang_choice", "auto")
if choice in NATIVE_LANGS:
    ui_lang = choice
elif choice == "auto":
    ui_lang = st.session_state.get("last_lang", "en")
    ui_lang = ui_lang if ui_lang in NATIVE_LANGS else "en"
else:
    ui_lang = "en"  # interface text stays English for other languages

if "messages" not in st.session_state:
    st.session_state.messages = []
welcome_version = "chennai-directory-v1"
if not st.session_state.messages or (
    len(st.session_state.messages) == 1
    and (st.session_state.get("welcome_lang") != ui_lang
         or st.session_state.get("welcome_version") != welcome_version)
):
    st.session_state.messages = [{"role": "assistant", "content": bot.welcome(ui_lang)}]
    st.session_state.welcome_lang = ui_lang
    st.session_state.welcome_version = welcome_version


def ask(question: str) -> None:
    """Button callback: remember the clicked quick question."""
    st.session_state.pending = question


def clear_chat() -> None:
    st.session_state.messages = []
    st.session_state.pop("last_lang", None)


# -------------------------------------------------------------- sidebar
with st.sidebar:
    st.header(f"🌐 {bot.ui('language', ui_lang)}")
    st.selectbox(
        bot.ui("language", ui_lang),
        LANG_CHOICES,
        key="lang_choice",
        format_func=lambda c: bot.ui("auto", ui_lang) if c == "auto" else LANGUAGES[c],
        label_visibility="collapsed",
    )
    st.button(bot.ui("clear", ui_lang), on_click=clear_chat, use_container_width=True)
    st.caption(bot.ui("footer", ui_lang))

    with st.expander("🔒 Admin analytics"):
        if not ADMIN_PASSWORD:
            st.info("Analytics are disabled. Set ADMIN_PASSWORD in Streamlit secrets to enable them.")
            pwd = ""
        else:
            pwd = st.text_input("Password", type="password", key="admin_pwd")
        if ADMIN_PASSWORD and pwd and pwd == ADMIN_PASSWORD:
            rows = []
            if LOG_PATH.exists():
                with open(LOG_PATH, newline="", encoding="utf-8") as fh:
                    rows = list(csv.DictReader(fh))
            st.metric("Total questions", len(rows))
            if rows:
                import pandas as pd

                by_intent = Counter(r["intent"] for r in rows)
                st.caption("Questions by topic")
                st.bar_chart(pd.Series(by_intent, name="count"))
                by_lang = Counter(r["detected_lang"] for r in rows)
                st.caption("Questions by language")
                st.bar_chart(pd.Series(by_lang, name="count"))
                missed = [r["question"] for r in rows if r["intent"] == "fallback"]
                st.caption(f"Unanswered questions ({len(missed)}) - add these to the data file")
                st.write(missed[-20:])
        elif ADMIN_PASSWORD and pwd:
            st.error("Wrong password")

# ----------------------------------------------------------------- chat
st.caption(bot.ui("title", ui_lang))

prompt = st.chat_input(bot.ui("placeholder", ui_lang))
if not prompt:
    prompt = st.session_state.pop("pending", None)

if prompt:
    result = bot.reply(prompt, preferred=choice)
    st.session_state.last_lang = result.lang
    reply_text = result.text + (f"\n\n_{result.notice}_" if result.notice else "")
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.session_state.messages.append({"role": "assistant", "content": reply_text})

for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar="🎓" if msg["role"] == "assistant" else None):
        st.markdown(msg["content"])

st.markdown(f"**{bot.ui('quick', ui_lang)}**")
sug_lang = st.session_state.get("last_lang", ui_lang) if choice == "auto" else ui_lang
cols = st.columns(3)
for i, label in enumerate(bot.suggestions(sug_lang)):
    cols[i % 3].button(label, key=f"sg_{i}", on_click=ask, args=(label,), use_container_width=True)
