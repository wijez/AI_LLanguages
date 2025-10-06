# Generate per-topic Skills and Lessons JSON files for the user's topic list.
# Each topic gets 5 skills; each skill gets 3 lessons with Duolingo-style blocks.
# Files are written under /mnt/data/dataset/ as skills_<slug>.json and lessons_<slug>.json

import os, json, re
from pathlib import Path
from typing import List, Dict

outdir = Path("D:\AI_LL\dataset")
outdir.mkdir(parents=True, exist_ok=True)

topics = [
    ("a1-greetings", "A1 - Basic Greetings", "Learn simple greetings, introductions, and polite expressions.", "A1"),
    ("a1-numbers-dates", "A1 - Numbers and Dates", "Counting, telling the time, days of the week, and months.", "A1"),
    ("a1-daily-activities", "A1 - Daily Activities", "Vocabulary and phrases for everyday routines.", "A1"),
    ("a2-food-drinks", "A2 - Food and Drinks", "Ordering in restaurants, talking about meals and preferences.", "A2"),
    ("a2-shopping", "A2 - Shopping", "Useful phrases for buying clothes, groceries, and bargaining.", "A2"),
    ("a2-travel-directions", "A2 - Travel and Directions", "How to ask for and give directions, booking tickets, travel phrases.", "A2"),
    ("b1-school-work", "B1 - School and Work", "Talking about studies, jobs, responsibilities, and experiences.", "B1"),
    ("b1-hobbies-free-time", "B1 - Hobbies and Free Time", "Discussing hobbies, sports, entertainment, and weekend plans.", "B1"),
    ("b1-health-emergencies", "B1 - Health and Emergencies", "Visiting a doctor, describing symptoms, and emergencies.", "B1"),
    ("b2-opinions-debates", "B2 - Opinions and Debates", "Expressing opinions, agreeing and disagreeing in conversations.", "B2"),
    ("b2-media-technology", "B2 - Media and Technology", "Discussing internet, social media, smartphones, and modern life.", "B2"),
    ("b2-environment-society", "B2 - Environment and Society", "Talking about environmental issues and social challenges.", "B2"),
    ("c1-academic-english", "C1 - Academic English", "Writing essays, summarizing articles, and academic vocabulary.", "C1"),
    ("c1-business-english", "C1 - Business English", "Meetings, presentations, negotiations, and formal communication.", "C1"),
    ("c1-culture-politics", "C1 - Culture and Politics", "Discussing culture, traditions, and political topics.", "C1"),
    ("c2-idioms-phrases", "C2 - Idioms and Phrasal Verbs", "Master advanced idiomatic expressions and phrasal verbs.", "C2"),
    ("c2-advanced-writing", "C2 - Advanced Writing", "Develop skills in essay writing, reports, and formal documents.", "C2"),
    ("c2-fluency-masterclass", "C2 - Fluency Masterclass", "Achieve near-native fluency with debates, literature, and analysis.", "C2"),
]

