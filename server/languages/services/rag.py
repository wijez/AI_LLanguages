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
        RoleplayBlock.objects.exclude(embedding__isnull=True)
        .exclude(section='dialogue') 
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
    "You are an expert English Tutor interacting with a student in a roleplay scenario. "
    "Your tasks are:\n"
    "1. MAINTAIN THE ROLEPLAY: Respond naturally to the student's input based on the scenario context.\n"
    "2. TEACHER MODE: Analyze the student's input for grammatical errors, unnatural phrasing, or vocabulary mistakes.\n"
    "3. OUTPUT FORMAT: You must return a valid JSON object with the following keys:\n"
    "   - 'reply': Your spoken response to the student (keep it natural, spoken style, 1-2 sentences).\n"
    "   - 'corrected': The corrected version of the student's input. If the student's input was perfect, return null.\n"
    "   - 'explanation': A very brief (1 sentence) explanation of the error (e.g., 'Wrong tense', 'Unnatural word choice'). If no error, return null.\n"
    "\n"
    "Example JSON:\n"
    "{ \"reply\": \"That sounds fun!\", \"corrected\": \"I went to the beach.\", \"explanation\": \"Use past tense 'went' instead of 'go'.\" }"
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


def ask_gemini_chat(system_context: str, history: list, new_user_input: str) -> dict:
    """
    Trả về dict: { "reply": str, "corrected": str|None, "explanation": str|None }
    """
    if not os.getenv("GEMINI_API_KEY"): 
        return {"reply": "AI service not configured.", "corrected": None}

    # Cấu hình Model
    # Dùng system_instruction để ép khuôn JSON mạnh hơn
    model = genai.GenerativeModel(GEMINI_MODEL, system_instruction=SYS_PRACTICE)
    
    # Chuẩn bị chat history cho SDK
    # Lưu ý: SDK google.generativeai yêu cầu history có format 'user'/'model' và 'parts'
    # Bạn cần đảm bảo history truyền vào đúng format này.
    
    # Nếu history rỗng, ghép Context vào input đầu
    if not history:
        final_input = f"CONTEXT:\n{system_context}\n\nSTUDENT SAYS: {new_user_input}"
        chat = model.start_chat(history=[])
    else:
        final_input = f"STUDENT SAYS: {new_user_input}"
        chat = model.start_chat(history=history)

    try:
        # Ép Gemini trả về JSON mode (nếu model hỗ trợ) hoặc prompt text
        response = chat.send_message(
            final_input,
            generation_config={"response_mime_type": "application/json"} # Gemini 1.5 hỗ trợ cái này
        )
        
        raw_text = response.text.strip()
        
        # Parse JSON
        try:
            data = json.loads(raw_text)
            return data # {reply, corrected, explanation}
        except json.JSONDecodeError:
            # Fallback nếu AI lỡ trả về text thường
            log.warning("Gemini did not return JSON")
            return {"reply": raw_text, "corrected": None, "explanation": None}

    except Exception as e:
        log.error(f"Gemini Chat Error: {e}")
        return {"reply": "Sorry, I encountered an error.", "corrected": None}