from django.utils import timezone
from django.db import models
from users.models import User
import uuid
from django.utils.text import slugify
from pgvector.django import VectorField

class Language(models.Model):
    name = models.CharField(max_length=100)
    abbreviation = models.CharField(max_length=10, unique=True)
    native_name = models.CharField(max_length=100, blank=True)
    direction = models.CharField(max_length=3, default='LTR')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.abbreviation})"


class LanguageEnrollment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='enrollments')
    language = models.ForeignKey(Language, on_delete=models.CASCADE, related_name='enrollments')
    level = models.IntegerField(default=0)
    total_xp = models.IntegerField(default=0)
    streak_days = models.IntegerField(default=0)
    last_practiced = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'language'], name='uq_enrollment_user_language')
        ]
        indexes = [models.Index(fields=['user', 'language'])]


class Topic(models.Model):
    language = models.ForeignKey(Language, on_delete=models.CASCADE, related_name='topics')
    slug = models.SlugField(max_length=150)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    order = models.IntegerField(default=0)
    golden = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    embedding = VectorField(dimensions=768, null=True, blank=True)
    embedding_text = models.TextField(blank=True)
    embedding_updated_at = models.DateTimeField(null=True, blank=True)
    embedding_hash = models.CharField(max_length=64, blank=True, default="")
    embedding_model = models.CharField(max_length=100, blank=True, default="")


    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['language', 'slug'], name='uq_topic_language_slug')
        ]
        ordering = ['order']
        indexes = [models.Index(fields=['language', 'order'])]

    def __str__(self):
        return f'{self.title}({self.language})'


class TopicProgress(models.Model):
    enrollment = models.ForeignKey(LanguageEnrollment, on_delete=models.CASCADE, related_name='topic_progress')
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE)
    highest_completed_order = models.IntegerField(default=0)
    completed = models.BooleanField(default=False)
    xp = models.IntegerField(default=0)
    last_seen = models.DateTimeField(null=True, blank=True)
    reviewable = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['enrollment', 'topic'], name='uq_topicprogress_enrollment_topic')
        ]
        indexes = [models.Index(fields=['enrollment', 'completed', 'reviewable'])]


class Skill(models.Model):
    class SkillType(models.TextChoices):
        LISTENING = "listening", "Listening"
        SPEAKING  = "speaking",  "Speaking"
        READING   = "reading",   "Reading"
        WRITING   = "writing",   "Writing"
        MATCHING  = "matching",  "Matching"   # ghép từ / nối cặp
        FILLGAP   = "fillgap",   "Fill in the blanks"
        ORDERING  = "ordering",  "Reorder words"
        QUIZ      = "quiz",      "Generic MCQ/QA"
        PRON      = "pron",      "Pronunciation"

    title = models.CharField(max_length=255)
    type = models.CharField(max_length=32, choices=SkillType.choices,  default=SkillType.QUIZ)
    xp_reward = models.IntegerField(default=10)
    duration_seconds = models.IntegerField(default=90)
    difficulty = models.PositiveSmallIntegerField(default=1)  
    title_i18n = models.JSONField(default=dict, blank=True)         
    description_i18n = models.JSONField(default=dict, blank=True)
    language_code = models.CharField(max_length=10, default="en")   

    # Metadata
    tags = models.JSONField(default=list, blank=True)  # ["A1","greetings"]
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["type"]), models.Index(fields=["language_code"])]

    def __str__(self):
        return f"{self.title} [{self.type}]"
    
    def get_title(self, locale: str):
        return (self.title_i18n or {}).get(locale) or self.title

class SkillQuestion(models.Model):
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="quiz_questions")
    question_text = models.TextField() 
    question_text_i18n = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"QuizQuestion({self.id}) for Skill({self.skill_id})"


