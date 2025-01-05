import asyncio
import aioftp
import os
import logging
import sys
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# Logging konfigurieren
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)

# Konfigurationsparameter
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBURL = os.getenv("WEBURL").rstrip("/")  # URL für Webhook
FTP_HOST = os.getenv("FTP_HOST")
FTP_USER = os.getenv("FTP_USER")
FTP_PASS = os.getenv("FTP_PASS")
FTP_UPLOAD_DIR = "/www/gallery"
LOCAL_DOWNLOAD_PATH = "./downloads/"
os.makedirs(LOCAL_DOWNLOAD_PATH, exist_ok=True)

# Temporäre Speicherung von Benutzerdaten
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
        logger.info(f"✅ Datei erfolgreich auf FTP hochgeladen: {file_name}")
        return True
    except Exception as e:
        logger.error(f"❌ FTP-Upload-Fehler: {e}")
        return False

# Start-Befehl
async def start(update: Update, context):
    await update.message.reply_text(
        "Hallo! Sende mir ein Bild, um es hochzuladen. Anschließend kannst du Titel, Material, Datum und Maße festlegen."
    )

# Bild hochladen
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
        logger.error(f"❌ Fehler beim Foto-Handling: {e}")
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

    try:
        if step == "title":
            user_info["title"] = update.message.text.replace(" ", "_")
            user_info["step"] = "material"
            await update.message.reply_text("Titel gespeichert. Bitte sende das Material des Bildes.")
        elif step == "material":
            user_info["material"] = update.message.text.replace(" ", "_")
            user_info["step"] = "date"
            await update.message.reply_text("Material gespeichert. Bitte sende das Datum im Format 'Monat Jahr'.")
        elif step == "date":
            try:
                month, year = update.message.text.split()
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
            new_name = f"{user_info['title']}_{user_info['material']}_{user_info['month']}_{user_info['year']}_{user_info['dimensions']}.jpg"
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
                logger.info(f"🗑️ Datei lokal gelöscht: {new_local_path}")

            # Benutzerdaten entfernen
            del user_data[chat_id]
    except Exception as e:
        logger.error(f"❌ Fehler bei der Verarbeitung: {e}")
        await update.message.reply_text("❌ Fehler bei der Verarbeitung.")

# Hauptfunktion
def main():
    # Anwendung erstellen
    application = Application.builder().token(BOT_TOKEN).build()

    # Handler hinzufügen
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Webhook setzen und starten
    webhook_url = f"{WEBURL}/{BOT_TOKEN}"
    try:
        application.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 8443)),
            url_path=BOT_TOKEN,
            webhook_url=webhook_url,
        )
        logger.info(f"Webhook erfolgreich gesetzt: {webhook_url}")
    except Exception as e:
        logger.error(f"❌ Fehler beim Starten des Webhook-Servers: {e}")

if __name__ == "__main__":
    main()
