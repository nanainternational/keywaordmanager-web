/* pwa-push.js */
function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) outputArray[i] = rawData.charCodeAt(i);
  return outputArray;
}

async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return null;
  const reg = await navigator.serviceWorker.register("/service-worker.js");
  return reg;
}

async function getVapidPublicKey() {
  const r = await fetch("/api/push/vapidPublicKey", { credentials: "same-origin" });
  const j = await r.json();
  if (!j || !j.ok || !j.publicKey) throw new Error("No VAPID public key");
  return j.publicKey;
}

async function ensurePushSubscription(sender) {
  if (!("PushManager" in window) || !("Notification" in window)) {
    alert("이 기기/브라우저는 Push를 지원하지 않습니다.");
    return;
  }

  const perm = await Notification.requestPermission();
  if (perm !== "granted") {
    alert("알림 권한이 허용되지 않았습니다.");
    return;
  }

  const reg = await registerServiceWorker();
  if (!reg) {
    alert("서비스워커 등록 실패");
    return;
  }

  const vapidPublicKey = await getVapidPublicKey();
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
    });
  }

  const res = await fetch("/api/push/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ sender, subscription: sub }),
  });
  const j = await res.json();
  if (!j || !j.ok) throw new Error(j && j.error ? j.error : "subscribe failed");
  return j;
}

async function testPush(sender) {
  const res = await fetch("/api/push/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ sender }),
  });
  const j = await res.json();
  if (!j || !j.ok) throw new Error(j && j.error ? j.error : "test failed");
  return j;
}


function isStandalonePWA() {
  return (
    (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
    window.navigator.standalone === true
  );
}

// ✅ iOS: 반드시 버튼 클릭(유저 제스처)에서 이 함수들을 호출해야 알림 팝업이 뜹니다.
window.pwaEnableNotifications = async function (sender) {
  try {
    if (!isStandalonePWA()) {
      alert("iPhone에서는 홈 화면에 추가한 앱(PWA)에서 '알림 켜기'를 눌러야 팝업이 뜹니다.");
    }
    const name = (sender || "익명").toString().trim() || "익명";
    const j = await ensurePushSubscription(name);
    if (j && j.ok) alert("✅ 알림 권한/구독 완료");
  } catch (e) {
    alert("알림 설정 실패: " + (e && e.message ? e.message : e));
  }
};

window.pwaTestPush = async function (sender) {
  try {
    const name = (sender || "익명").toString().trim() || "익명";
    const j = await testPush(name);
    if (j && j.ok) alert("✅ 푸시 테스트 요청 완료 (잠시 후 알림 확인)");
  } catch (e) {
    alert("푸시 테스트 실패: " + (e && e.message ? e.message : e));
  }
};
