// static/pwa-push.js

let swRegistration = null;

async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) {
    alert("이 브라우저는 Service Worker를 지원하지 않습니다.");
    return;
  }

  swRegistration = await navigator.serviceWorker.register("/service-worker.js");
  console.log("[PWA] Service Worker registered");
}

async function getVapidPublicKey() {
  const res = await fetch("/api/push/vapidPublicKey");
  const data = await res.json();
  return data.publicKey;
}

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding)
    .replace(/-/g, "+")
    .replace(/_/g, "/");

  const rawData = window.atob(base64);
  return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
}

async function enablePush() {
  try {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      alert("알림 권한이 거부되었습니다.");
      return;
    }

    const vapidKey = await getVapidPublicKey();
    if (!vapidKey) {
      alert("VAPID public key 없음");
      return;
    }

    const subscription = await swRegistration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidKey),
    });

    await fetch("/api/push/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(subscription),
    });

    alert("알림 설정 완료 ✅");
  } catch (e) {
    console.error(e);
    alert("알림 설정 실패: " + e.message);
  }
}

async function pushTest() {
  try {
    const res = await fetch("/api/push/send-test", { method: "POST" });
    const data = await res.json();
    if (data.ok) {
      alert("푸시 테스트 요청 완료 ✅ (잠시 후 확인)");
    } else {
      alert("푸시 테스트 실패");
    }
  } catch (e) {
    alert("푸시 테스트 오류: " + e.message);
  }
}

window.addEventListener("load", registerServiceWorker);
window.enablePush = enablePush;
window.pushTest = pushTest;
