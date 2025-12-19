// static/pwa-push.js
let swRegistration = null;

async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  swRegistration = await navigator.serviceWorker.register("/service-worker.js");
}

async function getVapidPublicKey() {
  const r = await fetch("/api/push/vapidPublicKey");
  const j = await r.json();
  return j.publicKey;
}

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
}

async function enablePush() {
  const perm = await Notification.requestPermission();
  if (perm !== "granted") return alert("권한 거부");

  const key = await getVapidPublicKey();
  const sub = await swRegistration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(key),
  });

  await fetch("/api/push/subscribe", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify(sub),
  });

  alert("알림 설정 완료");
}

async function pushTest() {
  await fetch("/api/push/send-test", {method:"POST"});
  alert("푸시 테스트 전송");
}

window.addEventListener("load", registerServiceWorker);
window.enablePush = enablePush;
window.pushTest = pushTest;