class SkillChoice(models.Model):
    question = models.ForeignKey(SkillQuestion, on_delete=models.CASCADE, related_name="choices")
    text = models.CharField(max_length=255)         # nội dung phương án lựa chọn
    is_correct = models.BooleanField(default=False) # đánh dấu đâu là đáp án đúng

    def __str__(self):
        return f"Choice({self.text[:20]}) for Question({self.question_id})"

# --- Model cho loại Fill in the Gap (Điền vào chỗ trống) ---
class SkillGap(models.Model):
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="fillgaps")
    text = models.TextField()    # câu văn với chỗ trống, có thể dùng ký hiệu đặc biệt để đánh dấu vị trí chỗ trống
    answer = models.CharField(max_length=255)  # đáp án đúng điền vào chỗ trống

    def __str__(self):
        return f"FillGap({self.id}) for Skill({self.skill_id})"

class OrderingItem(models.Model):
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="ordering_items")
    text = models.CharField(max_length=255)   # nội dung của 1 mảnh (từ/cụm từ) cần sắp xếp
    order_index = models.IntegerField()       # vị trí đúng trong thứ tự (bắt đầu từ 1 hoặc 0 tùy ý quy ước)

    def __str__(self):
        return f"OrderingItem({self.text}) order={self.order_index} for Skill({self.skill_id})"

class MatchingPair(models.Model):
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="matching_pairs")
    left_text = models.CharField(max_length=255)   # nội dung bên trái của cặp
    right_text = models.CharField(max_length=255)  
    left_text_i18n = models.JSONField(default=dict, blank=True) # nội dung bên phải tương ứng (đáp án đúng của left_text)

    def __str__(self):
        return f"MatchingPair({self.left_text} - {self.right_text}) for Skill({self.skill_id})"

class ListeningPrompt(models.Model):
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="listening_prompts")
    audio_url = models.URLField(blank=True, null=True)   
    # audio_file = models.FileField(..., blank=True, null=True)
    question_text = models.CharField(max_length=255, blank=True)
    answer = models.CharField(max_length=255)      


    def __str__(self):
        return f"ListeningPrompt({self.id}) for Skill({self.skill_id})"

# --- Model cho loại Pronunciation (Phát âm) ---
class PronunciationPrompt(models.Model):
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="pronunciation_prompts")
    word = models.CharField(max_length=100)        # từ hoặc cụm từ cần phát âm
    phonemes = models.CharField(max_length=100, blank=True)  # phiên âm hoặc chú thích phát âm (nếu có)
    answer = models.CharField(max_length=100, blank=True)   

    def __str__(self):
        return f"PronunciationPrompt({self.word}) for Skill({self.skill_id})"

class ReadingContent(models.Model):
    skill = models.OneToOneField(Skill, on_delete=models.CASCADE, related_name="reading_content")
    passage = models.TextField()   # đoạn văn hoặc nội dung cần đọc

    def __str__(self):
        return f"ReadingContent for Skill({self.skill_id})"

class ReadingQuestion(models.Model):
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="reading_questions")
    question_text = models.TextField() 
    answer = models.CharField(max_length=255)      
  

    def __str__(self):
        return f"ReadingQuestion({self.id}) for Skill({self.skill_id})"

class WritingQuestion(models.Model):
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="writing_questions")
    prompt = models.TextField()   # đề bài hoặc câu hỏi yêu cầu viết
    answer = models.CharField(max_length=255)  
    def __str__(self):
        return f"WritingQuestion({self.id}) for Skill({self.skill_id})"

class SpeakingPrompt(models.Model):
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="speaking_prompts")
    text = models.CharField(max_length=255)     # hiển thị cho học viên
    target = models.CharField(max_length=255)   # câu cần nói đúng
    tip = models.CharField(max_length=255, blank=True)

