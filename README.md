# Chennai College Explorer

A searchable starter directory of selected universities and colleges in
Chennai and nearby Chennai metropolitan areas, across engineering, arts and
science, medical, and other categories. It includes links to institutional
websites. The directory is not exhaustive; confirm current details with each
institution.

The app includes a conversational assistant that searches this directory in
**English, Tamil and Hindi**, with automatic language detection. Questions about
current or missing details can use live web search, returning snippets and
source links. Other
Indian languages (Telugu, Malayalam, Kannada, ...) work through an optional
online translation fallback.

## Features
- Auto-detects the question language from its script (தமிழ், हिन्दी, తెలుగు ...)
- Understands romanised **Tanglish / Hinglish** ("hostel fees evlo", "fees kitni hai")
- 17 topics + department-wise details (CSE, IT, AI&DS, ECE, EEE, Mech, Civil)
- Language selector: Auto / English / Tamil / Hindi / Telugu / Malayalam / Kannada
- Quick-question buttons in the user's language
- Searchable Chennai-area college directory with category filters and official-site links
- Live, cited web search for questions beyond the local directory (internet required)
- Admin analytics: questions by topic and language, plus a list of unanswered questions
- Works fully **offline** for English / Tamil / Hindi (no API keys, no model downloads)

## Project structure
```
college_assistant/
├── app.py                  Streamlit web UI
├── cli.py                  Terminal version (no Streamlit needed)
├── chatbot/
│   ├── engine.py           Language detection, intent matching, answer generation
│   └── translator.py       Optional translation for other languages
├── data/chennai_colleges.json  Starter directory for the Chennai College Explorer
├── data/college_data.json  Sample profile and answers for the single-college chatbot
├── tests/test_engine.py    Unit tests
└── requirements.txt
```

## How it works
```
 user message
     │
     ├─ 1. detect language ........ Unicode script ranges (+ romanised hints for Latin text)
     ├─ 2. normalise .............. lower-case, strip punctuation, Unicode NFC
     ├─ 3. find department ........ CSE / ECE / ... aliases in any language
     ├─ 4. score intents .......... weighted keyword match (longer phrases weigh more)
     ├─ 5. pick answer ............ pre-written answer in en / ta / hi, filled with college facts
     └─ 6. (other languages) ...... translate question -> English, answer -> user's language
```
The Chennai directory answers with its stored college name, type, area, and
official website. For facts not in the directory (such as current fees or
course lists), it asks which institution is meant or points to that institution's
official site instead of using the old sample profile.

## Setup and run
```bash
python -m venv venv
venv\Scripts\activate          # Windows   (Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt

streamlit run app.py           # web app  -> http://localhost:8501
python cli.py                  # or the terminal version
python -m unittest discover -s tests -v    # run tests
```
`deep-translator` is only needed for languages other than English/Tamil/Hindi
and needs internet. The `ddgs` package provides live web search and also needs
internet. If search is unavailable, the assistant says the local directory
lacks the requested fact rather than returning sample figures.

## Deploy on Streamlit Community Cloud
1. Push this project to a GitHub repository. Do not commit `.venv`, chat logs,
    `.env`, or `.streamlit/secrets.toml`; the repository `.gitignore` excludes them.
2. Sign in at [share.streamlit.io](https://share.streamlit.io/) with GitHub and
    create an app from the repository's `main` branch, using `app.py` as the entrypoint.
3. In the app's **Settings → Secrets**, set `ADMIN_PASSWORD` to a private password
    before sharing the app. The default local password is `admin`.
4. Deploy. Streamlit Cloud installs dependencies from `requirements.txt`.

The app needs outbound internet for live search and optional translation. Its
CSV chat log is ephemeral on hosted instances, so do not use it for durable
analytics or collect sensitive student information.

## Chennai college directory
Edit `data/chennai_colleges.json` to add or update directory entries. The app
currently lists selected institutions and official website links; it does not
provide verified, college-specific fees or course/admissions data in the
directory. Check locations, links, and current details before presenting the
project publicly.

## Legacy single-college chatbot data
`data/college_data.json` contains sample data for the original single-college
assistant. Chennai directory mode does not use these placeholder facts.
1. `college` - name, phone, email, website, address, office hours (per language)
2. `facts` - fees, package figures, recruiters
3. `departments` - intake and focus areas
4. `intents` - answers and keywords for each topic

Add a new topic by copying an intent block, changing `id`, `keywords` and `answers`.
Placeholders such as `{phone}` and `{tuition_fee}` are filled automatically.

## Admin analytics
Every question is logged to `logs/chat_log.csv`. In the app sidebar, open
**Admin analytics** (default password `admin`; set your own with the
`ADMIN_PASSWORD` environment variable). The "Unanswered questions" list shows
what to add to the data file next.

## Possible extensions
- Voice input / text-to-speech (`SpeechRecognition`, `gTTS`)
- WhatsApp or Telegram bot using the same `CollegeAssistant.reply()` function
- Replace keyword matching with sentence embeddings (e.g. multilingual MiniLM)
- Student-specific answers (timetable, results) via a college database / login
