# =====================================================================
# 학과 행사 아이디어 채팅 서비스 - 백엔드(Flask API 서버)
# ---------------------------------------------------------------------
# 이 파일이 하는 일
#   1) 채팅방 만들기 / 채팅방 목록 보여주기
#   2) 닉네임으로 채팅방에 입장하기
#   3) 메시지 보내기 / 새 메시지 받아오기
#   4) 서버가 살아있는지 확인하는 /api/health 제공
#
# 데이터는 Redis 에 저장해.
#   - Flask 서버 안(메모리)에 저장하면 서버가 2대 이상일 때
#     서버마다 데이터가 달라지는 문제가 생겨.
#   - Redis 라는 "공용 저장소"에 저장하면 Flask 서버를 몇 대로 늘려도
#     모두 같은 데이터를 보게 돼. (README 의 ELB·Auto Scaling 검토와 연결되는 부분)
#
# 요청 흐름: 브라우저 → Nginx(:80) → /api/ 요청만 Flask(:5000) 로 전달 → Redis
# =====================================================================

import json      # 메시지를 문자열(JSON)로 바꿔서 Redis 에 넣고 꺼내기 위해 사용
import os        # 환경 변수(REDIS_HOST 등)를 읽기 위해 사용
import time      # 현재 시간을 구하기 위해 사용
import uuid      # 채팅방마다 겹치지 않는 고유 ID 를 만들기 위해 사용

import redis                                   # Redis 에 접속하는 라이브러리
from flask import Flask, jsonify, request      # Flask 웹 서버 기본 도구들

# ---------------------------------------------------------------------
# 기본 설정값 (입력 길이 제한 = "경계 시험"에 쓰이는 값들)
# ---------------------------------------------------------------------
ROOM_NAME_MAX = 20      # 채팅방 이름은 최대 20글자
NICKNAME_MAX = 10       # 닉네임은 최대 10글자
MESSAGE_MAX = 200       # 메시지는 최대 200글자
KEEP_MESSAGES = 300     # 방마다 최근 메시지 300개만 보관 (Redis 용량 관리)

# Flask 앱 객체 만들기. 아래에서 @app.route 로 주소(API)를 붙여 나가.
app = Flask(__name__)

# 한글이 \uXXXX 로 깨져 보이지 않도록 JSON 응답을 그대로 한글로 내보내기
app.json.ensure_ascii = False

# ---------------------------------------------------------------------
# Redis 연결
#   docker-compose.yml 에서 REDIS_HOST=redis 로 넘겨줘.
#   (Compose 안에서는 서비스 이름 "redis" 가 곧 주소가 돼)
#   decode_responses=True → Redis 에서 꺼낸 값을 bytes 가 아니라 str 로 받기
# ---------------------------------------------------------------------
db = redis.Redis(
    host=os.environ.get("REDIS_HOST", "localhost"),
    port=int(os.environ.get("REDIS_PORT", "6379")),
    decode_responses=True,
)

# ---------------------------------------------------------------------
# Redis 에 저장하는 키 구조 (한눈에 보기)
#   rooms                  : 정렬 집합(ZSET)  방 ID 들을 "생성 시간" 순서로 저장
#   room_names             : 해시(HASH)       방 이름 → 방 ID  (이름 중복 검사용)
#   room:{방ID}            : 해시(HASH)       방 정보 (이름, 생성 시간)
#   room:{방ID}:seq        : 숫자             메시지 번호를 1, 2, 3... 으로 늘리는 카운터
#   room:{방ID}:messages   : 리스트(LIST)     메시지들(JSON 문자열)
#   room:{방ID}:members    : 집합(SET)        입장한 닉네임 목록 (참여자 수 표시용)
# ---------------------------------------------------------------------


def now_ms():
    """현재 시간을 '밀리초' 숫자로 돌려줘. (브라우저 JS 의 Date 와 단위가 같아서 편해)"""
    return int(time.time() * 1000)


def error(message, status):
    """
    오류 응답을 한 가지 모양으로 통일해서 돌려주는 함수.
    예) error("채팅방 이름을 입력하세요.", 400)
        → {"error": "채팅방 이름을 입력하세요."} 와 HTTP 상태코드 400
    """
    return jsonify({"error": message}), status


def get_json_body():
    """
    요청 본문(JSON)을 안전하게 꺼내는 함수.
    silent=True → JSON 이 아니거나 비어 있어도 에러를 터뜨리지 않고 None 을 줘.
    None 이면 빈 딕셔너리 {} 로 바꿔서 아래 코드가 편하게 쓰도록 함.
    """
    return request.get_json(silent=True) or {}


