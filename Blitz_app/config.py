# Blitz_app/config.py
import os
import logging
from pathlib import Path
from datetime import timedelta

# ===== 기본 경로/DB =====
BASE_DIR = Path(__file__).resolve().parents[1]

# Support optional BLITZ_DB_PATH env to override absolute path
BLITZ_DB_PATH = os.environ.get('BLITZ_DB_PATH')
if BLITZ_DB_PATH:
    DB_PATH = Path(BLITZ_DB_PATH).resolve()
else:
    DB_PATH = BASE_DIR / "instance" / "users.db"

# Ensure instance directory exists
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SQLALCHEMY_DATABASE_URI = f"sqlite:///{DB_PATH.as_posix()}"
SQLALCHEMY_TRACK_MODIFICATIONS = False

# □ SQLAlchemy 엔진 옵션 (연결 재시도/헬스체크)
SQLALCHEMY_ENGINE_OPTIONS = {
    "pool_pre_ping": True,
    # SQLite busy 상황에서 대기 시간(초)
    "connect_args": {"timeout": 30},
}

# Print resolved DB path at startup for troubleshooting
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info(f"📁 Database path resolved to: {DB_PATH.as_posix()}")

# ===== Flask 세션/쿠키 =====
# env 우선, 없으면 고정값 사용(안전)
SECRET_KEY = (
    os.environ.get("BLITZ_SECRET_KEY")
    or os.environ.get("FLASK_SECRET_KEY")
    or os.environ.get("SECRET_KEY")
    or "ce05772949e7d8da54b46d410ed7e12805a133b233fe296c832a70f1ec73da5f"
)

# (선택) 8000과 8001을 동시에 쓸 때 쿠키 충돌 방지용 이름 지정 가능
SESSION_COOKIE_NAME = os.environ.get("BLITZ_SESSION_COOKIE", "session")

# ✅ Session 설정 (Redis 대신 filesystem 사용)
SESSION_TYPE = "filesystem"
SESSION_FILE_DIR = BASE_DIR / "instance" / "flask_session"
SESSION_PERMANENT = True
PERMANENT_SESSION_LIFETIME = timedelta(days=7)
SESSION_USE_SIGNER = True     # 쿠키 위변조 방지
SESSION_COOKIE_SECURE = False # HTTPS가 아니면 False (나중에 SSL 붙이면 True로)
SESSION_COOKIE_SAMESITE = "Lax"

# Redis URL for production (commented out for development)
# SESSION_TYPE = "redis"
# SESSION_REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")

# 템플릿/디버그 최적화
DEBUG = False
TEMPLATES_AUTO_RELOAD = False
SEND_FILE_MAX_AGE_DEFAULT = 3600  # 정적 파일 캐시 기본 1시간

# ===== SQLite 성능 PRAGMA (WAL 모드 등) =====
# SQLAlchemy가 연결을 만들 때마다 적용되도록 리스너 등록
try:
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    @event.listens_for(Engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        # SQLite에만 적용
        try:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")     # 동시 읽기↑
            cursor.execute("PRAGMA synchronous=NORMAL;")   # 쓰기 성능↑
            cursor.execute("PRAGMA temp_store=MEMORY;")
            cursor.execute("PRAGMA cache_size=-20000;")    # 약 20MB
            cursor.execute("PRAGMA busy_timeout=30000;")   # 30초 대기
            cursor.execute("PRAGMA foreign_keys=ON;")      # FK 제약조건 활성화
            cursor.close()
        except Exception:
            # 다른 DB(예: Postgres)에서는 조용히 통과
            pass

    # Asia/Seoul 타임존 설정
    import os
    os.environ.setdefault('TZ', 'Asia/Seoul')
except Exception:
    # SQLAlchemy가 아직 설치되지 않았거나 초기 로딩 이슈 시 무시
    pass
