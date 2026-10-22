"""공무확인증 관리대장 — 구글 시트 연동. Qt 없음.

담당자 2026-10-22: "주차관제시스템에 할인내역을 구글시트에 저장하고 그 구글시트를 연동해서 어플에서 관리대장을 확인할 수 있도록".

길: 담당자가 자기 구글 계정에 시트를 하나 만들고, 앱이 만들어 준 Apps Script(SCRIPT)를 그 시트에 붙여 '웹 앱' 으로 배포한 뒤 그 주소를
설정에 넣는다. 앱은 그 주소로 JSON 을 주고받는다(urllib — 새 의존성 없음 · 구글 클라우드 설정 없음).
- '할인내역' 탭: 사이트 '운영 → 할인 내역' 에서 읽은 줄을 쌓는다(같은 할인일시 · 차량번호는 한 번만). 사이트는 처음 쪽만 보여 주지만 시트에는 계속 쌓인다.
- '관리대장' 탭: 앱의 공무확인증 관리대장과 같은 것(parking_ledger.SHEET_HEAD). 앱은 시트를 읽어 이 PC 의 사본과 줄 id 로 맞추고(parking_ledger.merge)
  맞춘 대장을 시트에 다시 쓴다 — 시트에서 고친 줄은 스크립트가 '수정시각' 을 찍어 앱보다 늦으면 시트 것이 이긴다.
웹 앱은 '모든 사용자' 접근으로 배포해야 앱이 로그인 없이 부를 수 있다 — 그래서 앱이 만든 토큰을 스크립트에 넣어, 토큰이 없는 요청은 아무것도 주지 않는다.
주소 · 토큰은 이 PC 의 `_구글시트연동.json` 에만(저장소 · 배포 · 기록에는 두지 않는다). 시트의 줄(이름 · 차량번호)은 기록에 남기지 않는다.
"""
from __future__ import annotations

import json
import secrets
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from . import parking_ledger as ledger
from . import settings

TIMEOUT = 40          # 구글 웹 앱은 처음 부를 때 몇 초 걸린다

