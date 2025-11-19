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
