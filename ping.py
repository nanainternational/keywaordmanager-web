import customtkinter as ctk
import threading
import requests
import time

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

class KeepAliveGUI:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("Render Keep Alive GUI")
        self.root.geometry("400x330")

        # 상태
        self.running = False
        self.ping_thread = None

        # URL 1 (백엔드)
        self.url_entry1 = ctk.CTkEntry(self.root, placeholder_text="https://your-backend.onrender.com/")
        self.url_entry1.insert(0, "https://nana-renewal-backend.onrender.com/")
        self.url_entry1.pack(pady=(20, 10), padx=20, fill="x")

        # URL 2 (키워드 매니저 웹)
        self.url_entry2 = ctk.CTkEntry(self.root, placeholder_text="https://your-web.onrender.com/")
        self.url_entry2.insert(0, "https://keywaordmanager-web.onrender.com/")
        self.url_entry2.pack(pady=(0, 15), padx=20, fill="x")

        # 로그 출력
        self.log_text = ctk.CTkTextbox(self.root, height=120)
        self.log_text.pack(padx=20, pady=(0, 10), fill="both")

        # 버튼
        self.start_button = ctk.CTkButton(self.root, text="▶️ 시작", command=self.start_pinging)
        self.start_button.pack(pady=5)

        self.stop_button = ctk.CTkButton(self.root, text="⏹️ 중지", command=self.stop_pinging, state="disabled")
        self.stop_button.pack(pady=5)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.mainloop()

    def start_pinging(self):
        url1 = self.url_entry1.get().strip()
        url2 = self.url_entry2.get().strip()

        if not url1 and not url2:
            self.log("❌ URL을 1개 이상 입력하세요.")
            return

        self.running = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

        self.ping_thread = threading.Thread(
            target=self.ping_loop,
            args=(url1, url2),
            daemon=True
        )
        self.ping_thread.start()

        self.log(f"✅ 5분마다 Ping 시작!")
        self.log(f"   - {url1}")
        self.log(f"   - {url2}")

    def stop_pinging(self):
        self.running = False
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.log("⏹️ Ping 중지됨.")

    def ping_loop(self, url1, url2):
        urls = [u for u in [url1, url2] if u]

        while self.running:
            for url in urls:
                if not self.running:
                    break
                try:
                    r = requests.get(url, timeout=10)
                    self.log(f"[{time.strftime('%H:%M:%S')}] {url} → {r.status_code}")
                except Exception as e:
                    self.log(f"⚠️ {url} 에러: {e}")

            for _ in range(300):  # 5분 = 300초
                if not self.running:
                    break
                time.sleep(1)

    def log(self, message):
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")

    def on_close(self):
        self.running = False
        self.root.destroy()

if __name__ == "__main__":
    KeepAliveGUI()
