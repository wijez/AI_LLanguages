from languages.models import RoleplayScenario, RoleplayBlock

ORDER_PRIORITY = {"background":1, "instruction":2, "dialogue":3, "warmup":4, "vocabulary":5}
PRACTICE_SECTIONS = {"background": 1, "instruction":2, "warmup":3, "vocabulary":4}

def ordered_blocks(scn):
    blks = list(scn.blocks.all())
    blks.sort(key=lambda b: (ORDER_PRIORITY.get(b.section, 99), b.order, b.created_at))
    return blks

def split_prologue_and_dialogue(blocks):
    prologue = [b for b in blocks if b.section in ("background","instruction","warmup")]
    dialogue =  [b for b in blocks if b.section == "dialogue"]
    return prologue, dialogue


def practice_blocks(scn):
    """Return non-dialogue blocks in the order they should be displayed for practice."""
    blocks = ordered_blocks(scn)
    return [b for b in blocks if b.section in PRACTICE_SECTIONS]