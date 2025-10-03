def build_features(df_mistakes):
    features = (
        df_mistakes.groupby("enrollment_id")["score"]
        .agg(mistake_rate="mean", count="count")
        .reset_index()
    )
    return features.fillna(0)