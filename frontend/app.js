// =====================================================================
// 화면 동작 (브라우저에서 실행되는 JavaScript)
// ---------------------------------------------------------------------
// 하는 일
//   - 방 목록을 3초마다 새로고침
//   - [만들기] → POST /api/rooms
//   - [입장]   → POST /api/rooms/{id}/join  → 채팅 화면으로 전환
//   - 채팅 화면에서 1초마다 GET /api/rooms/{id}/messages?after=번호 (폴링)
//   - [전송]   → POST /api/rooms/{id}/messages
// =====================================================================

// ---------------------------------------------------------------------
// 화면 요소를 미리 찾아서 변수에 담아 두기 ($ 로 시작하면 "화면 요소"라는 표시)
// ---------------------------------------------------------------------
const $lobby = document.getElementById("lobby");
const $chat = document.getElementById("chat");
const $createForm = document.getElementById("create-form");
const $roomName = document.getElementById("room-name");
const $createMsg = document.getElementById("create-msg");
const $nickname = document.getElementById("nickname");
const $joinMsg = document.getElementById("join-msg");
const $roomList = document.getElementById("room-list");
const $roomCount = document.getElementById("room-count");
const $chatTitle = document.getElementById("chat-title");
const $chatSub = document.getElementById("chat-sub");
const $messages = document.getElementById("messages");
const $sendForm = document.getElementById("send-form");
const $messageInput = document.getElementById("message-input");
const $sendMsg = document.getElementById("send-msg");
const $leaveBtn = document.getElementById("leave-btn");

// ---------------------------------------------------------------------
// 현재 상태를 기억하는 변수들
// ---------------------------------------------------------------------
let currentRoom = null;   // 지금 들어가 있는 방 정보 {id, name, ...} (로비면 null)
let myNickname = "";      // 내 닉네임
let lastMessageId = 0;    // 마지막으로 받은 메시지 번호 → 다음엔 이것보다 큰 것만 요청
let messageTimer = null;  // 1초 폴링 타이머
let roomTimer = null;     // 3초 방 목록 새로고침 타이머

// ---------------------------------------------------------------------
// 서버에 요청을 보내는 공통 함수
//   - 성공이면 JSON 결과를 돌려주고
//   - 실패(400, 404 등)면 서버가 준 error 문구로 예외를 던져서
//     호출한 쪽의 catch 에서 화면에 보여줄 수 있게 함
// ---------------------------------------------------------------------
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  // 응답 본문을 JSON 으로 읽기 (본문이 비어 있으면 빈 객체)
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `요청 실패 (${res.status})`);
  }
  return data;
}

// 안내 문구 표시 함수 (type: "error" 빨강, "ok" 초록, "" 기본)
function showMsg($el, text, type = "") {
  $el.textContent = text;
  $el.className = "msg " + type;
}

// 밀리초 시간 → "오후 3:05" 같은 한국어 시각 문자열
function formatTime(ms) {
  return new Date(ms).toLocaleTimeString("ko-KR", { hour: "numeric", minute: "2-digit" });
}

// =====================================================================
// 로비: 방 목록 불러오기
// =====================================================================
async function loadRooms() {
  try {
    const data = await api("/api/rooms");
    renderRooms(data.rooms);
  } catch (err) {
    showMsg($joinMsg, "방 목록을 불러오지 못했습니다: " + err.message, "error");
  }
}

// 방 목록을 화면(<ul>)에 그리기
function renderRooms(rooms) {
  $roomList.innerHTML = "";           // 기존 목록 비우기
  $roomCount.textContent = `(${rooms.length}개)`;

  if (rooms.length === 0) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "아직 채팅방이 없어요. 위에서 첫 방을 만들어 보세요!";
    $roomList.appendChild(li);
    return;
  }

  for (const room of rooms) {
    const li = document.createElement("li");

    const info = document.createElement("div");
    const name = document.createElement("div");
    name.className = "name";
    // textContent 사용: 방 이름에 <script> 같은 글자가 있어도 코드로 실행되지 않고 글자로만 보임(XSS 방지)
    name.textContent = room.name;
    const sub = document.createElement("div");
    sub.className = "muted";
    sub.textContent = `참여 ${room.members}명`;
    info.append(name, sub);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "입장";
    btn.addEventListener("click", () => joinRoom(room));  // 버튼 누르면 이 방으로 입장

    li.append(info, btn);
    $roomList.appendChild(li);
  }
}

