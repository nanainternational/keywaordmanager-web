# iOS 먼저: PWA Web Push 최소 세팅

## 0) iOS에서 "푸시" 되려면 (중요)
- iOS/iPadOS 16.4+에서 지원
- Safari 탭이 아니라 "홈 화면에 추가된 웹앱(PWA)"에서만 푸시 구독/수신 가능

## 1) 파일 추가
- /manifest.webmanifest
- /service-worker.js
- /static/pwa-push.js
- /static/icons/icon-192.png, icon-512.png (임시로 아무 png라도 OK)

## 2) HTML(head)에 추가
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/static/icons/icon-192.png">
<meta name="theme-color" content="#0b0d10">

## 3) 화면에 버튼 2개 추가
- "알림 켜기" → ensurePushSubscription(sender)
- "푸시 테스트" → testPush(sender)

## 4) 서버(Flask)
- requirements.txt: pywebpush py-vapid 추가
- app.py에서 bp 등록:
    from push_routes import bp_push
    app.register_blueprint(bp_push)

## 5) VAPID 키 생성 (서버에서 1번만)
pip install py-vapid
vapid --gen
vapid --applicationServerKey
