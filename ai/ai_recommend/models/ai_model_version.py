from django.db import models
from django.utils import timezone

class AIModelVersion(models.Model):
    name = models.CharField(max_length=100)
    version = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    trained_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} v{self.version}"


class TrainingRun(models.Model):
    STATUS_CHOICES = [
        ("pending", "pending"),
        ("running", "running"),
        ("succeeded", "succeeded"),
        ("failed", "failed"),
    ]

    model = models.ForeignKey(AIModelVersion, on_delete=models.CASCADE, related_name='training_runs')
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    parameters = models.JSONField(blank=True, null=True)         # hyperparams
    metrics = models.JSONField(blank=True, null=True)            # e.g. rmse, map@k
    dataset_snapshot = models.CharField(max_length=255, blank=True)  # optional: path to parquet/csv

    class Meta:
        ordering = ['-started_at']


class FeatureSnapshot(models.Model):
    """Tùy chọn: lưu feature đã dùng để train/serve (để audit/repro)."""
    model = models.ForeignKey(AIModelVersion, on_delete=models.CASCADE, related_name='feature_snapshots')
    created_at = models.DateTimeField(auto_now_add=True)
    spec = models.JSONField()  # định nghĩa feature, schema, versioning
    storage_path = models.CharField(max_length=255, blank=True)  # nơi lưu (parquet/feature store)
