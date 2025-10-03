import json
import zipfile
import os

# danh sách động từ (đã loại trùng)
verbs = list(dict.fromkeys([
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

def generate_forms(verb):
    forms = {
        "base": verb,
        "present_participle": verb + "ing",
        "past_simple": verb + "ed",
        "past_participle": verb + "ed",
        "third_person": verb + "s"
    }
    irregular = {
        "be": {"past_simple": "was", "past_participle": "been", "present_participle": "being", "third_person": "is"},
        "begin": {"past_simple": "began", "past_participle": "begun"},
        "buy": {"past_simple": "bought", "past_participle": "bought"},
        "come": {"past_simple": "came", "past_participle": "come"},
        "do": {"past_simple": "did", "past_participle": "done"},
        "drink": {"past_simple": "drank", "past_participle": "drunk"},
        "drive": {"past_simple": "drove", "past_participle": "driven"},
        "eat": {"past_simple": "ate", "past_participle": "eaten"},
        "find": {"past_simple": "found", "past_participle": "found"},
        "get": {"past_simple": "got", "past_participle": "gotten"},
        "go": {"past_simple": "went", "past_participle": "gone"},
        "have": {"past_simple": "had", "past_participle": "had"},
        "keep": {"past_simple": "kept", "past_participle": "kept"},
        "know": {"past_simple": "knew", "past_participle": "known"},
        "leave": {"past_simple": "left", "past_participle": "left"},
        "make": {"past_simple": "made", "past_participle": "made"},
        "run": {"past_simple": "ran", "past_participle": "run"},
        "say": {"past_simple": "said", "past_participle": "said"},
        "see": {"past_simple": "saw", "past_participle": "seen"},
        "take": {"past_simple": "took", "past_participle": "taken"},
        "write": {"past_simple": "wrote", "past_participle": "written"}
    }
    if verb in irregular:
        forms.update(irregular[verb])
    return forms

words = []
relations = []
seen = set()

for v in verbs:
    forms = generate_forms(v)
    base = forms["base"]

    if ("en", base.lower()) not in seen:
        words.append({
            "language": "en",
            "text": base,
            "normalized": base.lower(),
            "part_of_speech": "verb"
        })
        seen.add(("en", base.lower()))

    for rel_type, form in forms.items():
        if rel_type == "base":
            continue

        if ("en", form.lower()) not in seen:
            words.append({
                "language": "en",
                "text": form,
                "normalized": form.lower(),
                "part_of_speech": "verb"
            })
            seen.add(("en", form.lower()))

        relations.append({
            "relation_type": rel_type,
            "language": "en",
            "word_text": base,
            "related_text": form
        })

# save
os.makedirs("D:/AI_LL/dataset/verbs_dataset", exist_ok=True)

with open("D:/AI_LL/dataset/verbs_dataset/words.json", "w", encoding="utf-8") as f:
    json.dump(words, f, indent=2, ensure_ascii=False)

with open("D:/AI_LL/dataset/verbs_dataset/words_relations.json", "w", encoding="utf-8") as f:
    json.dump(relations, f, indent=2, ensure_ascii=False)

print("✅ Exported words.json & words_relations.json")
