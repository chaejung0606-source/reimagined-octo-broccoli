"""공무확인증 관리대장 — 구글 시트 연동. Qt 없음.

담당자 2026-10-22: "주차관제시스템에 할인내역을 구글시트에 저장하고 그 구글시트를 연동해서 어플에서 관리대장을 확인할 수 있도록".

길: 담당자가 자기 구글 계정에 시트를 하나 만들고, 앱이 만들어 준 Apps Script(SCRIPT)를 그 시트에 붙여 '웹 앱' 으로 배포한 뒤 그 주소를
설정에 넣는다. 앱은 그 주소로 JSON 을 주고받는다(urllib — 새 의존성 없음 · 구글 클라우드 설정 없음).
- '할인내역' 탭: 사이트 '운영 → 할인 내역' 에서 읽은 줄을 쌓는다(같은 할인일시 · 차량번호는 한 번만). 사이트는 처음 쪽만 보여 주지만 시트에는 계속 쌓인다.
- '관리대장' 탭: 앱의 공무확인증 관리대장과 같은 것(parking_ledger.SHEET_HEAD). 앱은 시트를 읽어 이 PC 의 사본과 줄 id 로 맞추고(parking_ledger.merge)
  맞춘 대장을 시트에 다시 쓴다 — 시트에서 고친 줄은 스크립트가 '수정시각' 을 찍어 앱보다 늦으면 시트 것이 이긴다.
- '로그' 탭: 업무 화면의 [로그 보내기] 가 개인정보를 가린 실행 기록을 보낸다(log_send.py, 담당자 2026-10-22 — 깃허브 대신 구글 시트).
  스크립트의 doGet 이 열쇠(log_key)가 맞는 요청에만 그 기록을 글로 돌려준다 — 그 주소를 채팅에 붙이면 Claude 가 읽는다. 열쇠로는 기록만 읽힌다.
- '다운로드 현황' 탭: 증빙 다운로드의 건마다 청구서 · 구매요청 · 검사처리 서류를 받았는지 O/X(progress.py, 담당자 2026-10-23). 앱이 표를 통째로
  다시 쓰고(status_put) 스크립트가 서식(머리 고정 · 거르기 · 칸 너비 · O/X 색)을 입힌다 — 시트에서 고쳐도 다음에 쓸 때 덮인다(앱의 기록이 기준).
웹 앱은 '모든 사용자' 접근으로 배포해야 앱이 로그인 없이 부를 수 있다 — 그래서 앱이 만든 토큰을 스크립트에 넣어, 토큰이 없는 요청은 아무것도 주지 않는다.
주소 · 토큰은 이 PC 의 `_구글시트연동.json` 에만(저장소 · 배포 · 기록에는 두지 않는다). 시트의 줄(이름 · 차량번호)은 기록에 남기지 않는다.
"""
from __future__ import annotations

import http.client
import json
import re
import secrets
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import parking_ledger as ledger
from . import settings
from .minutes.logbook import log

TIMEOUT = 40          # 구글 웹 앱은 처음 부를 때 몇 초 걸린다
CONNECT_WAITS = (6, 10, 15)   # 주소 하나에 붙어 보는 시간 — 바퀴마다 길게. 구글은 보통 1초 안에 붙는다. 다 실패하면 다음 바퀴(_connect)
CONNECT_PAUSE = 1.0           # 바퀴 사이에 쉬는 시간

