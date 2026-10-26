"""Terminal version of the assistant - no Streamlit needed.

Run with:   python cli.py
Commands:   /lang auto|en|ta|hi|te|ml|kn     /quit
"""

from chatbot import CollegeAssistant, Translator, LANGUAGES


def main() -> None:
    bot = CollegeAssistant(translator=Translator())
    lang = "auto"
    print(bot.welcome("en"))
    print("\n(type /lang ta to force Tamil, /lang hi for Hindi, /lang auto to follow your question, /quit to exit)\n")
    while True:
        try:
            q = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q.lower() in ("/quit", "/exit"):
            break
        if q.lower().startswith("/lang"):
            code = q.split(maxsplit=1)[1].strip().lower() if " " in q else ""
            if code == "auto" or code in LANGUAGES:
                lang = code
                print(f"Language set to: {code}\n")
            else:
                print("Use: /lang auto | " + " | ".join(LANGUAGES) + "\n")
            continue
        r = bot.reply(q, preferred=lang)
        print(f"\nBot [{r.lang}]: {r.text}")
        if r.notice:
            print(f"  ({r.notice})")
        print()


if __name__ == "__main__":
    main()
