import json
import os
from deep_translator import GoogleTranslator

verbs = verbs = list(dict.fromkeys([
    "accept", "add", "allow", "ask", "be", "become", "begin", "believe", "bring", "build",
    "buy", "call", "can", "choose", "come", "consider", "continue", "create", "cut", "decide",
    "develop", "do", "draw", "drive", "eat", "enable", "expect", "explain", "fall", "feel",
    "find", "finish", "follow", "get", "give", "go", "grow", "happen", "have", "hear",
    "help", "hold", "hope", "imagine", "improve", "include", "increase", "indicate", "inform", "introduce",
    "keep", "know", "learn", "leave", "let", "like", "listen", "live", "look", "lose",
    "love", "make", "manage", "mean", "meet", "move", "need", "offer", "open", "organize",
    "pay", "play", "prepare", "produce", "promise", "provide", "put", "read", "receive", "remember",
    "report", "require", "return", "run", "say", "see", "seem", "sell", "send", "set",
    "show", "sit", "speak", "spend", "stand", "start", "stay", "stop", "study", "succeed",
    "suggest", "support", "take", "talk", "teach", "tell", "think", "travel", "try", "turn",
    "understand", "use", "wait", "walk", "want", "watch", "win", "work", "write", "achieve",
    "adapt", "affect", "analyze", "argue", "arrive", "assume", "attend", "avoid", "belong", "break",
    "compare", "complain", "contribute", "convince", "cope", "deliver", "deny", "discover", "encourage", "establish",
    "examine", "exist", "explore", "express", "face", "fail", "handle", "identify", "imply", "influence",
    "insist", "invest", "involve", "judge", "maintain", "measure", "mention", "notice", "obtain",
    "occur", "perform", "prefer", "prevent", "protect", "prove", "realize", "recognize", "recommend", "reduce",
    "reflect", "refuse", "relate", "replace", "respond", "result", "reveal", "separate", "share",
    "solve", "suffer", "survive", "test", "train", "transform", "value", "warn", "wonder",
    "agree", "disagree", "compete", "debate", "criticize", "defend", "oppose", "persuade", "negotiate",
    "clarify", "summarize", "interpret", "translate", "predict", "anticipate", "conclude", "demonstrate", "illustrate", "emphasize",
    "highlight", "underline", "stress", "overcome", "dominate", "emerge", "adopt", "assess", "calculate",
    "classify", "categorize", "confirm", "determine", "distinguish", "evaluate", "exceed", "fulfill", "justify", "validate"
]))

translator = GoogleTranslator(source="en", target="vi")

translations = []
for verb in verbs:
    try:
        vi_word = translator.translate(verb)
    except Exception as e:
        print(f"⚠️ Error translating {verb}: {e}")
        vi_word = verb  # fallback giữ nguyên

    example = ""
    translations.append({
        "source_text": verb,
        "translated_text": vi_word,
        "example": example,
        "source_language": "en",
        "target_language": "vi"
    })

os.makedirs("D:/AI_LL/dataset/verbs_dataset", exist_ok=True)
with open("D:/AI_LL/dataset/verbs_dataset/translations.json", "w", encoding="utf-8") as f:
    json.dump(translations, f, indent=2, ensure_ascii=False)

print("✅ Exported translations.json with Deep Translator")
