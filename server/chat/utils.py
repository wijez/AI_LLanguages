import random

SYSTEM_TEMPLATE = (
    "Bạn là trợ giảng thân thiện. Chủ đề: {topic}.\n"
    "Chế độ: roleplay. Vai: trợ giảng.\n"
    "Ngôn ngữ: {lang}.\n"
    "Nguyên tắc: bám sát chủ đề, trả lời ngắn + hỏi lại, đề xuất 2–3 gợi ý."
)

SUGGESTION_POOL = [
    "Bạn muốn đi sâu phần nào tiếp?",
    "Bạn có ví dụ cụ thể không?",
    "Muốn luyện tập thêm không?",
    "Bạn thử đọc lại câu vừa rồi nhé?",
]

def make_system_turn(topic_title:str, lang:str='vi'):
    return SYSTEM_TEMPLATE.format(topic=topic_title, lang=lang)

def simple_reply(topic_title:str, user_text:str|None):
    # Trả lời rất đơn giản theo topic A1 greetings
    pref = "Hãy luyện chào hỏi nào. "
    ask = "Bạn thử nói: “Hello, nice to meet you.”"
    if user_text:
        pref = "Cảm ơn bạn. "
    reply = f"{pref}Bạn đã biết cách nói 'Hello' chưa?\n\n2 gợi ý để bắt đầu:\n" \
            f"1) Bạn đọc: “Hello!”\n2) Bạn đọc: “Nice to meet you.”\n\n{ask}"
    suggestions = random.sample(SUGGESTION_POOL, k=3)
    return reply, suggestions



def _format_rag_snippet(hits, max_items=3, max_len=350) -> str:
    out = []
    for i, h in enumerate((hits or [])[:max_items], start=1):
        txt = (h.get("text") or "").strip()
        if len(txt) > max_len:
            txt = txt[:max_len].rsplit(" ", 1)[0] + "…"
        m = h.get("meta") or {}
        tag = f"{m.get('topic_slug','?')} / L{m.get('lesson_order','?')} / {m.get('skill_title','?')}"
        out.append(f"[{i}] ({h.get('score',0):.3f}) {tag}: {txt}")
    return "\n".join(out)