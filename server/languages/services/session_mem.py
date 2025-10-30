from django.core.cache import cache
import uuid, time

TTL = 60*60 

def create_session(scn_id, chosen_role, dialogue_ids):
    sid = str(uuid.uuid4())
    cache.set(f"rp:{sid}", {
        "scenario_id": scn_id,
        "role": chosen_role,
        "dialogue_ids": dialogue_ids,
        "idx": 0,
        "created_at": int(time.time()),
    }, TTL)
    return sid

def get_session(sid):
    return cache.get(f"rp:{sid}")

def save_session(sid, data):
    cache.set(f"rp:{sid}", data, TTL)
