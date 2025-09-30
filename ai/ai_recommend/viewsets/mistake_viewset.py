from rest_framework import viewsets
from ..models import Mistake
from ..serializers import (
    MistakeSerializer,
)


class MistakeViewSet(viewsets.ModelViewSet):
    queryset = Mistake.objects.all().order_by('-timestamp')
    serializer_class = MistakeSerializer
