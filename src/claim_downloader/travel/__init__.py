"""출장증빙자료 만들기 — 지원 항목별 증빙 + 출장 경로 → '<이름> 출장증빙_yy.mm.dd.pdf'. CLAUDE.md 28절.

model.py 는 Qt 없이 쪽 짜임 · 숙박 지원금액을 정하고(tests/test_travel.py), render.py 가 그 짜임을 PDF 로 그린다(PySide6).
"""
