
// static/pwa-push.js (FIXED)

async function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
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

async function getVapidPublicKey() {
  const res = await fetch('/api/push/vapidPublicKey');
  const data = await res.json();
  if (!data.publicKey) throw new Error('No VAPID public key');
  return data.publicKey;
}

export async function enablePush() {
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') {
    alert('알림 권한 거부됨');
    return;
  }

  const registration = await navigator.serviceWorker.ready;
  const vapidKey = await getVapidPublicKey();
  const convertedKey = await urlBase64ToUint8Array(vapidKey);

  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: convertedKey
  });

  await fetch('/api/push/subscribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(subscription)
  });

  alert('알림 설정 완료');
}

export async function testPush() {
  await fetch('/api/push/test', { method: 'POST' });
  alert('푸시 테스트 요청 완료 (잠시 후 알림 확인)');
}