def load_room(room_id):
    """
    방 ID 로 방 정보를 Redis 에서 읽어와 딕셔너리로 돌려줘.
    방이 없으면 None 을 돌려줘서 호출한 쪽에서 404 처리를 하게 함.
    """
    info = db.hgetall(f"room:{room_id}")   # 해시 전체 읽기 → 없으면 빈 딕셔너리 {}
    if not info:
        return None
    return {
        "id": room_id,
        "name": info["name"],
        "created_at": int(info["created_at"]),
        "members": db.scard(f"room:{room_id}:members"),  # 집합 크기 = 참여자 수
    }


def push_message(room_id, nickname, text, kind="user"):
    """
    메시지 1개를 방에 저장하는 함수.
      kind="user"   → 사용자가 보낸 일반 메시지
      kind="system" → "OO님이 입장했습니다" 같은 안내 메시지
    """
    # INCR: 숫자를 1 올리고 그 값을 돌려줌 → 메시지마다 고유 번호(1, 2, 3...)가 생김
    seq = db.incr(f"room:{room_id}:seq")

    message = {
        "id": seq,               # 메시지 번호 (브라우저가 "어디까지 받았는지" 기억할 때 사용)
        "nickname": nickname,
        "text": text,
        "kind": kind,
        "ts": now_ms(),          # 보낸 시간
    }

    # 파이프라인: 여러 Redis 명령을 한 번에 묶어서 보내는 기능 (왕복 횟수 감소)
    pipe = db.pipeline()
    # RPUSH: 리스트 맨 뒤에 추가 (json.dumps 로 딕셔너리 → 문자열 변환)
    pipe.rpush(f"room:{room_id}:messages", json.dumps(message, ensure_ascii=False))
    # LTRIM: 리스트를 "뒤에서 KEEP_MESSAGES 개"만 남기고 잘라냄 → 오래된 메시지 정리
    pipe.ltrim(f"room:{room_id}:messages", -KEEP_MESSAGES, -1)
    pipe.execute()
    return message


# =====================================================================
# API 0. 상태 확인  GET /api/health
#   - 로컬 점검, EC2 배포 후 점검 때 가장 먼저 호출해 보는 주소
#   - Redis 까지 연결되는지 PING 으로 같이 확인
# =====================================================================
@app.get("/api/health")
def health():
    try:
        db.ping()   # Redis 가 살아 있으면 True, 죽어 있으면 예외 발생
        return jsonify({"status": "ok", "redis": "ok"})
    except redis.RedisError:
        # 서버(Flask)는 살아 있지만 Redis 연결이 안 되는 상황 → 503(서비스 불가)
        return jsonify({"status": "error", "redis": "unreachable"}), 503


# =====================================================================
# API 1-1. 채팅방 목록  GET /api/rooms
# =====================================================================
@app.get("/api/rooms")
def list_rooms():
    # ZREVRANGE: 점수(생성 시간)가 큰 것부터 = 최신 방이 맨 위로 오도록 가져오기
    room_ids = db.zrevrange("rooms", 0, -1)
    rooms = []
    for room_id in room_ids:
        room = load_room(room_id)
        if room:                    # 혹시 정보가 지워진 방이 있으면 건너뛰기
            rooms.append(room)
    return jsonify({"rooms": rooms})


# =====================================================================
# API 1-2. 채팅방 생성  POST /api/rooms   body: {"name": "축제 부스 아이디어"}
#   정상   : 201 + 새 방 정보 → 화면 목록에 표시
#   실패   : 이름이 비었음(400) / 20글자 초과(400) / 같은 이름 존재(409)
# =====================================================================
@app.post("/api/rooms")
def create_room():
    body = get_json_body()
    # str(...)  : 혹시 숫자 등 다른 타입이 와도 문자열로 통일
    # .strip()  : 앞뒤 공백 제거 → "   " 처럼 공백만 넣은 경우도 "빈 이름"으로 처리됨
    name = str(body.get("name", "")).strip()

    # ---- 입력 검사(실패/경계 시험 대상) ----
    if not name:
        return error("채팅방 이름을 입력하세요.", 400)
    if len(name) > ROOM_NAME_MAX:
        return error(f"채팅방 이름은 {ROOM_NAME_MAX}자 이하로 입력하세요.", 400)

    # 짧고 겹치지 않는 방 ID 만들기 (uuid 앞 8자리)
    room_id = uuid.uuid4().hex[:8]

    # HSETNX: "그 이름이 아직 없을 때만" 저장하고 1을 돌려줌. 이미 있으면 0.
    #   → 두 사람이 동시에 같은 이름으로 만들어도 한 명만 성공하도록 막아 줌
    if not db.hsetnx("room_names", name, room_id):
        return error("같은 이름의 채팅방이 이미 있습니다.", 409)

    created = now_ms()
    pipe = db.pipeline()
    pipe.hset(f"room:{room_id}", mapping={"name": name, "created_at": created})
    pipe.zadd("rooms", {room_id: created})   # 목록(정렬 집합)에 생성 시간을 점수로 추가
    pipe.execute()

    return jsonify(load_room(room_id)), 201   # 201 = "새로 만들어졌음"


# =====================================================================
# API 2. 채팅방 입장  POST /api/rooms/<방ID>/join   body: {"nickname": "세빈"}
#   정상   : 200 + 방 정보 → 브라우저가 대화 화면으로 이동
#   실패   : 닉네임 비었음(400) / 10글자 초과(400) / 없는 방(404)
# =====================================================================
@app.post("/api/rooms/<room_id>/join")
def join_room(room_id):
    room = load_room(room_id)
    if room is None:
        return error("존재하지 않는 채팅방입니다.", 404)

    nickname = str(get_json_body().get("nickname", "")).strip()
    if not nickname:
        return error("닉네임을 입력하세요.", 400)
    if len(nickname) > NICKNAME_MAX:
        return error(f"닉네임은 {NICKNAME_MAX}자 이하로 입력하세요.", 400)

    # SADD: 집합에 추가 (이미 있는 닉네임이면 0 을 돌려줌 = 새로고침 후 재입장)
    is_new = db.sadd(f"room:{room_id}:members", nickname)
    if is_new:
        # 처음 들어온 사람만 "입장했습니다" 안내 메시지를 남겨서 다른 사람에게 보이게 함
        push_message(room_id, "", f"{nickname}님이 입장했습니다.", kind="system")

    return jsonify({"room": load_room(room_id), "nickname": nickname})


# =====================================================================
# API 3-1. 메시지 받아오기  GET /api/rooms/<방ID>/messages?after=번호
#   - 브라우저는 1초마다 이 주소를 호출해서 "after 번호보다 큰" 새 메시지만 받아 감
#     (이런 방식을 '폴링(polling)'이라고 해)
#   - after=0 이면 보관 중인 메시지를 전부 줌 (처음 입장했을 때)
# =====================================================================
@app.get("/api/rooms/<room_id>/messages")
def get_messages(room_id):
    if load_room(room_id) is None:
        return error("존재하지 않는 채팅방입니다.", 404)

    # ?after= 값을 숫자로 바꾸기. 숫자가 아니면 0 으로 처리
    try:
        after = int(request.args.get("after", "0"))
    except ValueError:
        after = 0

    raw_list = db.lrange(f"room:{room_id}:messages", 0, -1)   # 리스트 전체 읽기
    messages = [json.loads(raw) for raw in raw_list]          # 문자열 → 딕셔너리
    new_messages = [m for m in messages if m["id"] > after]   # 새 메시지만 골라내기
    return jsonify({"messages": new_messages})


# =====================================================================
# API 3-2. 메시지 보내기  POST /api/rooms/<방ID>/messages
#          body: {"nickname": "세빈", "text": "포토존 어때요?"}
#   정상   : 201 → 같은 방의 다른 브라우저 화면에 1초 안에 표시
#   실패   : 빈 메시지(400) / 200자 초과(400) / 입장하지 않은 닉네임(403) / 없는 방(404)
# =====================================================================
@app.post("/api/rooms/<room_id>/messages")
def send_message(room_id):
    if load_room(room_id) is None:
        return error("존재하지 않는 채팅방입니다.", 404)

    body = get_json_body()
    nickname = str(body.get("nickname", "")).strip()
    text = str(body.get("text", "")).strip()

    # 입장(join)하지 않고 메시지만 보내려는 요청 막기
    if not nickname or not db.sismember(f"room:{room_id}:members", nickname):
        return error("채팅방에 먼저 입장하세요.", 403)
    if not text:
        return error("메시지를 입력하세요.", 400)
    if len(text) > MESSAGE_MAX:
        return error(f"메시지는 {MESSAGE_MAX}자 이하로 입력하세요.", 400)

    message = push_message(room_id, nickname, text)
    return jsonify(message), 201


# ---------------------------------------------------------------------
# "python app.py" 로 직접 실행할 때만 동작하는 부분 (개발용)
# Docker 에서는 gunicorn 이 app 객체를 불러서 실행하므로 이 부분은 안 쓰여.
# ---------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
