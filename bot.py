import os
import aioftp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

# Konfigurationsparameter
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBURL = os.getenv("WEBURL").rstrip("/")
FTP_HOST = os.getenv("FTP_HOST")
FTP_USER = os.getenv("FTP_USER")
FTP_PASS = os.getenv("FTP_PASS")
FTP_UPLOAD_DIR = "/www/gallery"
LOCAL_DOWNLOAD_PATH = "./downloads/"
os.makedirs(LOCAL_DOWNLOAD_PATH, exist_ok=True)

user_data = {}

# Hilfsfunktion: Datei auf FTP hochladen
async def upload_to_ftp(local_path, file_name):
    try:
        client = aioftp.Client()
        await client.connect(FTP_HOST)
        await client.login(FTP_USER, FTP_PASS)
        await client.change_directory(FTP_UPLOAD_DIR)
        await client.upload(local_path)
        await client.quit()
        return True
    except Exception as e:
        print(f"FTP-Upload-Fehler: {e}")
        return False

# Hilfsfunktion: Dateien von FTP auflisten
async def list_ftp_files():
    try:
        client = aioftp.Client()
        await client.connect(FTP_HOST)
        await client.login(FTP_USER, FTP_PASS)
        
        # Ändere das Verzeichnis auf den Zielpfad
        await client.change_directory(FTP_UPLOAD_DIR)
        
        # Liste der Dateien abrufen
        files = []
        async for path, info in client.list(FTP_UPLOAD_DIR):
            if info["type"] == "file":  # Nur Dateien, keine Verzeichnisse
                files.append(path.name)
        
        await client.quit()
        return files
    except Exception as e:
        print(f"Fehler beim Abrufen der Dateien: {e}")
        return []


# Start-Befehl
async def start(update: Update, context):
    await update.message.reply_text(
        "Hallo! Sende mir ein Bild, um es hochzuladen. Anschließend kannst du Titel, Material, Datum und Maße festlegen. "
        "Verwende /help, um weitere Informationen zu erhalten."
    )

# Hilfe-Befehl
async def help_command(update: Update, context):
    await update.message.reply_text(
        "/start - Startet den Bot\n"
        "/help - Zeigt diese Hilfe an\n"
        "/list - Listet alle Bilder aus dem Verzeichnis\n"
    )

# Bilder auflisten
async def list_images(update: Update, context):
    files = await list_ftp_files()
    if not files:
        await update.message.reply_text("📂 Keine Bilder gefunden.")
        return

    titles = [file.split("_")[0] for file in files if file.endswith(".jpg")]
    keyboard = [
        [InlineKeyboardButton(f"{i+1}. {title}", callback_data=f"select_{i}")]
        for i, title in enumerate(titles)
    ]

    await update.message.reply_text(
        "📂 Verfügbare Bilder:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Bildoptionen anzeigen
async def show_image_options(update: Update, context):
    query = update.callback_query
    index = int(query.data.split("_")[1])
    context.user_data["selected_image_index"] = index

    keyboard = [
        [InlineKeyboardButton("1. Titel ändern", callback_data="edit_title")],
        [InlineKeyboardButton("2. Datum ändern", callback_data="edit_date")],
        [InlineKeyboardButton("3. Maße ändern", callback_data="edit_dimensions")],
        [InlineKeyboardButton("4. Verfügbarkeit ändern", callback_data="edit_availability")],
        [InlineKeyboardButton("5. Startbild festlegen", callback_data="set_start")],
        [InlineKeyboardButton("6. Löschen", callback_data="delete")]
    ]

    await query.edit_message_text(
        "Was möchtest du tun?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Upload eines Bildes
async def photo_handler(update: Update, context):
    chat_id = update.message.chat.id
    status = await update.message.reply_text("📥 Herunterladen des Bildes...")

    try:
        file = await update.message.photo[-1].get_file()
        local_path = os.path.join(LOCAL_DOWNLOAD_PATH, file.file_id + ".jpg")
        await file.download_to_drive(local_path)

        user_data[chat_id] = {"file_path": local_path, "file_name": file.file_id + ".jpg", "step": "title"}
        await status.edit_text("✅ Bild hochgeladen! Bitte sende jetzt den Titel des Bildes.")
    except Exception as e:
        print(f"Fehler beim Upload: {e}")
        await status.edit_text("❌ Fehler beim Hochladen des Bildes.")

# Benutzerinformationen abfragen und Datei umbenennen
async def text_handler(update: Update, context):
    chat_id = update.message.chat.id
    if chat_id not in user_data:
        await update.message.reply_text("Sende zuerst ein Bild, um fortzufahren.")
        return

    user_info = user_data[chat_id]
    step = user_info.get("step")
    local_path = user_info.get("file_path")

    if step == "title":
        user_info["title"] = update.message.text.replace(" ", "_")
        user_info["step"] = "date"
        await update.message.reply_text("Titel gespeichert. Bitte sende das Datum im Format 'Monat Jahr'.")
    elif step == "date":
        try:
            parts = update.message.text.split()
            month = parts[0] if len(parts) > 1 else "None"
            year = parts[-1]
            user_info["month"] = month
            user_info["year"] = year
            user_info["step"] = "dimensions"
            await update.message.reply_text("Datum gespeichert. Bitte sende die Maße im Format 'Breite x Höhe'.")
        except ValueError:
            await update.message.reply_text("Ungültiges Format. Bitte sende das Datum im Format 'Monat Jahr'.")
    elif step == "dimensions":
        user_info["dimensions"] = update.message.text.replace(" ", "")
        user_info["step"] = None

        # Neuer Dateiname erstellen
        new_name = f"{user_info['title']}_{user_info['month']}_{user_info['year']}_{user_info['dimensions']}.jpg"
        new_local_path = os.path.join(LOCAL_DOWNLOAD_PATH, new_name)

        # Datei lokal umbenennen
        os.rename(local_path, new_local_path)

        # Datei auf FTP hochladen
        success = await upload_to_ftp(new_local_path, new_name)

        if success:
            await update.message.reply_text(f"✅ Datei erfolgreich hochgeladen: {new_name}")
        else:
            await update.message.reply_text("❌ Fehler beim Hochladen der Datei.")

        # Lokale Datei löschen
        if os.path.exists(new_local_path):
            os.remove(new_local_path)
            print(f"🗑️ Datei lokal gelöscht: {new_local_path}")

        # Benutzerdaten entfernen
        del user_data[chat_id]

# Hauptfunktion
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Handler hinzufügen
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("list", list_images))
    application.add_handler(CallbackQueryHandler(show_image_options, pattern="select_"))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Webhook setzen und starten
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBURL}/{BOT_TOKEN}",
    )

if __name__ == "__main__":
    main()