class Lesson(models.Model):
    topic = models.ForeignKey("Topic", on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=255)
    content = models.JSONField(null=True, blank=True)  # optional: mô tả chung
    order = models.IntegerField(default=0)
    xp_reward = models.IntegerField(default=10)
    duration_seconds = models.IntegerField(default=120)

    # Liên kết N–N tới skill (có thứ tự hiển thị trong 1 lesson)
    skills = models.ManyToManyField(Skill, related_name="lessons", through="LessonSkill")

    class Meta:
        ordering = ["order", "id"]
        indexes = [models.Index(fields=["topic", "order"])]

    def __str__(self):
        return self.title


class LessonSkill(models.Model):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE)
    skill  = models.ForeignKey(Skill, on_delete=models.CASCADE)
    order  = models.IntegerField(default=0)

    class Meta:
        unique_together = ("lesson", "skill")
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["lesson", "order"]),
            models.Index(fields=["skill", "order"]),
        ]

    def __str__(self):
        return f"{self.lesson} ↔ {self.skill} (#{self.order})"



class UserSkillStats(models.Model):
    enrollment = models.ForeignKey(LanguageEnrollment, on_delete=models.CASCADE,  related_name='skill_stats')
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE)
    xp = models.IntegerField(default=0)
    total_lessons_completed = models.IntegerField(default=0)
    last_practiced = models.DateTimeField(null=True, blank=True)
    proficiency_score = models.FloatField(default=0.0) 
    level = models.IntegerField(default=0, help_text="Crown level 0-5")
    lessons_completed_at_level = models.IntegerField(default=0, help_text="Lessons completed at current level")
    lessons_required_for_next = models.IntegerField(default=5, help_text="Lessons needed to level up")
    # Review tracking
    needs_review = models.BooleanField(default=False)
    review_reminder_date = models.DateField(null=True, blank=True)
    STATUS_CHOICES = [
        ('locked', 'Locked'),
        ('available', 'Available'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('mastered', 'Mastered'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='locked')
    
    # Timestamps
    unlocked_at = models.DateTimeField(null=True, blank=True)
    first_completed_at = models.DateTimeField(null=True, blank=True)
    mastered_at = models.DateTimeField(null=True, blank=True)

    class Meta: 
        constraints = [
            models.UniqueConstraint(fields=['enrollment', 'skill'], name='uq_userskillstats_enrollment_skill_v2')
        ]
        indexes = [
            models.Index(fields=['enrollment', 'skill']),
            models.Index(fields=['enrollment', 'level']),
            models.Index(fields=['needs_review', 'review_reminder_date']),
        ]
    
    def __str__(self):
        return f"{self.skill.title} - Level {self.level} ({self.status})"
    
    @property
    def is_maxed(self):
        """Đã đạt level 5 chưa"""
        return self.level >= 5
    
    @property
    def progress_to_next_level(self):
        """% progress to next crown"""
        if self.is_maxed:
            return 100
        return (self.lessons_completed_at_level / self.lessons_required_for_next) * 100
    
    def complete_lesson(self, xp_earned=10):
        """Cập nhật khi hoàn thành một lesson"""
        self.total_lessons_completed += 1
        self.lessons_completed_at_level += 1
        self.xp += xp_earned
        self.last_practiced = timezone.now()
        
        if self.status == 'available':
            self.status = 'in_progress'
        
        # Check for level up
        if not self.is_maxed and self.lessons_completed_at_level >= self.lessons_required_for_next:
            self.level_up()
        
        # Update proficiency
        self._update_proficiency()
        
        self.save()
    
    def level_up(self):
        """Tăng crown level"""
        if self.is_maxed:
            return False
        
        self.level += 1
        self.lessons_completed_at_level = 0
        
        # Increase difficulty for next level
        self.lessons_required_for_next = 5 + (self.level * 2)  # 5, 7, 9, 11, 13
        
        if self.level == 5:
            self.status = 'mastered'
            self.mastered_at = timezone.now()
        elif not self.first_completed_at:
            self.status = 'completed'
            self.first_completed_at = timezone.now()
        
        self.save()
        return True
    
    def _update_proficiency(self):
        """Cập nhật proficiency score dựa trên level và accuracy"""
        base_score = self.level * 20  # Each level = 20 points
        # Add bonus based on completion
        completion_bonus = min(20, (self.lessons_completed_at_level / self.lessons_required_for_next) * 20)
        self.proficiency_score = min(100, base_score + completion_bonus)
    
    def mark_for_review(self):
        """Đánh dấu skill cần ôn tập"""
        self.needs_review = True
        self.review_reminder_date = timezone.now().date()
        self.save()
    
    def unlock(self):
        """Mở khóa skill"""
        if self.status == 'locked':
            self.status = 'available'
            self.unlocked_at = timezone.now()
            self.save()


class RoleplayScenario(models.Model):
    class Level(models.TextChoices):
        A1 = "A1", "CEFR A1"
        A2 = "A2", "CEFR A2"
        B1 = "B1", "CEFR B1"
        B2 = "B2", "CEFR B2"
        C1 = "C1", "CEFR C1"
        C2 = "C2", "CEFR C2"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=150, unique=True) 
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    level = models.CharField(max_length=2, choices=Level.choices, default=Level.A1)
    order = models.IntegerField(default=0)
    # gắn kịch bản với các skill (để lọc RAG theo skill)

    tags = models.JSONField(default=list, blank=True)
    skill_tags = models.JSONField(default=list, blank=True)   
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    embedding = VectorField(dimensions=768, null=True, blank=True)
    embedding_text = models.TextField(blank=True)
    embedding_updated_at = models.DateTimeField(null=True, blank=True)
    embedding_hash = models.CharField(max_length=64, blank=True, default="")
    embedding_model = models.CharField(max_length=100, blank=True, default="")


    class Meta:
        ordering = ["order", "created_at"]
        indexes = [
            models.Index(fields=["order"]),
            models.Index(fields=["level"]),
        ]

    def save(self, *args, **kwargs):
        if self.slug:
            self.slug = slugify(self.slug)
        else:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} ({self.slug})"


