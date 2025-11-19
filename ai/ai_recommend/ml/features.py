def build_features(df_mistakes):
    if "enrollment_id" not in df_mistakes.columns:
        if "enrollment" in df_mistakes.columns:
            # Đổi tên 'enrollment' (từ BE) thành 'enrollment_id' (cho AI pipeline)
            df_mistakes = df_mistakes.rename(columns={"enrollment": "enrollment_id"})
        else:
            # Nếu không có cả hai, báo lỗi cụ thể
            raise KeyError("Dữ liệu 'mistakes' từ BE không chứa cột 'enrollment_id' hoặc 'enrollment'.")
    features = (
        df_mistakes.groupby("enrollment_id")["score"]
        .agg(mistake_rate="mean", count="count")
        .reset_index()
    )
    return features.fillna(0)