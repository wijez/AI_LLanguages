def build_features(df_mistakes):
    """
    Chuyển đổi dữ liệu raw mistakes từ BE thành bảng Features cho AI.
    Input: DataFrame chứa các cột [enrollment_id, score, ...]
    Output: DataFrame [enrollment_id, avg_score, mistake_rate, count]
    """
    if "enrollment_id" not in df_mistakes.columns:
        if "enrollment" in df_mistakes.columns:
            # Đổi tên 'enrollment' (từ BE) thành 'enrollment_id' (cho AI pipeline)
            df_mistakes = df_mistakes.rename(columns={"enrollment": "enrollment_id"})
        else:
            # Nếu không có cả hai, báo lỗi cụ thể
            raise KeyError("Dữ liệu 'mistakes' từ BE không chứa cột 'enrollment_id' hoặc 'enrollment'.")
    features = (
        df_mistakes.groupby("enrollment_id")["score"]
        .agg(avg_score="mean", count="count")
        .reset_index()
    )
    features["mistake_rate"] = 1.0 - features["avg_score"]
    fill_values = {
        "avg_score": 0.0,
        "count": 0,
        "mistake_rate": 1.0
    }   
    return features.fillna(value=fill_values)