import os
import joblib
import pandas as pd
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.utils.crypto import get_random_string

from ai_recommend.clients.be_client import BEClient
from ai_recommend.services.feature_and_rank import aggregate_from_be, _to_dt
from ai_recommend.services.rankers import rank_skills, rank_words
from ai_recommend.models import Recommendation, AIModelVersion
from ..auth.jwt_session import JWTSession

logger = logging.getLogger(__name__)

# --- Helper: Model Loading ---
def _load_latest_model_artifact():
    """
    Tìm và load file model .joblib mới nhất từ thư mục settings.MODEL_DIR.
    Trả về dict chứa {'model': ..., 'features': ...} hoặc None nếu không tìm thấy.
    """
    model_dir = getattr(settings, 'MODEL_DIR', 'models')
    if not os.path.exists(model_dir):
        return None

    try:
        # Lấy danh sách file .joblib
        files = [f for f in os.listdir(model_dir) if f.endswith('.joblib')]
        if not files:
            return None
        
        # Tìm file mới nhất dựa trên thời gian tạo
        latest_file = max(files, key=lambda f: os.path.getctime(os.path.join(model_dir, f)))
        path = os.path.join(model_dir, latest_file)
        
        # Load artifact (được dump từ trainer.py)
        artifact = joblib.load(path)
        logger.info(f"Loaded AI Model artifact: {latest_file}")
        return artifact
    except Exception as e:
        logger.error(f"Error loading AI model: {e}")
        return None

def _calculate_user_features(mistakes: List[Dict[str, Any]], skill_meta: Dict[int, Dict[str, Any]]) -> pd.DataFrame:
    """
    Tính toán input vector cho model AI.
    CẬP NHẬT: Thêm logic tính proficiency từ skill_meta để đồng bộ với features.py.
    Output cols: [avg_score, mistake_rate, count, avg_proficiency, total_system_xp]
    """
    # 1. Tính từ Mistakes (Historical Performance)
    scores = [float(m.get('score')) for m in mistakes if m.get('score') is not None]
    
    if not scores:
        # Giá trị mặc định cho user mới (Cold Start)
        data = {
            "avg_score": 0.5,
            "count": 0,
            "mistake_rate": 0.5
        }
    else:
        avg_score = sum(scores) / len(scores)
        data = {
            "avg_score": avg_score,
            "count": len(scores),
            "mistake_rate": 1.0 - avg_score
        }
    
    # 2. Tính từ Skill Meta (Current Proficiency State)
    # skill_meta cấu trúc: {skill_id: {'proficiency': 20.0, 'xp': 100, ...}}
    if skill_meta:
        # Lấy danh sách proficiency score hiện tại của tất cả skill user đã học
        profs = [float(m.get('proficiency', 0)) for m in skill_meta.values()]
        # Lấy tổng XP (nếu có trường xp trong skill_meta, API list_skill_stats cần trả về)
        xps = [int(m.get('xp', 0) if m.get('xp') is not None else 0) for m in skill_meta.values()]
        
        avg_prof = sum(profs) / len(profs) if profs else 0.0
        total_xp = sum(xps)
    else:
        avg_prof = 0.0
        total_xp = 0.0
        
    data["avg_proficiency"] = avg_prof
    data["total_system_xp"] = total_xp

    # Trả về DataFrame 1 dòng
    return pd.DataFrame([data])

# --- Main Service ---