# Skill templates per topic slug (5 per topic)
templates = {
    "a1-greetings": [
        ("Hello & Goodbye", "Common greetings and farewells."),
        ("Introduce Yourself", "Names, origin, and simple info."),
        ("Polite Expressions", "Please, thank you, excuse me."),
        ("Basic Questions", "How are you? What's your name?"),
        ("Small Talk", "Weather, mood, and simple chit-chat.")
    ],
    "a1-numbers-dates": [
        ("Numbers 0-20", "Basic numbers and counting."),
        ("Telling Time", "O'clock, half past, quarter to."),
        ("Days & Months", "Weekdays and months."),
        ("Dates & Birthdays", "Ordinal numbers and dates."),
        ("Simple Schedules", "Timetables and appointments.")
    ],
    "a1-daily-activities": [
        ("Morning Routine", "Wake up, breakfast, commute."),
        ("At School", "Classes, homework, teachers."),
        ("At Work (A1)", "Office basics and tasks."),
        ("Evening Activities", "Dinner, TV, family time."),
        ("Weekend Plans (A1)", "Relaxing and simple plans.")
    ],
    "a2-food-drinks": [
        ("At a Restaurant", "Ordering food and drinks."),
        ("At a Café", "Coffee, tea, pastries, snacks."),
        ("Cooking & Ingredients", "Basic cooking verbs and nouns."),
        ("Likes & Preferences", "I like/don't like, favorites."),
        ("Dietary Needs", "Allergies, vegetarian, halal.")
    ],
    "a2-shopping": [
        ("Clothes Shopping", "Sizes, colors, changing rooms."),
        ("Grocery Shopping", "Fruits, vegetables, staples."),
        ("Prices & Bargaining", "Asking prices and discounts."),
        ("Sizes & Fits", "Small/medium/large, fits well."),
        ("Returns & Exchanges", "Policies and receipts.")
    ],
    "a2-travel-directions": [
        ("Asking Directions", "Left/right, near/far, landmarks."),
        ("Transportation", "Bus, train, taxi, subway."),
        ("Booking & Tickets", "Schedules, reservations, seats."),
        ("At the Hotel", "Check-in, facilities, problems."),
        ("At the Airport", "Security, boarding, baggage.")
    ],
    "b1-school-work": [
        ("Subjects & Courses", "Majors, schedules, projects."),
        ("Job Roles & Duties", "Responsibilities and tasks."),
        ("Meetings & Deadlines", "Agendas, timelines, follow-ups."),
        ("Interviews", "Experience, strengths, STAR."),
        ("Workplace Communication", "Requests, feedback, clarity.")
    ],
    "b1-hobbies-free-time": [
        ("Sports", "Team vs solo, equipment."),
        ("Music & Arts", "Genres, instruments, museums."),
        ("Movies & TV", "Genres, reviews, recommendations."),
        ("Travel & Outdoors", "Trips, hiking, beaches."),
        ("Social Events", "Parties, festivals, invitations.")
    ],
    "b1-health-emergencies": [
        ("Symptoms & Illness", "Describing how you feel."),
        ("At the Pharmacy", "Medicines and instructions."),
        ("Doctor's Appointment", "History, diagnosis, advice."),
        ("First Aid & Emergencies", "Accidents and responses."),
        ("Insurance & Forms", "Coverage, claims, paperwork.")
    ],
    "b2-opinions-debates": [
        ("Expressing Opinions", "Nuanced views and hedging."),
        ("Agree & Disagree", "Conceding and countering."),
        ("Persuasion & Rhetoric", "Ethos, logos, pathos."),
        ("Debate Strategies", "Framing, rebuttal, evidence."),
        ("Bias & Fallacies", "Common pitfalls in reasoning.")
    ],
    "b2-media-technology": [
        ("Social Media", "Platforms, posting, etiquette."),
        ("Smartphones & Apps", "Features, privacy, updates."),
        ("News & Journalism", "Sources, bias, fact-checking."),
        ("Online Safety", "Passwords, scams, security."),
        ("Digital Productivity", "Tools, workflows, automation.")
    ],
    "b2-environment-society": [
        ("Climate Change", "Causes, effects, mitigation."),
        ("Sustainability", "Reduce, reuse, recycle."),
        ("Urbanization", "Cities, transport, housing."),
        ("Inequality", "Income, gender, access."),
        ("Civic Engagement", "Volunteering, voting, policy.")
    ],
    "c1-academic-english": [
        ("Academic Vocabulary", "Discipline-specific terms."),
        ("Summarizing", "Condensing key ideas."),
        ("Critical Reading", "Evaluate arguments & methods."),
        ("Research Methods", "Qualitative vs quantitative."),
        ("Presentations (C1)", "Structure, visuals, delivery.")
    ],
    "c1-business-english": [
        ("Meetings & Agendas", "Structure and facilitation."),
        ("Presentations (Biz)", "Pitching and demos."),
        ("Negotiations", "BATNA, concessions, value."),
        ("Emails & Reports", "Tone, clarity, formatting."),
        ("Project Management", "Scope, risk, stakeholders.")
    ],
    "c1-culture-politics": [
        ("Cultural Discussions", "Identity, norms, values."),
        ("Traditions & Heritage", "Rituals and history."),
        ("Political Systems", "Democracy, policy, law."),
        ("Public Policy", "Design, trade-offs, impact."),
        ("International Relations", "Diplomacy, conflict, trade.")
    ],
    "c2-idioms-phrases": [
        ("Common Idioms", "Everyday figurative language."),
        ("Phrasal Verbs I", "Up, out, off, on."),
        ("Phrasal Verbs II", "Over, through, away, back."),
        ("Metaphors & Analogies", "Conceptual metaphors."),
        ("Collocations", "Natural word pairings.")
    ],
    "c2-advanced-writing": [
        ("Argumentative Essays", "Claims, evidence, logic."),
        ("Reports & Proposals", "Structure and clarity."),
        ("Editing & Style", "Concision, cohesion, tone."),
        ("Citations & Integrity", "Avoid plagiarism, formats."),
        ("Peer Review", "Constructive feedback.")
    ],
    "c2-fluency-masterclass": [
        ("Advanced Debates", "Live rebuttals and nuance."),
        ("Literature Analysis", "Themes, symbols, context."),
        ("Rhetorical Devices", "Parallelism, irony, anaphora."),
        ("Interview Mastery", "Behavioral & case practice."),
        ("Impromptu Speaking", "Rapid structuring & delivery.")
    ],
}

