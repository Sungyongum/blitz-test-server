# Blitz_app/bot_state.py

from threading import Lock

# 전역 봇 상태 저장용
bot_events = {}
force_refresh_flags = {}
single_refresh_flags = {}

repeat_overrides = {}
_repeat_lock = Lock()

def set_repeat_override(user_id: int, value: bool):
    """루프 중에도 즉시 반영되는 반복 여부 오버라이드"""
    with _repeat_lock:
        repeat_overrides[user_id] = value

def clear_repeat_override(user_id: int):
    """오버라이드 해제"""
    with _repeat_lock:
        repeat_overrides.pop(user_id, None)