def generate_recommendations_for_user(
    user_id: int,
    enrollment_id: int,
    language: str,
    top_k: int = 5,
    top_n_words: int = 10
) -> List[int]:
    """
    Quy trình Hybrid:
    1. Fetch dữ liệu từ Backend (Mistakes, Interactions, SkillStats).
    2. Chạy Heuristic (rankers.py) để lấy tập ứng viên (Candidate Generation).
    3. Chạy AI Model để dự đoán xác suất thành công dựa trên Features (Prediction).
    4. Kết hợp điểm (Re-ranking) và lưu DB.
    """
    
    # 1. SETUP KẾT NỐI BE
    jwt_sess = JWTSession(
        base_url=settings.BE_API_BASE_URL,            
        username=settings.BE_JWT_USERNAME,
        password=settings.BE_JWT_PASSWORD,
        token_url=getattr(settings, "BE_JWT_TOKEN_URL", "/api/token/"),
        refresh_url=getattr(settings, "BE_JWT_REFRESH_URL", "/api/token/refresh/"),
    )
    client = BEClient(base_url=settings.BE_API_BASE_URL, jwt_session=jwt_sess)

    # 2. FETCH DATA TỪ BE
    logger.info(f"Fetching data for User {user_id}, Enrollment {enrollment_id}...")
    try:
        mistakes = list(client.list_mistakes(user_id=user_id, language=language))
        interactions = list(client.list_interactions(user_id=user_id, language=language))
        
        # Skill Stats chứa thông tin về proficiency, xp, level...
        skill_meta: Dict[int, Dict[str, Any]] = {}
        for row in client.list_skill_stats(user_id=user_id, language=language):
            sid = row["skill_id"]
            skill_meta[sid] = {
                "level": row.get("level", 0),
                "proficiency": row.get("proficiency_score", 0.0),
                "xp": row.get("xp", 0), # Cần lấy thêm field này từ API BE
                "last_practiced": _to_dt(row.get("last_practiced")),
                "status": row.get("status", "available"),
                "needs_review": row.get("needs_review", False),
            }
    except Exception as e:
        logger.error(f"Failed to fetch data from Backend: {e}")
        return []

    # 3. AGGREGATE & HEURISTIC RANKING (CANDIDATE GENERATION)
    # Bước này luôn chạy để lọc ra các bài học khả thi nhất về mặt sư phạm
    mis_by_skill, acc_map, problem_lesson = aggregate_from_be(mistakes, interactions)

    # Lấy pool ứng viên lớn hơn top_k (gấp 3) để AI có không gian lựa chọn lại
    candidate_pool_size = top_k * 3
    skill_cands = rank_skills(mis_by_skill, acc_map, problem_lesson, skill_meta, top_k=candidate_pool_size)
    
    # Xử lý từ vựng (giữ nguyên logic heuristic vì chưa có AI cho từ vựng)
    word_cands = rank_words(mistakes, top_n=top_n_words)

    # 4. HYBRID RE-RANKING (AI INTEGRATION)
    
    model_artifact = _load_latest_model_artifact()
    model_used_record = None # Để lưu log DB xem dùng model nào
    
    # Cấu hình trọng số Hybrid
    # ALPHA: Trọng số cho điểm Heuristic (Sư phạm: Cần ôn tập, Hổng kiến thức)
    # BETA: Trọng số cho điểm AI (Khả năng: Xác suất hoàn thành bài học)
    ALPHA = 0.6  
    BETA = 0.4   

    if not model_artifact:
        logger.info("No AI model found. Using Heuristic ranking (Cold Start Mode).")
    else:
        try:
            logger.info("AI Model found. Applying Hybrid Re-ranking...")
            model = model_artifact["model"]
            feat_cols = model_artifact.get("features", [])
            
            # Lấy bản ghi model version từ DB để lưu vào Recommendation (Audit Trail)
            model_used_record = AIModelVersion.objects.order_by('-trained_at').first()

            # Tính features vector hiện tại của user (Input X)
            # Truyền cả mistakes và skill_meta để tính đầy đủ các chỉ số
            X_input = _calculate_user_features(mistakes, skill_meta)
            
            # Đảm bảo columns khớp với lúc train (thêm cột thiếu nếu cần - fill 0)
            for col in feat_cols:
                if col not in X_input.columns:
                    X_input[col] = 0.0
            
            # Predict Probability: Xác suất user sẽ học tốt/hoàn thành (Class 1)
            if hasattr(model, "predict_proba"):
                # predict_proba trả về [[prob_class_0, prob_class_1]]
                ai_prob = model.predict_proba(X_input[feat_cols])[0][1]
            else:
                # Fallback
                ai_prob = 0.5 

            logger.info(f"AI Prediction (Completion Probability): {ai_prob:.4f}")
            
            # Cập nhật điểm cho từng Skill Candidate
            for cand in skill_cands:
                # Chuẩn hóa điểm Heuristic (thường trong khoảng 0-2.0, đưa về thang [0, 1])
                norm_h_score = min(cand.score, 1.5) / 1.5
                
                # Công thức Hybrid
                hybrid_score = (ALPHA * norm_h_score) + (BETA * ai_prob)
                
                # Cập nhật thông tin để debug/hiển thị lý do
                cand.score = round(float(hybrid_score), 4)
                
                # Thêm lý do từ AI nếu xác suất quá cao hoặc quá thấp
                prob_percent = int(ai_prob * 100)
                if ai_prob > 0.8:
                    cand.reasons.insert(0, f"AI: Khả năng hoàn thành cao ({prob_percent}%)")
                elif ai_prob < 0.3:
                    cand.reasons.append(f"AI: Thử thách ({prob_percent}%)")
                
            # Sort lại danh sách sau khi tính điểm Hybrid (Cao xuống thấp)
            skill_cands.sort(key=lambda c: -c.score)
            
        except Exception as e:
            logger.warning(f"Failed to apply AI model prediction: {e}. Fallback to Heuristic order.")
            # Nếu AI lỗi, skill_cands vẫn giữ nguyên thứ tự Heuristic ban đầu.
    
    # Cắt lấy Top K cuối cùng sau khi đã Re-rank
    final_skill_cands = skill_cands[:top_k]

    # 5. LƯU XUỐNG DB (PERSISTENCE)
    batch_id = get_random_string(16)
    rec_ids: List[int] = []

    try:
        with transaction.atomic():
            # Lưu Skills
            for c in final_skill_cands:
                r = Recommendation.objects.create(
                    user_id=user_id,
                    enrollment_id=enrollment_id,
                    skill_id=c.skill_id,
                    lesson_id=c.lesson_id,
                    word_id=None,
                    rec_type=c.rec_type,         
                    reasons=c.reasons,          
                    language=language,            
                    batch_id=batch_id,           
                    priority_score=c.score,
                    model_used=model_used_record,
                )
                rec_ids.append(r.id)

            # Lưu Words
            for w in word_cands:
                r = Recommendation.objects.create(
                    user_id=user_id,
                    enrollment_id=enrollment_id,
                    skill_id=None,
                    lesson_id=None,
                    word_id=w.word_id,
                    rec_type='word',
                    reasons=w.reasons,
                    language=language,
                    batch_id=batch_id,
                    priority_score=w.score,
                    model_used=model_used_record,
                )
                rec_ids.append(r.id)
                
        logger.info(f"Generated {len(rec_ids)} recommendations for user {user_id}. Batch: {batch_id}")
    except Exception as e:
        logger.error(f"Error saving recommendations to DB: {e}")
        raise e

    return rec_ids