// =====================================================================
// 기능 1: 채팅방 생성
// =====================================================================
$createForm.addEventListener("submit", async (event) => {
  event.preventDefault();   // form 기본 동작(페이지 새로고침) 막기
  try {
    const room = await api("/api/rooms", {
      method: "POST",
      body: JSON.stringify({ name: $roomName.value }),
    });
    showMsg($createMsg, `'${room.name}' 채팅방을 만들었습니다.`, "ok");
    $roomName.value = "";
    loadRooms();            // 목록 바로 새로고침 → 새 방이 맨 위에 보임
  } catch (err) {
    showMsg($createMsg, err.message, "error");   // 예: "채팅방 이름을 입력하세요."
  }
});

// =====================================================================
// 기능 2: 닉네임으로 채팅방 입장
// =====================================================================
async function joinRoom(room) {
  try {
    const data = await api(`/api/rooms/${room.id}/join`, {
      method: "POST",
      body: JSON.stringify({ nickname: $nickname.value }),
    });
    showMsg($joinMsg, "");
    enterChat(data.room, data.nickname);
  } catch (err) {
    showMsg($joinMsg, err.message, "error");     // 예: "닉네임을 입력하세요."
  }
}

// 채팅 화면으로 전환
function enterChat(room, nickname) {
  currentRoom = room;
  myNickname = nickname;
  lastMessageId = 0;
  $messages.innerHTML = "";
  showMsg($sendMsg, "");

  $chatTitle.textContent = room.name;
  $chatSub.textContent = `${nickname} 님으로 참여 중`;

  $lobby.hidden = true;     // 로비 숨기기
  $chat.hidden = false;     // 채팅 화면 보이기
  $messageInput.focus();

  clearInterval(roomTimer);                          // 로비용 타이머 멈춤
  pollMessages();                                    // 처음 한 번 바로 불러오기
  messageTimer = setInterval(pollMessages, 1000);    // 이후 1초마다 새 메시지 확인
}

// 로비로 돌아가기
$leaveBtn.addEventListener("click", () => {
  clearInterval(messageTimer);
  currentRoom = null;
  $chat.hidden = true;
  $lobby.hidden = false;
  loadRooms();
  roomTimer = setInterval(loadRooms, 3000);
});

// =====================================================================
// 기능 3-1: 메시지 수신 (폴링)
// =====================================================================
async function pollMessages() {
  if (!currentRoom) return;
  try {
    const data = await api(`/api/rooms/${currentRoom.id}/messages?after=${lastMessageId}`);
    for (const m of data.messages) {
      addMessage(m);
      lastMessageId = Math.max(lastMessageId, m.id);  // 받은 번호 중 가장 큰 값 기억
    }
  } catch (err) {
    showMsg($sendMsg, "메시지를 받아오지 못했습니다: " + err.message, "error");
  }
}

// 메시지 1개를 화면에 추가
function addMessage(m) {
  // 이미 화면에 있는 메시지면 중복 추가하지 않기 (전송 직후 + 폴링이 겹칠 때 대비)
  if ($messages.querySelector(`[data-id="${m.id}"]`)) return;

  const li = document.createElement("li");
  li.dataset.id = m.id;

  if (m.kind === "system") {
    li.className = "system";
  } else if (m.nickname === myNickname) {
    li.className = "mine";
  }

  if (m.kind !== "system") {
    const who = document.createElement("span");
    who.className = "who";
    who.textContent = `${m.nickname} · ${formatTime(m.ts)}`;
    li.appendChild(who);
  }

  const bubble = document.createElement("span");
  bubble.className = "bubble";
  bubble.textContent = m.text;     // textContent → XSS 방지
  li.appendChild(bubble);

  // 사용자가 맨 아래를 보고 있을 때만 자동으로 스크롤 내리기
  const nearBottom = $messages.scrollHeight - $messages.scrollTop - $messages.clientHeight < 60;
  $messages.appendChild(li);
  if (nearBottom) $messages.scrollTop = $messages.scrollHeight;
}

// =====================================================================
// 기능 3-2: 메시지 전송
// =====================================================================
$sendForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const m = await api(`/api/rooms/${currentRoom.id}/messages`, {
      method: "POST",
      body: JSON.stringify({ nickname: myNickname, text: $messageInput.value }),
    });
    $messageInput.value = "";
    showMsg($sendMsg, "");
    addMessage(m);                              // 내 화면엔 바로 표시
    $messages.scrollTop = $messages.scrollHeight;
  } catch (err) {
    showMsg($sendMsg, err.message, "error");   // 예: "메시지를 입력하세요."
  }
});

// =====================================================================
// 페이지가 처음 열렸을 때 실행
// =====================================================================
loadRooms();
roomTimer = setInterval(loadRooms, 3000);
