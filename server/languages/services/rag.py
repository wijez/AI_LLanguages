import json
import os, logging
from typing import Optional
from django.db.models import F
from pgvector.django import CosineDistance
from languages.models import RoleplayBlock
from .ollama_client import embed_one
import google.generativeai as genai
log = logging.getLogger(__name__)

def retrieve_blocks(q_text: str, top_k=8, scenario_slug: Optional[str] = None):
    q_vec = embed_one(q_text)
    qs = (
        # RoleplayBlock.objects.exclude(embedding__isnull=True)
        # .exclude(section='dialogue') 
        RoleplayBlock.objects
        .filter(scenario__slug=scenario_slug)       # Chỉ tìm trong bài học hiện tại
        .exclude(embedding__isnull=True)            # Bỏ qua block chưa có vector
        .annotate(score=CosineDistance("embedding", q_vec)) # So khớp vector
        .order_by("score")                          # Xếp theo độ tương đồng (thấp nhất là giống nhất với CosineDistance)
        [:top_k]
    )
    if scenario_slug: qs = qs.filter(scenario__slug=scenario_slug)
    return (qs.annotate(score=CosineDistance("embedding", q_vec))
             .order_by("score")[:top_k])


GEMINI_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash")
if os.getenv("GEMINI_API_KEY"): genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

SYS = ("You are a helpful and friendly English tutor. "
       "You will be provided with CONTEXT from a roleplay scenario. This CONTEXT includes background, instructions, warmup exercises, and vocabulary lists. "
       "Your main goal is to answer the user's questions naturally, like a real tutor. "
       
       "You MUST follow these rules: "
       "1. Base your answers ONLY on the provided CONTEXT. Do not use any external knowledge. "
       "2. The CONTEXT defines the entire topic. Do not answer questions that are off-topic. "
       "3. If the answer cannot be found in the CONTEXT, you MUST politely say: 'I'm sorry, I don't have that information in the current scenario.' "
       "4. Keep your responses encouraging and conversational.")

SYS_PRACTICE = (
    "You are an expert English Tutor interacting with a student in a roleplay scenario.\n"
    "Your Goal: Help the student practice speaking English naturally while maintaining the flow of conversation.\n\n"
    
    "=== CRITICAL INSTRUCTIONS ===\n"
    "1. DUAL MINDSET (Hai tư duy song song):\n"
    "   - As a TEACHER: Check the user's input for errors. Put corrections in 'corrected' and 'explanation'.\n"
    "   - As a ROLEPLAY CHARACTER: You MUST respond to the MEANING of the user's input. Put this in 'reply'.\n\n"

    "2. THE 'REPLY' FIELD (STRICT RULES):\n"
    "   - This is the conversational response.\n"
    "   - DO NOT say 'Good job', 'Nice try', or talk about grammar here.\n"
    "   - IF USER ASKS A QUESTION: You MUST answer it based on the Scenario Context.\n"
    "   - IF USER MAKES A STATEMENT: You MUST respond relevantly and ask a follow-up question to keep the chat going.\n"
    "   - Language: ALWAYS English.\n\n"

    "3. THE 'EXPLANATION' FIELD:\n"
    "   - Use the student's support language (if provided in context) to explain errors.\n"
    "   - Keep it brief.\n\n"
    
    "=== OUTPUT FORMAT (JSON) ===\n"
    "{\n"
    "  \"reply\": \"(String) Your in-character response. E.g., 'Level one is mild spice, mostly just flavor.'\",\n"
    "  \"reply_trans\": \"(String) Translation of your response into the Support Language (e.g., Vietnamese).\",\n"
    "  \"corrected\": \"(String or Null) The corrected version of user input.\",\n"
    "  \"explanation\": \"(String or Null) Grammar explanation in support language.\"\n"
    "}"
)
def ask_gemini(query: str, blocks) -> str:
    if not os.getenv("GEMINI_API_KEY"): return ""
    ctx = "\n".join([f"[{b.section}#{b.order}] {b.role or '-'}: {b.text}" for b in blocks])
    prompt = f"""<DIALOGUE_CONTEXT>
    {ctx}
    </DIALOGUE_CONTEXT>
    USER: {query}
    """
    m = genai.GenerativeModel(GEMINI_MODEL, system_instruction=SYS)
    try:
        response = m.generate_content(
            prompt,
            safety_settings={
                'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_MEDIUM_AND_ABOVE',
                'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_MEDIUM_AND_ABOVE',
                'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_MEDIUM_AND_ABOVE',
                'HARM_CATEGORY_HARASSMENT': 'BLOCK_MEDIUM_AND_ABOVE',
            }
        )
        
        # Kiểm tra xem response có bị block không
        if response.prompt_feedback.block_reason:
            log.warning(f"Gemini prompt blocked. Reason: {response.prompt_feedback.block_reason}")
            return "I am sorry, I cannot respond to that query."
            
        return (response.text or "").strip()
    
    except Exception as e:
        log.error(f"Gemini API call failed: {e}")
        return "I'm sorry, an error occurred with the AI service. Please try again."


def ask_gemini_chat(
    system_instructions: str, 
    history: list, 
    new_user_input: str, 
    scenario_slug: Optional[str] = None
) -> dict:
    if not os.getenv("GEMINI_API_KEY"): 
        return {"reply": "AI service not configured.", "corrected": None}

    # 1. RAG Retrieve (Giữ nguyên)
    rag_context = ""
    if scenario_slug:
        try:
            relevant_blocks = retrieve_blocks(new_user_input, top_k=3, scenario_slug=scenario_slug)
            if relevant_blocks:
                block_texts = [f"- {b.embedding_text or b.text}" for b in relevant_blocks]
                rag_context = "\nDETAILS FOUND IN SCENARIO:\n" + "\n".join(block_texts) + "\n"
        except Exception as e:
            log.warning(f"RAG Retrieval failed: {e}")

    # 2. [QUAN TRỌNG] Kết hợp SYS_PRACTICE (Luật) + system_instructions (Dữ liệu bài học)
    # SYS_PRACTICE đứng đầu để định hình hành vi (System Prompt)
    combined_system_prompt = f"{SYS_PRACTICE}\n\n=== CURRENT SCENARIO INFO ===\n{system_instructions}"

    # 3. Prompt User
    final_user_prompt = f"{rag_context}\nSTUDENT SAYS: {new_user_input}"

    # Khởi tạo model với Prompt gộp
    model = genai.GenerativeModel(os.getenv("GEMINI_MODEL"), system_instruction=combined_system_prompt)
    
    if not history:
        chat = model.start_chat(history=[])
    else:
        chat = model.start_chat(history=history)

    try:
        response = chat.send_message(
            final_user_prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text.strip())
    except Exception as e:
        log.error(f"Gemini Chat Error: {e}")
        return {"reply": "Sorry, I encountered an error.", "corrected": None, "explanation": None}