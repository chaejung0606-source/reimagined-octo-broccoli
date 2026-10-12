"""회의록 생성 — 회의 자료 폴더에서 정산용 회의록(.hwpx)을 만들어 그 폴더 안에 둔다.

'회의록 자동 작성 도구'(jubilant-happiness 의 core.py)에서 옮겨 왔다(2026-10-12). 7개월치 회의록을
만들며 잡은 버그와 규칙이 코드에 녹아 있으므로 **새로 짜지 않았다.** hwpx.py · rules.py · errors.py 와
backends/claude_cli.py 의 프롬프트는 글자 하나 바꾸지 않는다. 배경은 그 저장소의 인수인계.md.

    회의 폴더 + 규칙(rules.py)  ──[ backends/ ]──▶  dict(schema.py)  ──▶  hwpx.py (실패 시 docx.py)

백엔드는 backends/base.py 의 규약(MinutesBackend) 하나만 지키면 된다. 1단계(지금)는 Claude Code CLI
하나다. API 백엔드(Anthropic · OpenAI · Gemini)는 담당자가 다시 요청할 때 base.py 만 보고 끼운다 —
화면(ui/pages/minutes.py)과 작업 스레드(ui/minutes_worker.py)는 고치지 않아도 되게 만들었다.

청구서 받기와는 독립이다. erp.py · session.py · targets.py · archive.py 를 읽지 않는다.
공유하는 것은 settings.py(설정·기록 위치)와 naming.UPLOAD_DIR(업로드 폴더 보호)뿐이다.
"""
from .process import MeetingResult, process_meeting, run

__all__ = ["MeetingResult", "process_meeting", "run"]