# Default lesson title variants
lesson_variants = ["Foundations", "Practice", "Challenge"]

def normalize_slug(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text).strip().lower()
    s = re.sub(r"\s+", "-", s)
    return s

def build_blocks(level: str, skill_title: str, variant: str) -> List[Dict]:
    # Simple progression of task types by level
    common = [
        {"type": "translate", "direction": "vi->en", "prompt": f"Translate: sample for {skill_title}", "answer": "sample"},
        {"type": "multiple_choice", "prompt": f"Pick the best option for {skill_title}.", "choices": ["A","B","C"], "answer": "A"},
        {"type": "fill_blank", "prompt": f"Fill the blank ({skill_title}).", "answer": "answer"},
    ]
    # add advanced tasks
    if level in ("B1","B2","C1","C2"):
        common.append({"type": "reorder", "prompt": "Reorder to form a correct sentence.", "tokens": ["This","is","a","test","."], "answer": ["This","is","a","test","."]})
        common.append({"type": "speak", "prompt": f"Speak about: {skill_title} ({variant})"})
    if level in ("C1","C2"):
        common.append({"type": "write", "prompt": f"Write 3-4 sentences about {skill_title} ({variant})."})
        common.append({"type": "critique", "prompt": f"Read and critique a short paragraph about {skill_title}."})
    return common

def build_skill_lessons(topic_level: str, skill_title: str) -> List[Dict]:
    lessons = []
    for idx, variant in enumerate(lesson_variants, start=1):
        lesson = {
            "title": f"{skill_title} — {variant}",
            "xp_reward": 10 if topic_level.startswith("A") else (15 if topic_level.startswith("B") else 20),
            "duration_seconds": 120 + 10*idx,
            "content": {
                "schema_version": 1,
                "cefr": topic_level,
                "grammar_points": [f"{skill_title} basics", f"{variant.lower()} focus"],
                "target_vocab": [normalize_slug(skill_title).replace("-", " "), variant.lower()],
                "blocks": build_blocks(topic_level, skill_title, variant)
            }
        }
        lessons.append(lesson)
    return lessons

# Generate files per topic
created_files = []
for slug, title, desc, level in topics:
    skills = []
    lessons = []
    skill_defs = templates[slug]
    for order, (skill_title, skill_desc) in enumerate(skill_defs, start=1):
        skills.append({
            "title": skill_title,
            "description": skill_desc,
            "order": order,
            "topic": slug  # use slug so user can --topic on import
        })
        # add 3 lessons per skill
        for lesson in build_skill_lessons(level, skill_title):
            lessons.append({
                "title": lesson["title"],
                "content": lesson["content"],
                "xp_reward": lesson["xp_reward"],
                "duration_seconds": lesson["duration_seconds"],
                "skill": skill_title  # refer by title; use --topic to disambiguate on import
            })

    skills_path = outdir / f"skills_{slug}.json"
    lessons_path = outdir / f"lessons_{slug}.json"
    with open(skills_path, "w", encoding="utf-8") as f:
        json.dump(skills, f, ensure_ascii=False, indent=2)
    with open(lessons_path, "w", encoding="utf-8") as f:
        json.dump(lessons, f, ensure_ascii=False, indent=2)
    created_files.append((str(skills_path), str(lessons_path)))

created_files
