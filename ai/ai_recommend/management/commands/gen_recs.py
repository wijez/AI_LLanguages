# ai_recommend/management/commands/gen_recs.py
from django.core.management.base import BaseCommand
from ai_recommend.services.generate_recommendations import generate_recommendations_for_user

class Command(BaseCommand):
    help = "Generate recommendations for a user from BE data"

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--enrollment-id", type=int, required=True)
        parser.add_argument("--language", type=str, required=True)
        parser.add_argument("--top-k", type=int, default=5)
        parser.add_argument("--top-n-words", type=int, default=10)

    def handle(self, *args, **opts):
        ids = generate_recommendations_for_user(
            user_id=opts["user_id"],
            enrollment_id=opts["enrollment_id"],
            language=opts["language"],
            top_k=opts["top_k"],
            top_n_words=opts["top_n_words"],
        )
        self.stdout.write(self.style.SUCCESS(f"Created {len(ids)} recommendations: {ids}"))