class RoleplayBlock(models.Model):
    class Section(models.TextChoices):
        BACKGROUND   = "background",   "Background"
        WARMUP       = "warmup",       "Warm-up Question"
        INSTRUCTION  = "instruction",  "Instruction"
        DIALOGUE     = "dialogue",     "Dialogue Turn"
        VOCABULARY   = "vocabulary",   "Vocabulary Item"

    class Role(models.TextChoices):
        TEACHER   = "teacher",   "Teacher"
        STUDENT_A = "student_a", "Student A"
        STUDENT_B = "student_b", "Student B"
        NARRATOR  = "narrator",  "Narrator"  

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scenario = models.ForeignKey(RoleplayScenario, on_delete=models.CASCADE, related_name="blocks")
    section = models.CharField(max_length=32, choices=Section.choices)
    order = models.IntegerField(default=0)

    role = models.CharField(max_length=32, choices=Role.choices, blank=True)
    text = models.TextField()

    extra = models.JSONField(default=dict, blank=True)  
    audio_key = models.CharField(max_length=255, blank=True) 
    tts_voice = models.CharField(max_length=64, blank=True)    
    lang_hint = models.CharField(max_length=10, blank=True)    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    embedding = VectorField(dimensions=768, null=True, blank=True)
    embedding_text = models.TextField(blank=True)
    embedding_updated_at = models.DateTimeField(null=True, blank=True)
    embedding_hash = models.CharField(max_length=64, blank=True, default="")
    embedding_model = models.CharField(max_length=100, blank=True, default="")


    class Meta:
        ordering = ["scenario_id", "section", "order", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["scenario", "section", "order"], name="uq_block_scenario_section_order")
        ]
        indexes = [
            models.Index(fields=["scenario", "section", "order"]),
            models.Index(fields=["section"]),
            models.Index(fields=["role"]),
        ]

    def __str__(self):
        return f"{self.scenario.slug} · {self.section} · #{self.order} · {self.role or '-'}"