from rest_framework import serializers
from .models import Conversation, Turn
from languages.models import Topic
from languages.serializers import TopicSerializer

class TurnSerializer(serializers.ModelSerializer):
    class Meta:
        model = Turn
        fields = ['role','content','meta','created_at']

class ConversationSerializer(serializers.ModelSerializer):
    topic = TopicSerializer()
    class Meta:
        model = Conversation
        fields = [
            'id','topic','use_rag','max_tokens','temperature',
            'knowledge_limit','suggestions_count','created_at'
        ]

# --- Requests
class StartRequestSerializer(serializers.Serializer):
    topic_slug = serializers.SlugField()
    mode = serializers.CharField(default='roleplay')
    temperature = serializers.FloatField(required=False, default=0.4)
    max_tokens = serializers.IntegerField(required=False, default=300)
    suggestions_count = serializers.IntegerField(required=False, default=2)
    use_rag = serializers.BooleanField(required=False, default=True)
    knowledge_limit = serializers.IntegerField(required=False, default=3)
    rag_skill = serializers.CharField(required=False, allow_blank=True)
    rag_k = serializers.IntegerField(required=False, default=5)
    skill_title = serializers.CharField(required=False, allow_blank=True)
    system_extra = serializers.CharField(required=False, allow_blank=True)
    language_override = serializers.CharField(required=False, default='vi')
    conv_name = serializers.CharField(required=False, allow_blank=True)

class MessageRequestSerializer(serializers.Serializer):
    conv_id = serializers.UUIDField()
    user_text = serializers.CharField(allow_blank=True, allow_null=True, required=False, default='')
    expect_text = serializers.CharField(required=False, allow_blank=True, default='')
    force_pron  = serializers.BooleanField(required=False, default=False)
    
# --- Responses
class StartResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(source='conversation.id')
    topic = TopicSerializer()
    roleplay = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(source='conversation.created_at')
    turns = TurnSerializer(many=True)

    def get_roleplay(self, obj):
        c = obj['conversation']
        return {
            'temperature': c.temperature,
            'max_tokens': c.max_tokens,
            'suggestions_count': c.suggestions_count,
            'use_rag': c.use_rag,
            'knowledge_limit': c.knowledge_limit,
        }

class MessageResponseSerializer(serializers.Serializer):
    reply = serializers.CharField()
    meta = serializers.DictField()
    conversation = ConversationSerializer()
