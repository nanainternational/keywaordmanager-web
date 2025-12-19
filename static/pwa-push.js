// static/pwa-push.js
// iOS/Android PWA Push 공통용 (Safari iOS 16.4+ 필요)

let swReg = null;

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
}

async function registerSW() {
  if (!("serviceWorker" in navigator)) return;
  try {
    swReg = await navigator.serviceWorker.register("/service-worker.js");
    console.log("[PWA] SW registered");
  } catch (e) {
    console.error("[PWA] SW register fail", e);
  }
}

async function fetchVapidPublicKey() {
  const r = await fetch("/api/push/vapidPublicKey", { cache: "no-store" });
  const j = await r.json();
  return j && j.publicKey ? j.publicKey : "";
}

async function enablePush() {
  try {
    if (!swReg) await registerSW();
    if (!swReg) throw new Error("ServiceWorker not ready");

    const perm = await Notification.requestPermission();
    if (perm !== "granted") {
      alert("알림 권한이 거부되었습니다.");
      return;
    }

    const publicKey = await fetchVapidPublicKey();
    if (!publicKey) {
      alert("알림 설정 실패: No VAPID public key");
      return;
    }

    // 기존 구독이 있으면 재사용
    let sub = await swReg.pushManager.getSubscription();
    if (!sub) {
      sub = await swReg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey),
      });
    }

    const r = await fetch("/api/push/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(sub),
    });

    const j = await r.json();
    if (!j.ok) throw new Error(j.error || "subscribe failed");

    alert("알림 설정 완료 ✅");
  } catch (e) {
    console.error(e);
    alert("알림 설정 실패: " + (e && e.message ? e.message : e));
  }
}

async function pushTest() {
  try {
    const r = await fetch("/api/push/send-test", { method: "POST" });
    const j = await r.json();
    if (j.ok) alert("푸시 테스트 요청 완료 ✅ (잠시 후 확인)");
    else alert("푸시 테스트 실패: " + (j.error || ""));
  } catch (e) {
    alert("푸시 테스트 오류: " + (e && e.message ? e.message : e));
  }
}

window.addEventListener("load", registerSW);
window.enablePush = enablePush;
window.pushTest = pushTest;
