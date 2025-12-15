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
        self.root.geometry("400x250")

        # 상태
        self.running = False
        self.ping_thread = None

        # URL 입력창
        self.url_entry = ctk.CTkEntry(
            self.root,
            placeholder_text="https://your-app.onrender.com/"
        )
        self.url_entry.insert(0, "https://nana-renewal-backend.onrender.com/")
        self.url_entry.pack(pady=20, padx=20, fill="x")

        # 로그 출력
        self.log_text = ctk.CTkTextbox(self.root, height=80)
        self.log_text.pack(padx=20, pady=(0, 10), fill="both")

        # 버튼 영역
        self.start_button = ctk.CTkButton(
            self.root,
            text="▶️ 시작",
            command=self.start_pinging
        )
        self.start_button.pack(pady=5)

        self.stop_button = ctk.CTkButton(
            self.root,
            text="⏹️ 중지",
            command=self.stop_pinging,
            state="disabled"
        )
        self.stop_button.pack(pady=5)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.mainloop()

    def start_pinging(self):
        url = self.url_entry.get().strip()
        if not url:
            self.log("❌ URL을 입력하세요.")
            return

        self.running = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

        self.ping_thread = threading.Thread(
            target=self.ping_loop,
            args=(url,),
            daemon=True
        )
        self.ping_thread.start()

        self.log(f"✅ {url} 에 5분마다 Ping 시작!")

    def stop_pinging(self):
        self.running = False
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.log("⏹️ Ping 중지됨.")

    def ping_loop(self, url):
        while self.running:
            try:
                response = requests.get(url, timeout=10)
                self.log(f"[{time.strftime('%H:%M:%S')}] 상태: {response.status_code}")
            except Exception as e:
                self.log(f"⚠️ 에러: {e}")

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
