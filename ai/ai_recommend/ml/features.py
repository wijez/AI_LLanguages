import pandas as pd

def build_features(df_mistakes, df_skill_stats=None):
    """
    Chuyển đổi dữ liệu thô từ BE thành bảng Features cho AI.
    
    Args:
        df_mistakes: DataFrame [enrollment_id, score, ...]
        df_skill_stats: DataFrame [enrollment_id, proficiency_score, xp, ...] (MỚI)
        
    Output: 
        DataFrame [enrollment_id, avg_score, mistake_rate, count, avg_proficiency, total_xp]
    """
    if "enrollment_id" not in df_mistakes.columns:
        if "enrollment" in df_mistakes.columns:
            df_mistakes = df_mistakes.rename(columns={"enrollment": "enrollment_id"})
        else:
            # Nếu không có data mistakes, tạo khung rỗng để tránh lỗi
            df_mistakes = pd.DataFrame(columns=["enrollment_id", "score"])

    if not df_mistakes.empty:
        features = (
            df_mistakes.groupby("enrollment_id")["score"]
            .agg(avg_score="mean", count="count")
            .reset_index()
        )
        features["mistake_rate"] = 1.0 - features["avg_score"]
    else:
        features = pd.DataFrame(columns=["enrollment_id", "avg_score", "count", "mistake_rate"])

    # 2. Xử lý Skill Stats (Proficiency)
    if df_skill_stats is not None and not df_skill_stats.empty:
        if "enrollment_id" not in df_skill_stats.columns and "enrollment" in df_skill_stats.columns:
            df_skill_stats = df_skill_stats.rename(columns={"enrollment": "enrollment_id"})
            
        prof_features = (
            df_skill_stats.groupby("enrollment_id")
            .agg(
                avg_proficiency=("proficiency_score", "mean"),
                total_system_xp=("xp", "sum") 
            )
            .reset_index()
        )
        
        # Merge vào bảng features chính
        # Dùng 'outer' để giữ cả user có mistakes nhưng chưa có skill_stats (hiếm) hoặc ngược lại
        features = features.merge(prof_features, on="enrollment_id", how="outer")
    else:
        features["avg_proficiency"] = 0.0
        features["total_system_xp"] = 0.0

    fill_values = {
        "avg_score": 0.5,       # Giả định trung bình nếu chưa có dữ liệu
        "count": 0,
        "mistake_rate": 0.5,
        "avg_proficiency": 0.0, # Mới bắt đầu = 0
        "total_system_xp": 0.0
    }
    
    return features.fillna(value=fill_values)