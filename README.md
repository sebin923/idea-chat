# 💡 아이디어 톡 (Idea Talk)

> 학과 행사 아이디어를 실시간으로 모으는 브레인스토밍 채팅 서비스
> [클라우드컴퓨팅] Ch.10 AWS 프로젝트 적용 과제

| 항목 | 내용 |
|---|---|
| 배포 주소 | `http://<EC2 퍼블릭 IP>:8080` ← 배포 후 실제 주소로 수정 |
| 제출 버전 | `v1.0` 태그 (커밋 해시: `<git rev-parse --short HEAD 결과>`) |
| 작성자 | 2324074 (이름) |

---

## 1. 서비스 소개

### 대상 사용자
학과 축제·MT·체육대회 같은 행사를 준비하는 **학생회와 학과 학생들**

### 해결하려는 문제
- 행사 공지가 올라온 직후 단톡방에 의견이 한꺼번에 몰리면, 주제가 섞여서 아이디어가 묻혀.
- **주제별로 채팅방을 따로 만들어** 그 주제의 아이디어만 모으면 정리가 쉬워져.
- 공지 직후처럼 **특정 시간에 입장·메시지 전송이 몰리는 상황**을 가정한 서비스야.

### 핵심 기능

| # | 기능 | 사용자 입력 | 결과 |
|---|---|---|---|
| 1 | 채팅방 생성 | 채팅방 이름 입력 → [만들기] | 새 채팅방이 목록 맨 위에 표시 |
| 2 | 닉네임으로 입장 | 닉네임 입력 → 방의 [입장] | 대화 화면으로 이동, "OO님이 입장했습니다" 안내 |
| 3 | 메시지 전송·수신 | 브라우저 A에서 메시지 입력 → [전송] | 같은 방의 브라우저 B에 1초 안에 표시 |

---

## 2. AWS 구성도

```
                  ┌──────────────────────── AWS (ap-northeast-2, 서울) ───────────────────────┐
                  │                                                                         │
 [브라우저 A] ─┐   │   보안 그룹                EC2 (t2.micro / Amazon Linux 2023 또는 Ubuntu)   │
               ├──┼─▶ 인바운드 8080 허용 ──▶ ┌─────────── Docker Compose ───────────┐        │
 [브라우저 B] ─┘   │                         │  nginx :80  ──/api/──▶  backend :5000 │        │
                  │                         │  (화면 제공)            (Flask+gunicorn)│        │
                  │                         │                            │          │        │
                  │                         │                       redis :6379     │        │
                  │                         │                    (채팅방·메시지 저장)  │        │
                  │                         └───────────────────────────────────────┘        │
                  └─────────────────────────────────────────────────────────────────────────┘
```

### 사용자 요청 경로
1. 브라우저 → `http://<EC2 IP>:8080` (보안 그룹에서 8080 허용)
2. 호스트 8080 → **nginx** 컨테이너 80
3. `/` 요청 → nginx가 `index.html`, `style.css`, `app.js`를 바로 응답
4. `/api/...` 요청 → nginx가 **backend**(Flask) 5000으로 전달
5. Flask → **redis**에 채팅방·메시지 저장/조회 → JSON 응답

### 사용한 AWS 서비스와 선택 이유

| 서비스 | 역할 | 선택 이유 |
|---|---|---|
| **EC2** | Docker Compose로 nginx·Flask·Redis 컨테이너 3개를 실행하는 가상 서버 | 수업에서 만든 Compose 구조를 그대로 올릴 수 있고, 프리 티어 t2.micro로 비용 부담이 적음 |
| **보안 그룹** | 8080(서비스), 22(SSH, 내 IP만) 인바운드 허용 | Flask 5000·Redis 6379는 외부에 열지 않고 nginx를 통해서만 접근하게 함 |

---

## 3. 실행·배포 방법

### 폴더 구조
```
idea-chat/
├── docker-compose.yml     # 컨테이너 3개(nginx, backend, redis) 정의
├── nginx/default.conf     # / → 정적 파일, /api/ → Flask 전달
├── frontend/              # 화면 (index.html, style.css, app.js)
└── backend/               # Flask API (app.py, requirements.txt, Dockerfile)
```

### API 목록

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/health` | 서버·Redis 상태 확인 |
| GET | `/api/rooms` | 채팅방 목록 |
| POST | `/api/rooms` | 채팅방 생성 `{"name": "..."}` |
| POST | `/api/rooms/<id>/join` | 입장 `{"nickname": "..."}` |
| GET | `/api/rooms/<id>/messages?after=<번호>` | 새 메시지 조회 (1초 폴링) |
| POST | `/api/rooms/<id>/messages` | 메시지 전송 `{"nickname": "...", "text": "..."}` |

### 준비 사항
- Docker, Docker Compose (로컬: Docker Desktop)
- Git
- AWS 계정 (EC2)

### 로컬 실행
```bash
git clone https://github.com/<내 계정>/idea-chat.git
cd idea-chat
docker compose config            # 설정 검사
docker compose up -d --build     # 실행
curl http://localhost:8080/api/health
# → {"redis":"ok","status":"ok"}
```
브라우저에서 `http://localhost:8080` 접속