# 담당자가 시트의 확장 프로그램 → Apps Script 에 붙여 넣는 글. __TOKEN__ 은 앱이 바꿔 넣는다(script_text).
SCRIPT = r"""// COSS 업무데스크 — 공무확인증 관리대장 연동 스크립트 (앱이 만든 글입니다. 고치지 마세요)
// 배포: 배포 → 새 배포 → 유형 '웹 앱' · 실행 사용자 '나' · 액세스 권한 '모든 사용자' → 배포 → 웹 앱 URL 을 앱 설정에 붙여 넣기
// 이 글을 새로 붙여 넣었으면: 배포 → 배포 관리 → (연필) 수정 → 버전 '새 버전' → 배포 (주소는 그대로)
const TOKEN = '__TOKEN__';
const LOG_KEY = '__LOGKEY__';   // [로그 보내기] 로 쌓은 기록을 읽는 열쇠 — 기록만 읽힌다(관리대장은 TOKEN)
const LEDGER = '관리대장';
const HISTORY = '할인내역';
const LEDGER_HEAD = ['일자', '구입', '배부', '잔여', '내용', '사용자', '차량번호', '비고', '적은 곳', 'id', '수정시각', '적은 때'];
const TEXT_COLS = [1, 10, 11, 12];   // 날짜 · id · 시각은 글자 그대로(시트가 날짜로 바꾸지 않게)
const LOGS = '로그';
const LOG_HEAD = ['id', '보낸 때', '업무', '오류', '앱', '조각', '내용'];
const LOG_KEEP = 30;                  // 최근 30번 보낸 것만 남긴다
const STATUS = '다운로드 현황';        // 증빙 다운로드 — 건마다 청구서 · 구매요청 · 검사처리 O/X (앱이 통째로 다시 쓴다)
const MARK_STYLE = {'O': ['#1E7F37', '#D9EAD3'], 'X': ['#B3261E', '#F4CCCC'], '△': ['#8A6D00', '#FFF2CC'], '': ['#9E9E9E', '#E3E3E3']};

function doGet(e) {
  const p = (e && e.parameter) || {};
  if (p.key && LOG_KEY.indexOf('__') !== 0 && p.key === LOG_KEY) return ContentService.createTextOutput(readLog(String(p.id || '')));
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
    if (body.action === 'ping') { ledgerSheet(); return out(Object.assign({ok: true, logs: true, status: true}, info)); }
    if (body.action === 'log_add') return out(Object.assign({ok: true, id: addLog(body)}, info));
    if (body.action === 'status_put') return out(Object.assign({ok: true, count: writeStatus(body)}, info));
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

// ── 로그 보내기 — 앱이 개인정보를 가린 실행 기록을 보낸다. 칸 하나에 5만 자까지라 앱이 나눠 보낸 조각을 한 줄씩 ──
function logSheet() {
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName(LOGS);
  if (!sh) sh = ss.insertSheet(LOGS);
  if (sh.getLastRow() === 0) {
    sh.getRange(1, 1, 1, LOG_HEAD.length).setValues([LOG_HEAD]).setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  return sh;
}

function addLog(body) {
  const sh = logSheet();
  const zone = Session.getScriptTimeZone();
  const now = new Date();
  const id = Utilities.formatDate(now, zone, 'yyyyMMdd-HHmmss') + '-' + Utilities.getUuid().slice(0, 4);
  const when = Utilities.formatDate(now, zone, 'yyyy-MM-dd HH:mm:ss');
  const parts = (body.parts && body.parts.length) ? body.parts : [''];
  // 조각 앞에 '[조각 i/n]' 줄을 붙인다 — 글이 '=' · '+' 로 시작해 시트가 수식으로 읽지 않게. 읽을 때 뗀다
  const rows = parts.map((part, i) => [id, when, String(body.task || ''), String(body.error || '').slice(0, 500), String(body.version || ''),
    (i + 1) + '/' + parts.length, '[조각 ' + (i + 1) + '/' + parts.length + ']\n' + String(part)]);
  const start = sh.getLastRow() + 1;
  sh.getRange(start, 1, rows.length, LOG_HEAD.length).setNumberFormat('@').setValues(rows);
  const n = sh.getLastRow();
  const ids = sh.getRange(2, 1, n - 1, 1).getDisplayValues().map(r => r[0]);
  const order = Array.from(new Set(ids));
  if (order.length > LOG_KEEP) {
    const drop = new Set(order.slice(0, order.length - LOG_KEEP));
    let k = 0;
    while (k < ids.length && drop.has(ids[k])) k++;
    if (k > 0) sh.deleteRows(2, k);
  }
  return id;
}

// ── 다운로드 현황 — 앱이 표(머리글 · 줄)를 통째로 보내면 탭을 다시 쓰고 서식을 입힌다 ──
// body.marks: O/X 칸 번호(1부터) · body.amount: 금액 칸 · body.texts: 글자 서식 칸(번호 · 날짜) · body.widths: 칸 너비(px) · body.legend: 1행 설명
function writeStatus(body) {
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName(STATUS);
  if (!sh) sh = ss.insertSheet(STATUS, 0);
  const head = body.head || [], rows = body.rows || [], marks = body.marks || [], widths = body.widths || [];
  const width = Math.max(head.length, 1);
  const filter = sh.getFilter();
  if (filter) filter.remove();
  sh.clear();
  if (sh.getMaxRows() < rows.length + 2) sh.insertRowsAfter(sh.getMaxRows(), rows.length + 2 - sh.getMaxRows());
  if (sh.getMaxColumns() < width) sh.insertColumnsAfter(sh.getMaxColumns(), width - sh.getMaxColumns());
  sh.getRange(1, 1, 1, sh.getMaxColumns()).breakApart();
  sh.getRange(1, 1, 1, width).merge().setValue(String(body.legend || '')).setFontColor('#666666').setFontSize(9).setWrap(false);
  sh.getRange(2, 1, 1, width).setValues([head]).setFontWeight('bold').setBackground('#EEEAFB').setFontColor('#3B3366')
    .setHorizontalAlignment('center').setVerticalAlignment('middle');
  sh.setFrozenRows(2);
  sh.setFrozenColumns(Math.min(2, width));
  widths.forEach((w, i) => { if (w) sh.setColumnWidth(i + 1, w); });
  if (!rows.length) return 0;
  (body.texts || []).forEach(c => sh.getRange(3, c, rows.length, 1).setNumberFormat('@'));
  if (body.amount) sh.getRange(3, body.amount, rows.length, 1).setNumberFormat('#,##0').setHorizontalAlignment('right');
  const area = sh.getRange(3, 1, rows.length, width);
  area.setValues(rows.map(r => head.map((h, i) => r[i] === undefined || r[i] === null ? '' : r[i])));
  area.setWrapStrategy(SpreadsheetApp.WrapStrategy.CLIP).setVerticalAlignment('middle')
      .setBorder(true, true, true, true, true, true, '#DDDDDD', SpreadsheetApp.BorderStyle.SOLID);
  marks.forEach(c => {
    const col = sh.getRange(3, c, rows.length, 1);
    const vals = rows.map(r => String(r[c - 1] === undefined || r[c - 1] === null ? '' : r[c - 1]));
    col.setHorizontalAlignment('center').setFontWeight('bold').setFontSize(12);
    col.setFontColors(vals.map(v => [(MARK_STYLE[v] || MARK_STYLE[''])[0]]));
    col.setBackgrounds(vals.map(v => [(MARK_STYLE[v] || MARK_STYLE[''])[1]]));
  });
  sh.getRange(2, 1, rows.length + 1, width).createFilter();
  return rows.length;
}

// 읽기 — id 가 없으면 가장 최근 것, 'list' 면 남은 것의 목록
function readLog(id) {
  const sh = logSheet();
  const n = sh.getLastRow();
  if (n < 2) return '보낸 로그가 없습니다.';
  const rows = sh.getRange(2, 1, n - 1, LOG_HEAD.length).getDisplayValues();
  if (id === 'list') {
    const seen = {};
    const lines = [];
    rows.forEach(r => { if (!seen[r[0]]) { seen[r[0]] = true; lines.push([r[0], r[1], r[2], r[3].split('\n')[0]].join(' · ')); } });
    return lines.reverse().join('\n');
  }
  const want = id || rows[rows.length - 1][0];
  const mine = rows.filter(r => r[0] === want);
  if (!mine.length) return '그 로그가 없습니다: ' + want + ' (최근 ' + LOG_KEEP + '번만 남깁니다)';
  const h = mine[0];
  const head = ['id ' + h[0], '보낸 때 ' + h[1], '업무 ' + h[2], '앱 ' + h[4], '오류 ' + (h[3] || '없음'), '────────────────────'];
  return head.join('\n') + '\n' + mine.map(r => r[6].replace(/^\[조각 [^\]]*\]\n/, '')).join('');
}
"""


