// static/pwa-push.js (UPDATED)
// ✅ iOS/Safari 포함 Web Push 구독/테스트
// - HTML onclick에서 호출할 수 있도록 window.* 전역 함수로 등록

function _urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding)
    .replace(/-/g, '+')
    .replace(/_/g, '/');

  const rawData = atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

async function _getVapidPublicKey() {
  const res = await fetch('/api/push/vapidPublicKey', { cache: 'no-store' });
  const data = await res.json().catch(() => ({}));
  if (!data || !data.publicKey) throw new Error('No VAPID public key');
  return data.publicKey;
}

async function _ensureSW() {
  if (!('serviceWorker' in navigator)) {
    throw new Error('ServiceWorker not supported');
  }
  // index.html에서 register 했더라도, 혹시 대비해서 한 번 더 보장
  try {
    const reg = await navigator.serviceWorker.getRegistration('/');
    if (!reg) {
      await navigator.serviceWorker.register('/service-worker.js', { scope: '/' });
    }
  } catch (e) {
    // 등록 실패해도 ready에서 다시 터지므로 여기선 메시지 최소화
    console.log('[pwa] sw register err:', e);
  }
  return await navigator.serviceWorker.ready;
}

// ✅ HTML에서: onclick="pwaEnableNotifications(...)"
window.pwaEnableNotifications = async function(senderName) {
  try {
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') {
      alert('알림 권한이 허용되지 않았습니다.');
      return;
    }

    const registration = await _ensureSW();
    const vapidKey = await _getVapidPublicKey();
    const applicationServerKey = _urlBase64ToUint8Array(vapidKey);

    // 이미 구독되어 있으면 재사용
    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey
      });
    }

    await fetch('/api/push/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(subscription)
    });

    alert('알림 설정 완료 ✅');
  } catch (e) {
    console.log('[pwa] enable err:', e);
    alert('알림 설정 실패: ' + (e && e.message ? e.message : e));
  }
};

// ✅ HTML에서: onclick="pwaTestPush(...)"
window.pwaTestPush = async function() {
  try {
    const res = await fetch('/api/push/test', { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    if (!data.ok) throw new Error(data.error || 'push_test_failed');
    alert('푸시 테스트 요청 완료 ✅ (잠시 후 알림 확인)');
  } catch (e) {
    console.log('[pwa] test err:', e);
    alert('푸시 테스트 실패: ' + (e && e.message ? e.message : e));
  }
};
