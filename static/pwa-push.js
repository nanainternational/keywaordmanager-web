/* static/pwa-push.js */

async function registerSW() {
  if (!("serviceWorker" in navigator)) return null;
  try {
    const reg = await navigator.serviceWorker.register("/service-worker.js");
    return reg;
  } catch (e) {
    console.error("SW register failed:", e);
    return null;
  }
}

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; ++i) out[i] = raw.charCodeAt(i);
  return out;
}

async function subscribePush(reg) {
  // 서버에서 내려주는 공개키를 window.VAPID_PUBLIC_KEY로 주입하는 구조면 그대로 사용
  const vapidPublicKey = window.VAPID_PUBLIC_KEY || "";
  if (!vapidPublicKey) throw new Error("VAPID public key missing (window.VAPID_PUBLIC_KEY)");

  const subObj = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
  });

  return subObj.toJSON ? subObj.toJSON() : subObj;
}

async function saveSubscription(sub, platform, clientId) {
  const payload = { client_id: clientId || "", platform: platform || "", subscription: sub };

  const res = await fetch("/api/push/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const j = await res.json().catch(() => ({}));
  if (!res.ok || !j.ok) throw new Error(j.error || "subscribe_failed");
  return j;
}

function guessPlatform() {
  const ua = (navigator.userAgent || "").toLowerCase();
  if (ua.includes("android")) return "android";
  if (ua.includes("iphone") || ua.includes("ipad") || ua.includes("ipod")) return "ios";
  return "desktop";
}

// ✅ index.html에서 종(🔔) 버튼이 이걸 호출하게 만들면 됨.
window.enablePush = async function enablePush(options) {
  const clientId = options && options.clientId ? String(options.clientId) : "";
  const platform = options && options.platform ? String(options.platform) : guessPlatform();

  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error("permission_denied");

  const reg = await registerSW();
  if (!reg) throw new Error("sw_not_supported");

  const sub = await subscribePush(reg);
  await saveSubscription(sub, platform, clientId);

  return { ok: true };
};
