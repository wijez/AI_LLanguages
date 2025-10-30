import base64, mimetypes
import json, base64, mimetypes, pathlib

path = r"D:\AI_LL\server\media\tts\3a86678323684a549e0a5339adde819f.mp3"  # .mp3/.ogg/.webm cũng được
mime = mimetypes.guess_type(path)[0] or "application/octet-stream"

with open(path, "rb") as f:
    b64 = base64.b64encode(f.read()).decode("utf-8")

# Chuỗi base64 thuần:
# print(b64)

# Chuỗi Data URL (tiện gửi JSON):
# data_url = f"data:{mime};base64,{b64}"
# print(data_url)
data = {
    "audio_base64": f"data:{mime};base64,{b64}",
    "target_text": "Hello world",
    "language_code": "en"
}
pathlib.Path("payload.json").write_text(json.dumps(data), encoding="utf-8")