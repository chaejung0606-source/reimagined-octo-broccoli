/* 포켓 다이어리 — 화면 전환, 할 일·일기(localStorage), 이미지 폴백.

   이미지 규칙: 캐릭터는 assets/images/ 의 소장 원본 파일만 표시한다.
   파일이 없으면 비슷한 그림·플레이스홀더로 대체하지 않고
   텍스트 안내만 보여 준다. */

(function () {
  "use strict";

  // ── 탭 전환 ────────────────────────────────────────
  const tabs = document.querySelectorAll(".tab");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".screen").forEach((s) => s.classList.remove("is-active"));
      tabs.forEach((t) => t.classList.remove("is-active"));
      document.getElementById(tab.dataset.tab).classList.add("is-active");
      tab.classList.add("is-active");
      window.scrollTo({ top: 0 });
    });
  });

  // ── 오늘 날짜 ──────────────────────────────────────
  const now = new Date();
  const week = ["일", "월", "화", "수", "목", "금", "토"];
  document.getElementById("today-label").textContent =
    `${now.getMonth() + 1}월 ${now.getDate()}일 ${week[now.getDay()]}요일`;

  // ── 이미지 폴백 — 대체 그림 없이 텍스트만 ─────────
  function showMissingNote(img) {
    const note = document.createElement("div");
    note.className = "img-missing";
    note.setAttribute("role", "note");
    note.textContent =
      `${img.dataset.missingNote || "이미지"}를 불러오지 못했습니다.\n` +
      `assets/images/ 폴더에 원본 파일을 넣어 주세요.`;
    img.replaceWith(note);
  }
  document.querySelectorAll("img.char-img").forEach((img) => {
    // 스크립트가 붙기 전에 이미 실패한 이미지는 error 이벤트가 다시 오지 않는다
    if (img.complete && img.naturalWidth === 0) {
      showMissingNote(img);
      return;
    }
    img.addEventListener("error", () => showMissingNote(img));
  });

  // ── 설정 화면의 에셋 상태 표시 ─────────────────────
  document.querySelectorAll("#asset-list li").forEach((item) => {
    const probe = new Image();
    probe.onload = () => { item.classList.add("ok"); item.querySelector("em").textContent = "연결됨"; };
    probe.onerror = () => { item.classList.add("missing"); item.querySelector("em").textContent = "파일 없음"; };
    probe.src = item.dataset.src;
  });

  // ── 할 일 (localStorage) ───────────────────────────
  const STORE_TODO = "pocket-diary.todos";
  const STORE_DIARY = "pocket-diary.diary";
  const listEl = document.getElementById("todo-list");
  const countEl = document.getElementById("todo-count");

  function loadTodos() {
    try { return JSON.parse(localStorage.getItem(STORE_TODO) || "[]"); }
    catch { return []; }
  }
  function saveTodos(todos) {
    localStorage.setItem(STORE_TODO, JSON.stringify(todos));
  }

  function render() {
    const todos = loadTodos();
    listEl.innerHTML = "";

    if (todos.length === 0) {
      const empty = document.createElement("li");
      empty.className = "todo-empty";
      empty.textContent = "아직 할 일이 없어요. 하나 적어 볼까요?";
      listEl.appendChild(empty);
    }

    todos.forEach((todo, index) => {
      const item = document.createElement("li");
      item.className = "todo-item" + (todo.done ? " done" : "");

      const check = document.createElement("button");
      check.className = "todo-check";
      check.setAttribute("aria-label", todo.done ? "완료 취소" : "완료로 표시");
      check.innerHTML = `<span class="box">${todo.done ? "✓" : ""}</span>`;
      check.addEventListener("click", () => {
        todos[index].done = !todos[index].done;
        saveTodos(todos); render();
      });

      const text = document.createElement("span");
      text.className = "todo-text";
      text.textContent = todo.text;

      const del = document.createElement("button");
      del.className = "todo-del";
      del.setAttribute("aria-label", "삭제");
      del.textContent = "✕";
      del.addEventListener("click", () => {
        todos.splice(index, 1);
        saveTodos(todos); render();
      });

      item.append(check, text, del);
      listEl.appendChild(item);
    });

    const remaining = todos.filter((t) => !t.done).length;
    countEl.textContent = remaining === 0 && todos.length > 0 ? "모두 완료!" : `${remaining}개 남음`;
  }

  document.getElementById("todo-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const input = document.getElementById("todo-input");
    const text = input.value.trim();
    if (!text) return;
    const todos = loadTodos();
    todos.push({ text, done: false });
    saveTodos(todos);
    input.value = "";
    render();
  });

  // ── 한 줄 일기 ─────────────────────────────────────
  const diary = document.getElementById("diary");
  diary.value = localStorage.getItem(STORE_DIARY) || "";
  diary.addEventListener("input", () => {
    localStorage.setItem(STORE_DIARY, diary.value);
    document.getElementById("diary-hint").textContent = "저장됐어요.";
  });

  // ── 기록 지우기 ────────────────────────────────────
  document.getElementById("clear-data").addEventListener("click", () => {
    if (!confirm("할 일과 일기를 모두 지울까요?")) return;
    localStorage.removeItem(STORE_TODO);
    localStorage.removeItem(STORE_DIARY);
    diary.value = "";
    render();
  });

  render();
})();
