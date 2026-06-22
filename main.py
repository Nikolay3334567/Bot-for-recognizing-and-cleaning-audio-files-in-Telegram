import os
import telebot
from google import genai
from google.genai import types as genai_types  # Для ИИ
from google.cloud import texttospeech
import google.auth
from telebot import types  # Оставляем классический types для Телеграма

# --- МИКРО-СЕРВЕР ДЛЯ ОБХОДА ОГРАНИЧЕНИЙ БЕСПЛАТНОГО ТАРИФА ---
import http.server
import socketserver
from threading import Thread

class DummyWebServer(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Бот работает!".encode("utf-8"))

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    # Разрешаем повторное использование порта
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(('', port), DummyWebServer) as httpd:
        print(f"Микро-сервер запущен на порту {port}")
        httpd.serve_forever()
# --------------------------------------------------


# === АВТОМАТИЧЕСКОЕ СОЗДАНИЕ ФАЙЛА С КЛЮЧАМИ GOOGLE ===
google_json = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON')
if google_json:
    # Создаем физический файл на диске сервера из текста в настройках Render
    with open('google-creds.json', 'w') as f:
        f.write(google_json)
    # Показываем библиотеке Google путь к созданному файлу
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'google-creds.json'
# ======================================================

# Читаем настройки из переменных окружения сервера
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
PROJECT_ID = os.environ.get('GOOGLE_CLOUD_PROJECT')
LOCATION = "us-central1"

# Инициализируем авторизацию с использованием нашего созданного файла
credentials, _ = google.auth.default()

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
ai_client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
tts_client = texttospeech.TextToSpeechClient(credentials=credentials)


# ========================================================
# 📋 ПЕРЕМЕННЫЕ НАСТРОЕК И ПРОМТОВ
# ========================================================

# 1. Дословная расшифровка
PROMPT_VERBATIM = """
Сделай максимально точную дословную текстовую расшифровку аудиозаписи. 
Записывай абсолютно все слова, даже если они повторяются из-за заикания. 
Не делай никакого литературного редактирования. Верни только чистый текст.
"""

# 2. Очистка и обработка текста
CLEANUP_PROMPT = "Прослушай аудиозапись, сделай расшифровку и причеши текст от заиканий и мусора."

# Временное хранилище аудиофайлов в памяти сервера
user_states = {}


# ========================================================
# 🛠️ ФУНКЦИИ И ОБРАБОТКА КОМАНД
# ========================================================

def process_audio_with_gemini(chat_id, prompt_text):
    """Отправляет сохраненную аудиозапись в Gemini с выбранным промтом"""
    state = user_states.get(chat_id)
    if not state or 'audio_bytes' not in state:
        return "Ошибка: аудиозапись не найдена в памяти. Отправьте аудио еще раз."
        
    response = ai_client.models.generate_content(
        model='gemini-3.5-flash',
        contents=[
            genai_types.Part.from_bytes(
                data=state['audio_bytes'],
                mime_type=state['mime_type']
            ),
            prompt_text
        ]
    )
    return response.text


def generate_voice(text, voice_name="ru-RU-Chirp3-HD-Aoede"):
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(language_code="ru-RU", name=voice_name)
    audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
    response = tts_client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)
    return response.audio_content


