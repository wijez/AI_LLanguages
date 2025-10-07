import random

def _rand_score(a=70, b=95):
    return round(random.uniform(a, b), 1)

def score_audio_stub(wav_file, target_text:str, lang='en'):
    """
    Trả về cấu trúc điểm giả lập theo format đã thống nhất.
    Thay thế bằng tích hợp ASR + forced alignment + GOP khi có model thật.
    """
    words = []
    tokens = [w.strip(",.!?") for w in target_text.split()]
    t = 0
    for i, w in enumerate(tokens):
        dur = random.randint(200, 500)
        word_score = _rand_score()
        words.append({
            "idx": i,
            "text": w,
            "start_ms": t,
            "end_ms": t + dur,
            "score": word_score,
            "error": "ok" if word_score >= 75 else random.choice(["sub","del","ins"]),
            "note": "Nhấn âm đầu" if i == 0 else "",
            "phonemes": [
                {
                    "symbol": "p{}".format(i),
                    "start_ms": t,
                    "end_ms": t + dur//2,
                    "score": _rand_score(),
                    "error": "ok",
                    "note": ""
                },
                {
                    "symbol": "v{}".format(i),
                    "start_ms": t + dur//2,
                    "end_ms": t + dur,
                    "score": _rand_score(),
                    "error": "ok",
                    "note": ""
                }
            ]
        })
        t += dur + random.randint(30, 120)

    scores = {
        "overall": _rand_score(),
        "pronunciation": _rand_score(),
        "fluency": _rand_score(),
        "completeness": _rand_score(),
        "prosody": _rand_score(),
        "wer": round(random.uniform(0.05, 0.25), 2),
        "cer": round(random.uniform(0.03, 0.15), 2)
    }
    suggestions = [
        "Mở khẩu hình hơn ở nguyên âm dài.",
        "Bật phụ âm cuối rõ hơn.",
        "Giữ nhịp đều, tránh ngắt quãng."
    ]

    return scores, words, suggestions