### AWS EC2 배포 절차
1. **EC2 인스턴스 생성**: 리전 서울(ap-northeast-2), AMI Ubuntu 24.04 LTS, 유형 t2.micro, 키 페어 생성·다운로드
2. **보안 그룹 인바운드 규칙**
   | 유형 | 포트 | 소스 |
   |---|---|---|
   | SSH | 22 | 내 IP |
   | 사용자 지정 TCP | 8080 | 0.0.0.0/0 |
3. **SSH 접속**
   ```bash
   ssh -i my-key.pem ubuntu@<EC2 퍼블릭 IP>
   ```
4. **Docker 설치**
   ```bash
   sudo apt update
   sudo apt install -y docker.io docker-compose-v2 git
   sudo usermod -aG docker $USER && newgrp docker
   ```
5. **코드 내려받아 실행**
   ```bash
   git clone https://github.com/<내 계정>/idea-chat.git
   cd idea-chat
   docker compose up -d --build
   docker compose ps                         # 3개 모두 running 확인
   curl http://localhost:8080/api/health
   ```
6. **접속 확인**: 내 PC 브라우저에서 `http://<EC2 퍼블릭 IP>:8080`

### 포트와 접속 주소
| 구분 | 포트 | 외부 공개 |
|---|---|---|
| nginx | 호스트 8080 → 컨테이너 80 | O |
| backend (Flask) | 5000 | X (Compose 내부만) |
| redis | 6379 | X (Compose 내부만) |

---

## 4. 검증 – 배포 주소에서의 기능 시험 결과

- 시험 환경: `http://<EC2 IP>:8080`, Chrome 브라우저 2개 창 (일반 창 A + 시크릿 창 B)
- 시험일: 2026-11-__

| 기능 | 구분 | 입력 | 기대 결과 | 실제 결과 |
|---|---|---|---|---|
| 1. 채팅방 생성 | 정상 | 이름 `축제 부스 아이디어` | 목록 맨 위에 새 방 표시, "채팅방을 만들었습니다" | ✅ |
| 1. 채팅방 생성 | 실패 | 이름 빈 칸(공백만) | "채팅방 이름을 입력하세요." 오류, 방 생성 안 됨 | ✅ |
| 1. 채팅방 생성 | 경계 | 21자 이름 | "20자 이하로 입력하세요." 오류 | ✅ |
| 2. 닉네임 입장 | 정상 | 닉네임 `세빈` → [입장] | 대화 화면 이동, "세빈님이 입장했습니다." 표시 | ✅ |
| 2. 닉네임 입장 | 실패 | 닉네임 빈 칸 → [입장] | "닉네임을 입력하세요." 오류, 화면 이동 안 됨 | ✅ |
| 3. 메시지 전송·수신 | 정상 | A에서 `포토존 부스 어때요?` 전송 | B 화면에 1초 안에 표시 | ✅ |
| 3. 메시지 전송·수신 | 실패 | 빈 메시지 전송 | "메시지를 입력하세요." 오류, 전송 안 됨 | ✅ |

> ✅ 표시는 직접 시험한 뒤 실제 결과로 바꿔 적기

---

## 5. 확장 검토 – ELB와 Auto Scaling

### 결론: 이번 배포에는 **적용하지 않음** (단일 EC2)

### 판단 근거
| 기준 | 판단 |
|---|---|
| 예상 부하 | 학과 단위(수십~백 명대) 동시 접속. 메시지는 짧은 텍스트이고 gunicorn 작업자 4개로 처리 가능한 수준 |
| 비용 | ALB는 시간당 요금이 계속 붙고, Auto Scaling으로 서버가 늘면 EC2 비용도 늘어남. 과제 검사 기간에는 프리 티어 EC2 1대가 가장 경제적 |
| 구조 | 현재 Redis가 같은 EC2 안에 있어서, 서버만 늘리면 서버마다 Redis가 따로 생겨 데이터가 나뉨. 확장하려면 Redis를 별도 서비스로 분리해야 함 |

### 확장이 필요해지면 (축제 공지 직후 수백 명 이상 동시 접속)
1. Redis를 **ElastiCache for Redis**로 분리 → 모든 서버가 같은 채팅 데이터를 공유
2. Flask 서버를 **EC2 Auto Scaling 그룹**(최소 1 · 희망 2 · 최대 4)으로 구성, CPU 60% 기준 대상 추적 정책
3. 앞단에 **ALB**를 두고 `/api/health`를 상태 검사 경로로 사용
4. 이 앱은 **서버에 상태를 저장하지 않고**(Redis에 저장), 메시지 수신을 **HTTP 폴링**으로 처리해서 ALB가 요청마다 아무 서버로 보내도 동작함 (WebSocket처럼 연결이 한 서버에 묶이는 문제 없음)
5. 최대 서버 수 제한 + AWS Budgets 예산 알림으로 비용 관리

---

## 6. 기록

### AI 활용
| 항목 | 내용 |
|---|---|
| 사용 여부 | 사용함 |
| 도구 | (사용한 도구 이름 기입) |
| 활용 범위 | (예: 담당 교수님 허락 하에 코드 초안·README 초안 작성에 사용) |
| 직접 확인한 결과 | (예: 로컬·EC2에서 직접 실행, 기능별 정상/실패 시험을 직접 수행하고 결과 기록, 코드 내용 검토) |

### 검사 후 자원 정리
- 검사 완료 후 EC2 인스턴스 종료(Terminate), 보안 그룹·키 페어 삭제
- GitHub 저장소와 README는 보존
