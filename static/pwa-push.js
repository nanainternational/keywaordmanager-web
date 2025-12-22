// static/pwa-push.js

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  return new Uint8Array([...rawData].map((c) => c.charCodeAt(0)));
}

async function registerSW() {
  if (!("serviceWorker" in navigator)) throw new Error("Service Worker not supported");
  const reg = await navigator.serviceWorker.register("/service-worker.js");
  return reg;
}

async function getVapidPublicKey() {
  const r = await fetch("/api/push/vapidPublicKey");
  const j = await r.json();
  if (!j || !j.publicKey) throw new Error("VAPID public key missing");
  return j.publicKey;
}

async function saveSubscriptionToServer(sub) {
  const res = await fetch("/api/push/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ subscription: sub }),
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`subscribe failed: ${res.status} ${text}`);
  return text;
}

window.pwaEnableNotifications = async function pwaEnableNotifications() {
  try {
    console.log("[PWA] enable clicked. perm(before) =", Notification.permission);

    const perm = await Notification.requestPermission();
    console.log("[PWA] perm(after) =", perm);
    if (perm !== "granted") {
      alert("알림 권한이 허용되지 않았습니다. 브라우저 설정에서 알림을 허용해주세요.");
      return;
    }

    const reg = await navigator.serviceWorker.ready;

    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      const vapidKey = await getVapidPublicKey();
      const appServerKey = urlBase64ToUint8Array(vapidKey);

      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: appServerKey,
      });
      console.log("[PWA] new subscription created");
    } else {
      console.log("[PWA] existing subscription found");
    }

    const saved = await saveSubscriptionToServer(sub);
    console.log("[PWA] subscription saved:", saved);

    alert("✅ 알림이 켜졌습니다!");
  } catch (e) {
    console.error("[PWA] enable error:", e);
    alert("❌ 알림 켜기 실패: " + (e && e.message ? e.message : e));
  }
};

window.pwaTestPush = async function pwaTestPush() {
  try {
    console.log("[PWA] test clicked");

    const res = await fetch("/api/push/send-test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: "푸시 테스트",
        body: "정상적으로 도착했습니다.",
        url: "/",
      }),
    });

    const text = await res.text();
    console.log("[PWA] send-test:", res.status, text);

    if (!res.ok) {
      alert("❌ 푸시 테스트 실패: " + res.status);
      return;
    }

    alert("✅ 푸시 발사 요청 완료! (알림이 뜨는지 확인)");
  } catch (e) {
    console.error("[PWA] test error:", e);
    alert("❌ 푸시 테스트 오류: " + (e && e.message ? e.message : e));
  }
};

(async () => {
  try {
    await registerSW();
    console.log("[PWA] SW registered");
  } catch (e) {
    console.error("[PWA] SW register failed:", e);
  }
})();