# ── 설정(이 PC 에만) ──────────────────────────────────────────────────────
@dataclass
class Config:
    url: str = ""
    token: str = ""
    sheet_url: str = ""
    sheet_name: str = ""
    log_key: str = ""        # [로그 보내기] 로 쌓은 기록을 읽는 열쇠 — 스크립트에 박힌다(TOKEN 과 따로: 이 열쇠로는 기록만 읽힌다)

    @property
    def connected(self) -> bool:
        return bool(self.url and self.token)


def load_config() -> Config:
    try:
        data = json.loads(settings.parking_sheet_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Config()
    return Config(**{k: str(data.get(k, "")) for k in ("url", "token", "sheet_url", "sheet_name", "log_key")})


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
    if not config.token or not config.log_key:
        config.token = config.token or secrets.token_urlsafe(24)
        config.log_key = config.log_key or secrets.token_hex(16)   # 글자만 — 스크립트의 '__' 확인과 겹치지 않게
        save_config(config)
    return SCRIPT.replace("__TOKEN__", config.token).replace("__LOGKEY__", config.log_key), config


def looks_like_web_app(url: str) -> bool:
    url = (url or "").strip()
    return url.startswith("https://script.google.com/") and url.rstrip("/").endswith("/exec")


# ── 부르기 ───────────────────────────────────────────────────────────────
class SheetError(RuntimeError):
    pass


class NetworkError(SheetError):
    """구글에 닿지도 못함(시트가 거절한 것이 아니다) — [연결 확인] 은 이때 network_report 로 까닭을 적는다."""


# 담당자 PC(2026-10-22): [저장하고 연결 확인] 이 '[WinError 10060] 연결된 구성원으로부터 응답이 없어 …' 로 끝났다. 같은 PC 에서 git(깃허브) ·
# Claude Code(node) · 브라우저는 인터넷에 닿는다. 파이썬 urllib 는 운영체제가 준 차례(대개 IPv6 먼저)대로 주소마다 운영체제가 포기할 때(약 21초)까지
# 기다린다 — 그래서 IPv4 를 먼저, 주소마다 짧게 붙어 본다. 이 판의 진단(같은 날 21:xx)이 실제 까닭을 보여 줬다: 구글 주소 몇 개가 **잠깐씩 응답하지 않는다** —
# script.googleusercontent.com(302 로 돌린 결과 주소) 의 IPv4 하나가 12초 동안 응답이 없었는데 몇 초 뒤 진단에서는 0.0초에 붙었고, script.google.com 주소 넷 가운데
# 하나도 응답이 없었다. 브라우저는 이런 것을 저절로 다시 해 본다. 그래서 다 실패하면 이름을 다시 찾아(구글은 주소를 돌려 준다) 바퀴를 더 돈다(CONNECT_WAITS).
# 붙기 전에 실패한 것이라 보낸 것이 없다 — 시트의 일이 두 번 되지 않는다.
def _short(error: BaseException) -> str:
    code = getattr(error, "winerror", None) or getattr(error, "errno", None)
    if isinstance(error, (TimeoutError, socket.timeout)) or code in (10060, 110):
        return "응답 없음"
    if isinstance(error, ConnectionRefusedError) or code in (10061, 111):
        return "거절됨"
    if code in (10051, 10065, 101, 113):
        return "갈 길 없음"
    return (str(error).splitlines() or [type(error).__name__])[0][:60]


def _connect(address, timeout=None, source_address=None, *rest, **extra) -> socket.socket:
    """socket.create_connection 대신 — IPv4 주소 먼저, 주소마다 짧게, 다 실패하면 이름을 다시 찾아 한 바퀴 더(CONNECT_WAITS).
    끝내 못 붙으면 마지막 바퀴의 주소마다 까닭을 한 글로."""
    host, port = address[0], address[1]
    wait_total = timeout if isinstance(timeout, (int, float)) else socket.getdefaulttimeout()
    errors: list[str] = []
    first: list[str] = []
    for turn, limit in enumerate(CONNECT_WAITS):
        if turn:
            time.sleep(CONNECT_PAUSE)
        wait = min(wait_total, limit) if wait_total else limit
        infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
        infos.sort(key=lambda info: info[0] != socket.AF_INET)   # 같은 꼴 안에서는 운영체제 차례 그대로
        errors = []
        for family, kind, proto, _name, where in infos:
            sock = None
            try:
                sock = socket.socket(family, kind, proto)          # IPv6 를 못 쓰는 PC 면 여기서부터 실패 — 다음 주소로
                sock.settimeout(wait)
                if source_address:
                    sock.bind(source_address)
                sock.connect(where)
            except OSError as error:
                if sock is not None:
                    sock.close()
                errors.append(f"{'IPv6' if family == socket.AF_INET6 else 'IPv4'} {where[0]} {_short(error)}")
                continue
            sock.settimeout(wait_total)
            if turn:
                log(f"구글 연결: {host} 에 {turn + 1}번째에 붙음 (처음: {' · '.join(first)})")
            return sock
        first = first or errors
    if not errors:
        raise OSError(f"{host} 의 주소가 없음")
    raise OSError(f"{host} 에 붙지 못함({len(CONNECT_WAITS)}번 시도) — " + " · ".join(errors))


class _Https(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _connect          # HTTPConnection.connect 가 부르는 자리(프록시를 거칠 때도 같다)


class _HttpsHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        extra = {"check_hostname": self._check_hostname} if hasattr(self, "_check_hostname") else {}   # 3.11 까지의 꼴
        return self.do_open(_Https, req, context=self._context, **extra)


def _urlopen(request, timeout=TIMEOUT):
    """urllib.request.urlopen 과 같되 붙는 차례만 다르다(프록시 설정 · 302 따라가기는 그대로)."""
    return urllib.request.build_opener(_HttpsHandler()).open(request, timeout=timeout)


def call(config: Config, action: str, opener=None, **payload) -> dict:
    """웹 앱에 POST — 구글은 302 로 결과 주소를 돌려주고 urllib 가 GET 으로 따라간다."""
    if not config.connected:
        raise SheetError("구글 시트가 연결돼 있지 않습니다 — 설정 → '구글 시트 연동' 에서 연결하세요")
    body = json.dumps(dict(payload, action=action, token=config.token), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(config.url.strip(), data=body, method="POST",
                                     headers={"Content-Type": "text/plain;charset=utf-8"})
    try:
        with (opener or _urlopen)(request, timeout=TIMEOUT) as response:
            text = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        raise SheetError(f"구글 시트에 닿았지만 거절됐습니다(HTTP {error.code}) — 배포 주소가 맞는지 보세요") from error
    except (urllib.error.URLError, OSError) as error:
        raise NetworkError("구글 시트에 닿지 못했습니다 — 인터넷 연결을 보세요 (" + str(getattr(error, "reason", error))[:240] + ")") from error
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
    logs: bool = False       # 붙여 넣은 스크립트가 [로그 보내기] 를 받는 판인지(ping)
    status: bool = False     # 붙여 넣은 스크립트가 [다운로드 현황] 을 받는 판인지(ping)
    when: str = field(default_factory=lambda: time.strftime("%H:%M"))


REPORT_WAIT = 4.0     # 진단에서 주소 하나에 붙어 보는 시간


def _hide_login(text: str) -> str:
    """프록시 주소에 아이디 · 비밀번호가 섞여 있으면 가린다."""
    return re.sub(r"//[^/@\s]+@", "//***@", str(text))[:120]


def _windows_proxy() -> tuple[str, bool]:
    """윈도우 인터넷 옵션의 프록시 — 브라우저는 이것을 다 쓰지만 파이썬은 '프록시 서버' 만 읽고 '자동 구성 스크립트' 는 못 쓴다. (글, 자동 구성 스크립트가 있는지)."""
    if sys.platform != "win32":
        return "", False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            def value(name):
                try:
                    return winreg.QueryValueEx(key, name)[0]
                except OSError:
                    return None
            enable, server, pac = value("ProxyEnable"), value("ProxyServer"), value("AutoConfigURL")
    except Exception as error:  # noqa: BLE001 — 진단이 진단 때문에 멈추면 안 된다
        return f"읽지 못함 ({_short(error)})", False
    text = "프록시 서버 " + (f"켬 {_hide_login(server)}" if enable and server else "끔")
    text += " · 자동 구성 스크립트 " + (_hide_login(pac) if pac else "없음")
    return text, bool(pac)


def _probe(name: str, wait: float) -> tuple[str, bool]:
    """그 이름의 주소마다 443 에 붙어 보기만 한다(보내는 것 없음)."""
    try:
        infos = socket.getaddrinfo(name, 443, 0, socket.SOCK_STREAM)
    except OSError as error:
        return f"{name}: 주소를 찾지 못함 ({_short(error)})", False
    parts, ok, seen = [], False, set()
    for family, kind, proto, _name, where in infos:
        if where[0] in seen or len(seen) >= 4:
            continue
        seen.add(where[0])
        label = "IPv6" if family == socket.AF_INET6 else "IPv4"
        sock = None
        start = time.monotonic()
        try:
            sock = socket.socket(family, kind, proto)
            sock.settimeout(wait)
            sock.connect(where)
            parts.append(f"{label} {where[0]} 붙음({time.monotonic() - start:.1f}초)")
            ok = True
        except OSError as error:
            parts.append(f"{label} {where[0]} {_short(error)}")
        finally:
            if sock is not None:
                sock.close()
    return f"{name}: " + (" · ".join(parts) or "주소 없음"), ok


def network_report(url: str = "", wait: float = REPORT_WAIT) -> list[str]:
    """구글에 닿지 못했을 때 무엇이 막혔는지 — 첫 줄은 할 일, 다음은 주소마다 붙어 본 결과 · 프록시 설정. 주소 · 설정만 적는다(개인정보 없음).
    깃허브는 견줌용이다 — 앱 업데이트(git)가 되는 PC 면 그곳에는 닿는다."""
    host = urllib.parse.urlsplit(url or "").hostname or "script.google.com"
    google, google_ok = _probe(host, wait)
    content, content_ok = _probe("script.googleusercontent.com", wait)
    github, github_ok = _probe("github.com", wait)
    proxies = {key: _hide_login(value) for key, value in urllib.request.getproxies().items()}
    windows, pac = _windows_proxy()
    if google_ok and content_ok:
        hint = "지금은 구글에 붙습니다 — [저장하고 연결 확인] 을 다시 눌러 보세요(잠깐 끊겼던 것으로 보입니다)."
    elif pac and not proxies:
        hint = "이 PC 의 브라우저는 '자동 구성 스크립트'(프록시)로 인터넷에 나가는데 앱은 그것을 쓰지 못합니다 — 이 화면을 Claude 에게 보내 주세요."
    elif github_ok:
        hint = "깃허브(앱 업데이트)에는 붙는데 구글에는 못 붙습니다 — 학교망이나 이 PC 의 보안 프로그램이 앱의 구글 연결을 막는 것으로 보입니다. 이 화면을 Claude 에게 보내 주세요."
    else:
        hint = "구글 · 깃허브 모두 붙지 못합니다 — 이 PC 의 인터넷 연결을 보세요."
    lines = [hint, google, content, github, "앱(파이썬)이 쓰는 프록시: " + (", ".join(f"{k}={v}" for k, v in sorted(proxies.items())) or "없음")]
    if windows:
        lines.append("윈도우 인터넷 설정: " + windows)
    return lines


def check(config: Config | None = None, opener=None) -> Result:
    """[연결 확인] — 토큰까지 맞는지(ping). 구글에 닿지도 못했으면 까닭을 살펴 기록 · 화면에 적는다(network_report)."""
    config = config or load_config()
    try:
        data = call(config, "ping", opener=opener)
    except NetworkError as error:
        lines = network_report(config.url)
        log(f"구글 시트 연결 확인 실패 — {error}")
        for line in lines:
            log("   진단: " + line)
        return Result(note=f"{error}\n\n진단 — " + "\n".join(lines))
    except SheetError as error:
        return Result(note=str(error))
    _remember(config, data)
    return Result(ok=True, note=f"연결됐습니다 — 시트 '{data.get('name', '')}'", sheet_url=config.sheet_url, sheet_name=config.sheet_name,
                  logs=bool(data.get("logs")), status=bool(data.get("status")))


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
