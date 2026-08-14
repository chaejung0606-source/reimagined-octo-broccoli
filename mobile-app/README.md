# 포켓 다이어리 (모바일 웹앱)

따뜻한 레트로 감성의 모바일 UI — 할 일 · 한 줄 일기 · 사진 컬렉션.

## 실행

```bash
cd mobile-app
python3 -m http.server 8080
# 휴대폰/브라우저에서 http://localhost:8080 접속
```

빌드 도구 없이 정적 파일만으로 동작합니다.

## 이미지 에셋

캐릭터 사진은 `assets/images/` 폴더의 **소장 원본 파일**을 그대로 표시합니다.
필요한 파일명과 쓰이는 위치는 [assets/images/README.md](assets/images/README.md) 참고.
이 폴더는 공개 저장소에 커밋되지 않으며(.gitignore), 파일이 없으면
대체 그림 없이 텍스트 안내만 나옵니다.