# 담당자가 시트의 확장 프로그램 → Apps Script 에 붙여 넣는 글. __TOKEN__ 은 앱이 바꿔 넣는다(script_text).
SCRIPT = r"""// COSS 업무데스크 — 공무확인증 관리대장 연동 스크립트 (앱이 만든 글입니다. 고치지 마세요)
// 배포: 배포 → 새 배포 → 유형 '웹 앱' · 실행 사용자 '나' · 액세스 권한 '모든 사용자' → 배포 → 웹 앱 URL 을 앱 설정에 붙여 넣기
const TOKEN = '__TOKEN__';
const LEDGER = '관리대장';
const HISTORY = '할인내역';
const LEDGER_HEAD = ['일자', '구입', '배부', '잔여', '내용', '사용자', '차량번호', '비고', '적은 곳', 'id', '수정시각', '적은 때'];
const TEXT_COLS = [1, 10, 11, 12];   // 날짜 · id · 시각은 글자 그대로(시트가 날짜로 바꾸지 않게)

function doGet(e) {
  return ContentService.createTextOutput('COSS 업무데스크 관리대장 연동 스크립트가 켜져 있습니다. 이 주소를 앱 설정에 넣으세요.');
}

function doPost(e) {
  let body;
  try { body = JSON.parse(e.postData.contents); } catch (err) { return out({ok: false, error: '요청을 읽지 못했습니다'}); }
  if (!body || body.token !== TOKEN) return out({ok: false, error: '토큰이 다릅니다 — 앱 설정에서 스크립트를 다시 복사해 붙여 넣으세요'});
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const ss = SpreadsheetApp.getActive();
    const info = {name: ss.getName(), url: ss.getUrl()};
    if (body.action === 'ping') { ledgerSheet(); return out(Object.assign({ok: true}, info)); }
    if (body.action === 'ledger_get') return out(Object.assign({ok: true, rows: readLedger()}, info));
    if (body.action === 'ledger_put') { writeLedger(body.rows || []); return out(Object.assign({ok: true, count: (body.rows || []).length}, info)); }
    if (body.action === 'history_add') return out(Object.assign({ok: true, added: addHistory(body.headers || [], body.rows || [], body.keys || [])}, info));
    return out({ok: false, error: '모르는 요청: ' + body.action});
  } finally {
    lock.releaseLock();
  }
}

function out(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function ledgerSheet() {
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName(LEDGER);
  if (!sh) sh = ss.insertSheet(LEDGER, 0);
  if (sh.getLastRow() === 0) {
    sh.getRange(1, 1, 1, LEDGER_HEAD.length).setValues([LEDGER_HEAD]).setFontWeight('bold');
    sh.setFrozenRows(1);
    sh.hideColumns(10, 3);   // id · 수정시각 · 적은 때 — 맞추기에 쓰는 칸
  }
  return sh;
}

function readLedger() {
  const sh = ledgerSheet();
  const n = sh.getLastRow();
  if (n < 2) return [];
  return sh.getRange(2, 1, n - 1, LEDGER_HEAD.length).getDisplayValues().filter(r => r.some(c => c !== ''));
}

function writeLedger(rows) {
  const sh = ledgerSheet();
  const n = sh.getLastRow();
  if (n > 1) sh.getRange(2, 1, n - 1, LEDGER_HEAD.length).clearContent();
  if (!rows.length) return;
  TEXT_COLS.forEach(c => sh.getRange(2, c, rows.length, 1).setNumberFormat('@'));
  sh.getRange(2, 1, rows.length, LEDGER_HEAD.length).setValues(rows.map(r => LEDGER_HEAD.map((h, i) => r[i] === undefined || r[i] === null ? '' : r[i])));
}

// 사람이 시트에서 고친 줄 — 수정시각을 찍어 앱과 맞출 때 이 줄이 이기게, 새로 적은 줄에는 id 를 준다
function onEdit(e) {
  const sh = e.range.getSheet();
  if (sh.getName() !== LEDGER || e.range.getLastRow() < 2) return;
  const now = new Date().toISOString();
  for (let r = Math.max(2, e.range.getRow()); r <= e.range.getLastRow(); r++) {
    const row = sh.getRange(r, 1, 1, LEDGER_HEAD.length);
    const v = row.getValues()[0];
    if (v.slice(0, 9).every(c => c === '')) continue;
    sh.getRange(r, 11).setNumberFormat('@').setValue(now);
    if (!v[9]) sh.getRange(r, 10).setNumberFormat('@').setValue(Utilities.getUuid().replace(/-/g, ''));
  }
}

function addHistory(headers, rows, keys) {
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName(HISTORY);
  if (!sh) sh = ss.insertSheet(HISTORY);
  const head = ['저장한 때'].concat(headers).concat(['키']);
  if (sh.getLastRow() === 0) {
    sh.getRange(1, 1, 1, head.length).setValues([head]).setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  const width = Math.max(sh.getLastColumn(), head.length);
  const have = sh.getRange(1, 1, 1, width).getDisplayValues()[0];
  const keyCol = have.indexOf('키') + 1;
  const n = sh.getLastRow();
  const seen = new Set(keyCol > 0 && n > 1 ? sh.getRange(2, keyCol, n - 1, 1).getDisplayValues().map(r => r[0]) : []);
  const now = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm');
  const add = [];
  rows.forEach((row, i) => {
    const key = keys[i] || row.join('|');
    if (seen.has(key)) return;
    seen.add(key);
    // 시트 머리글 이름으로 칸을 맞춘다(사이트의 열 차례가 바뀌어도)
    const line = have.map(h => h === '저장한 때' ? now : h === '키' ? key : (headers.indexOf(h) >= 0 ? row[headers.indexOf(h)] : ''));
    add.push(line);
  });
  if (add.length) {
    sh.getRange(n + 1, 1, add.length, width).setNumberFormat('@').setValues(add);
  }
  return add.length;
}
"""


# ── 설정(이 PC 에만) ──────────────────────────────────────────────────────
@dataclass
class Config:
    url: str = ""
    token: str = ""
    sheet_url: str = ""
    sheet_name: str = ""

    @property
    def connected(self) -> bool:
        return bool(self.url and self.token)


def load_config() -> Config:
    try:
        data = json.loads(settings.parking_sheet_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Config()
    return Config(**{k: str(data.get(k, "")) for k in ("url", "token", "sheet_url", "sheet_name")})


def save_config(config: Config) -> None:
    target = settings.parking_sheet_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(config.__dict__, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(target)


def forget() -> None:
    try:
        settings.parking_sheet_path().unlink()
    except OSError:
        pass


def script_text(config: Config | None = None) -> tuple[str, Config]:
    """붙여 넣을 스크립트 — 토큰이 없으면 새로 만들어 남긴다(같은 토큰을 다시 쓴다: 스크립트를 다시 복사해도 연동이 끊기지 않게)."""
    config = config or load_config()
    if not config.token:
        config.token = secrets.token_urlsafe(24)
        save_config(config)
    return SCRIPT.replace("__TOKEN__", config.token), config


def looks_like_web_app(url: str) -> bool:
    url = (url or "").strip()
    return url.startswith("https://script.google.com/") and url.rstrip("/").endswith("/exec")


# ── 부르기 ───────────────────────────────────────────────────────────────
class SheetError(RuntimeError):
    pass


def call(config: Config, action: str, opener=None, **payload) -> dict:
    """웹 앱에 POST — 구글은 302 로 결과 주소를 돌려주고 urllib 가 GET 으로 따라간다."""
    if not config.connected:
        raise SheetError("구글 시트가 연결돼 있지 않습니다 — 설정 → '관리대장 구글 시트' 에서 연결하세요")
    body = json.dumps(dict(payload, action=action, token=config.token), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(config.url.strip(), data=body, method="POST",
                                     headers={"Content-Type": "text/plain;charset=utf-8"})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=TIMEOUT) as response:
            text = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        raise SheetError(f"구글 시트에 닿았지만 거절됐습니다(HTTP {error.code}) — 배포 주소가 맞는지 보세요") from error
    except (urllib.error.URLError, OSError) as error:
        raise SheetError("구글 시트에 닿지 못했습니다 — 인터넷 연결을 보세요 (" + str(getattr(error, "reason", error))[:80] + ")") from error
    try:
        data = json.loads(text)
    except ValueError as error:
        raise SheetError("구글 시트의 답을 읽지 못했습니다 — 배포할 때 '액세스 권한' 을 '모든 사용자' 로 했는지, 주소가 '/exec' 로 끝나는지 보세요") from error
    if not data.get("ok"):
        raise SheetError("구글 시트: " + str(data.get("error") or "알 수 없는 오류"))
    return data


def _remember(config: Config, data: dict) -> None:
    if data.get("url") and (data.get("url") != config.sheet_url or data.get("name") != config.sheet_name):
        config.sheet_url, config.sheet_name = str(data.get("url")), str(data.get("name", ""))
        save_config(config)


@dataclass
class Result:
    ok: bool = False
    note: str = ""
    sheet_url: str = ""
    sheet_name: str = ""
    pulled: int = 0          # 시트에서 읽은 줄
    total: int = 0           # 맞춘 뒤 대장 줄
    changed: bool = False    # 이 PC 의 대장이 바뀌었는지(화면을 다시 그린다)
    added: int = 0           # 할인내역 탭에 더한 줄
    when: str = field(default_factory=lambda: time.strftime("%H:%M"))


def check(config: Config | None = None, opener=None) -> Result:
    """[연결 확인] — 토큰까지 맞는지(ping)."""
    config = config or load_config()
    try:
        data = call(config, "ping", opener=opener)
    except SheetError as error:
        return Result(note=str(error))
    _remember(config, data)
    return Result(ok=True, note=f"연결됐습니다 — 시트 '{data.get('name', '')}'", sheet_url=config.sheet_url, sheet_name=config.sheet_name)


def sync_ledger(config: Config | None = None, opener=None) -> Result:
    """시트의 '관리대장' 을 읽어 이 PC 의 대장과 맞추고(merge), 맞춘 대장을 시트에 다시 쓴다."""
    config = config or load_config()
    if not config.connected:
        return Result(note="연결 안 됨")
    try:
        data = call(config, "ledger_get", opener=opener)
        remote = ledger.from_sheet(data.get("rows") or [])
        with ledger._LOCK:
            local = ledger.load()
            synced, deleted = ledger.sync_state()
            merged = ledger.merge(local, remote, synced, deleted)
            before = [(e.id, e.updated) for e in ledger.ordered(local)]
            changed = before != [(e.id, e.updated) for e in merged]
            if changed:
                ledger.save(merged)
        call(config, "ledger_put", opener=opener, rows=ledger.to_sheet(merged))
        ledger.mark_synced({e.id for e in merged}, deleted)
    except SheetError as error:
        return Result(note=str(error), sheet_url=config.sheet_url, sheet_name=config.sheet_name)
    _remember(config, data)
    return Result(ok=True, note="맞춤", sheet_url=config.sheet_url, sheet_name=config.sheet_name, pulled=len(remote),
                  total=len(merged), changed=changed)


def push_history(headers: list[str], rows: list[list[str]], config: Config | None = None, opener=None) -> Result:
    """사이트 할인 내역의 줄을 '할인내역' 탭에 쌓는다 — 같은 할인일시 · 차량번호는 한 번만(키)."""
    config = config or load_config()
    if not config.connected or not rows:
        return Result(note="연결 안 됨" if not config.connected else "줄 없음")
    heads = [ledger.clean_header(h) for h in headers]
    date_col, car_col = ledger._column(heads, ledger.DATE_WORDS), ledger._column(heads, ledger.CAR_WORDS)
    keys = []
    for row in rows:
        cell = lambda c: row[c] if 0 <= c < len(row) else ""  # noqa: E731
        keys.append(f"{cell(date_col)}|{ledger._squash(cell(car_col))}" if date_col >= 0 and car_col >= 0 else "|".join(row))
    width = max([len(heads)] + [len(r) for r in rows])
    heads = heads + [f"칸 {i + 1}" for i in range(len(heads), width)]
    try:
        data = call(config, "history_add", opener=opener, headers=heads, rows=[list(r) + [""] * (width - len(r)) for r in rows], keys=keys)
    except SheetError as error:
        return Result(note=str(error))
    _remember(config, data)
    return Result(ok=True, note="쌓음", added=int(data.get("added") or 0), sheet_url=config.sheet_url, sheet_name=config.sheet_name)