# Кнопка СТАРТ (Ваши стандартные Reply-кнопки)
@bot.message_handler(commands=['start', 'help'])
def send_welcome_message(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    button1 = types.KeyboardButton("О нас")
    button2 = types.KeyboardButton("Контакты")
    markup.add(button1, button2)

    bot.send_message(message.chat.id, "Нажмите на кнопку или отправьте аудио:", reply_markup=markup)


# ========================================================
# ⚙️ ЛОГИКА ТЕКСТОВЫХ КНОПОК И ОБРАБОТКИ
# ========================================================

@bot.message_handler(content_types=['voice', 'audio'])
def handle_audio(message):
    try:
        chat_id = message.chat.id
        bot.send_chat_action(chat_id, 'typing')
        
        if message.voice:
            file_info = bot.get_file(message.voice.file_id)
            mime_type = "audio/ogg"
        else:
            file_info = bot.get_file(message.audio.file_id)
            mime_type = "audio/mpeg"

        downloaded_file = bot.download_file(file_info.file_path)

        # Сохраняем аудио в оперативную память
        user_states[chat_id] = {
            'audio_bytes': downloaded_file,
            'mime_type': mime_type,
            'state': 'waiting_for_action'
        }

        # Создаем обычную клавиатуру внизу экрана
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("📝 Дословная транскрибация", "✨ Обработка", "⚙️ Кастомный промт")

        bot.reply_to(message, "🎙️ Аудио получено! Выберите режим обработки на панели внизу:", reply_markup=markup)

    except Exception as e:
        bot.reply_to(message, f"Ошибка при загрузке аудио: {e}")


# Единый обработчик для всех текстовых команд и кнопок
@bot.message_handler(content_types=['text'])
def handle_text_commands(message):
    chat_id = message.chat.id
    text = message.text

    # 1. Если у нас НЕТ в памяти аудио для этого пользователя
    if chat_id not in user_states:
        if text == "О нас":
            bot.send_message(chat_id, "🤖 Мы — умный бот-диктор на базе искусственного интеллекта Gemini.")
        elif text == "Контакты":
            bot.send_message(chat_id, "📞 Поддержка: @your_telegram_username")
        else:
            # Возвращаем стандартное стартовое меню
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("О нас", "Контакты")
            bot.send_message(chat_id, "Чтобы начать, отправьте мне аудиозапись или голосовое сообщение.", reply_markup=markup)
        return

    # Получаем текущее состояние пользователя
    state_data = user_states[chat_id]
    state = state_data.get('state')

    # 2. Если бот ждет от пользователя текст кастомного промта
    if state == 'waiting_for_custom_prompt':
        bot.reply_to(message, f"⚙️ Обрабатываю аудио по вашей инструкции:\n*\"{text}\"*...", parse_mode="Markdown")
        try:
            result = process_audio_with_gemini(chat_id, text)
            # Возвращаем меню "О нас" / "Контакты" после вывода результата
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("О нас", "Контакты")
            bot.send_message(chat_id, f"🔮 **Результат обработки:**\n\n{result}", parse_mode="Markdown", reply_markup=markup)
        except Exception as e:
            bot.send_message(chat_id, f"Произошла ошибка: {e}")
            
        user_states.pop(chat_id, None)  # Очищаем память
        return

    # 3. Обработка трех основных кнопок после получения аудио
    if text == "📝 Дословная транскрибация":
        bot.send_message(chat_id, "✍️ Выполняю дословное распознавание...")
        result = process_audio_with_gemini(chat_id, PROMPT_VERBATIM)
        
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("О нас", "Контакты")
        bot.send_message(chat_id, f"📝 **Дословный текст:**\n\n{result}", parse_mode="Markdown", reply_markup=markup)
        user_states.pop(chat_id, None)

    elif text == "✨ Обработка":
        bot.send_message(chat_id, "🧹 Запускаю очистку и обработку текста...")
        result = process_audio_with_gemini(chat_id, CLEANUP_PROMPT)
        
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("О нас", "Контакты")
        bot.send_message(chat_id, f"✨ **Очищенный текст:**\n\n{result}", parse_mode="Markdown", reply_markup=markup)
        user_states.pop(chat_id, None)

    elif text == "⚙️ Кастомный промт":
        user_states[chat_id]['state'] = 'waiting_for_custom_prompt'
        # Временно скрываем кнопки, чтобы пользователь ввел свой текст
        hide_markup = types.ReplyKeyboardRemove()
        bot.send_message(chat_id, "⌨️ **Вставьте вашу инструкцию (промт) для обработки этого аудио:**", reply_markup=hide_markup)

    else:
        # Если при наличии аудио пользователь прислал что-то другое, напоминаем о выборе
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("📝 Дословная транскрибация", "✨ Обработка", "⚙️ Кастомный промт")
        bot.send_message(chat_id, "Пожалуйста, выберите один из режимов обработки на кнопках внизу:", reply_markup=markup)


if __name__ == "__main__":
    # 1. Запускаем микро-сервер в фоновом потоке, чтобы Render не ругался на порты
    Thread(target=run_dummy_server, daemon=True).start()
    
    # 2. Запускаем самого бота
    print("Бот запущен...")
    bot.infinity_polling()
