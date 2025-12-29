import difflib 

def _calculate_text_similarity(a, b):
    """Trả về độ giống nhau từ 0.0 đến 1.0"""
    return difflib.SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio()