# chat/serializers.py
from rest_framework import serializers
from languages.models import Topic
from chat.models import Conversation, Turn

class TopicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Topic
        fields = ['id','slug','title','description']

class TurnSerializer(serializers.ModelSerializer):
    class Meta:
        model = Turn
        fields = ['role','content','meta','created_at']

class ConversationSerializer(serializers.ModelSerializer):
    topic = TopicSerializer()
    turns = TurnSerializer(many=True)
    class Meta:
        model = Conversation
        fields = ['id','topic','roleplay','created_at','turns']

class StartPayloadSerializer(serializers.Serializer):
    topic_id = serializers.IntegerField(required=False)
    topic_slug = serializers.CharField(required=False)
    topic_title = serializers.CharField(required=False)
    language_override = serializers.CharField(required=False)
    mode = serializers.CharField(required=False, default='free')
    temperature = serializers.FloatField(required=False, default=0.7)
    max_tokens = serializers.IntegerField(required=False, default=512)
    suggestions_count = serializers.IntegerField(required=False, default=2)
    use_rag = serializers.BooleanField(required=False, default=False)
    knowledge_limit = serializers.IntegerField(required=False, default=3)
    roleplay_overrides = serializers.JSONField(required=False)

      # === NEW: params bổ sung ===
    # Neo theo Skill/Lesson (nếu muốn khoanh vùng nội dung)
    skill_title = serializers.CharField(required=False)     # ví dụ "Hello & Goodbye"
    lesson_id = serializers.IntegerField(required=False)    # id lesson cụ thể (ưu tiên nếu có)

    # Điều khiển RAG chi tiết
    rag_skill = serializers.CharField(required=False)       # filter RAG theo skill title
    rag_k = serializers.IntegerField(required=False, default=3, min_value=1, max_value=20)

    # Tùy biến system prompt
    system_extra = serializers.CharField(required=False, allow_blank=True)

    # Tên hiển thị (nếu bạn muốn đặt tên cuộc hội thoại — chỉ lưu trong roleplay/meta)
    conv_name = serializers.CharField(required=False, allow_blank=True)

class MessagePayloadSerializer(serializers.Serializer):
    conv_id = serializers.UUIDField()
    user_text = serializers.CharField()
