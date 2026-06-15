import os
import telebot
from google import genai
from google.genai import types
from google.cloud import texttospeech
import google.auth

# --- МИКРО-СЕРВЕР ДЛЯ ОБХОДА БЕСПЛАТНОГО ТАРИФА ---
import http.server
import socketserver
from threading import Thread

class DummyWebServer(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Бот работает!".encode("utf-8"))

def run_dummy_server():
    # Render сам передает порт в переменную окружения PORT
    port = int(os.environ.get("PORT", 8080))
    # Разрешаем повторное использование порта
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), DummyWebServer) as httpd:
        print(f"Микро-сервер запущен на порту {port}")
        httpd.serve_forever()
# --------------------------------------------------

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
PROJECT_ID = os.environ.get('GOOGLE_CLOUD_PROJECT')
LOCATION = "us-central1"

os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID
credentials, _ = google.auth.default(quota_project_id=PROJECT_ID)

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
ai_client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
tts_client = texttospeech.TextToSpeechClient(credentials=credentials)

CLEANUP_PROMPT = "Прослушай аудиозапись, сделай расшифровку и причеши текст от заиканий и мусора."

def generate_voice(text, voice_name="ru-RU-Chirp3-HD-Aoede"):
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(language_code="ru-RU", name=voice_name)
    audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
    response = tts_client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)
    return response.audio_content

@bot.message_handler(content_types=['voice', 'audio'])
def handle_audio(message):
    try:
        bot.reply_to(message, "⏳ Обрабатываю аудио...")
        if message.voice:
            file_info = bot.get_file(message.voice.file_id)
            mime_type = "audio/ogg"
        else:
            file_info = bot.get_file(message.audio.file_id)
            mime_type = "audio/mpeg"

        downloaded_file = bot.download_file(file_info.file_path)

        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[types.Part.from_bytes(data=downloaded_file, mime_type=mime_type), CLEANUP_PROMPT]
        )
        bot.reply_to(message, f"📝 **Текст:**\n\n{response.text}", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")

if __name__ == "__main__":
    # 1. Сначала запускаем микро-сервер в отдельном потоке
    Thread(target=run_dummy_server, daemon=True).start()
    
    # 2. Затем запускаем самого бота
    print("Бот запущен...")
    bot.infinity_polling()
