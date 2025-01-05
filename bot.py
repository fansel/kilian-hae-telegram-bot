import asyncio
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import aioftp
import os
import logging
import sys

# Logging konfigurieren
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)

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

async def upload_to_ftp(local_path, file_name):
    try:
        client = aioftp.Client()
        await client.connect(FTP_HOST)
        await client.login(FTP_USER, FTP_PASS)
        await client.change_directory(FTP_UPLOAD_DIR)
        await client.upload(local_path)
        await client.quit()
        logger.info(f"Datei erfolgreich auf FTP hochgeladen: {file_name}")
        return True
    except Exception as e:
        logger.error(f"FTP-Upload-Fehler: {e}")
        return False

async def start(update, context):
    logger.info(f"Received /start from {update.message.chat.id}")
    await update.message.reply_text("Hallo! Sende mir ein Bild, um es hochzuladen.")

async def photo_handler(update, context):
    chat_id = update.message.chat.id
    status = await update.message.reply_text("📥 Herunterladen des Bildes...")
    try:
        file = await update.message.photo[-1].get_file()
        local_path = os.path.join(LOCAL_DOWNLOAD_PATH, file.file_id + ".jpg")
        await file.download_to_drive(local_path)
        user_data[chat_id] = {"file_path": local_path, "step": "title"}
        logger.info(f"Bild erfolgreich heruntergeladen: {local_path}")
        await status.edit_text("✅ Bild hochgeladen! Bitte sende jetzt den Titel des Bildes.")
    except Exception as e:
        logger.error(f"Fehler beim Foto-Handling: {e}")
        await status.edit_text("❌ Fehler beim Hochladen des Bildes.")

async def text_handler(update, context):
    chat_id = update.message.chat.id
    if chat_id not in user_data:
        await update.message.reply_text("Bitte sende zuerst ein Bild.")
        return

    user_info = user_data[chat_id]
    step = user_info.get("step")
    try:
        if step == "title":
            user_info["title"] = update.message.text
            user_info["step"] = "material"
            await update.message.reply_text("Titel gespeichert. Sende das Material.")
        elif step == "material":
            user_info["material"] = update.message.text
            user_info["step"] = "date"
            await update.message.reply_text("Material gespeichert. Sende das Datum (Monat Jahr).")
        elif step == "date":
            user_info["date"] = update.message.text
            user_info["step"] = "dimensions"
            await update.message.reply_text("Datum gespeichert. Sende die Maße (Breite x Höhe).")
        elif step == "dimensions":
            dimensions = update.message.text.replace(" ", "")
            user_info["dimensions"] = dimensions
            local_path = user_info["file_path"]
            new_name = f"{user_info['title']}_{user_info['material']}_{user_info['date']}_{dimensions}.jpg"
            new_path = os.path.join(LOCAL_DOWNLOAD_PATH, new_name)
            os.rename(local_path, new_path)
            success = await upload_to_ftp(new_path, new_name)
            if success:
                await update.message.reply_text(f"✅ Hochgeladen: {new_name}")
            else:
                await update.message.reply_text("❌ Fehler beim Hochladen.")
            if os.path.exists(new_path):
                os.remove(new_path)
            del user_data[chat_id]
    except Exception as e:
        logger.error(f"Fehler bei der Verarbeitung: {e}")
        await update.message.reply_text("❌ Fehler bei der Verarbeitung.")

async def configure_webhook(application):
    webhook_url = f"{WEBURL}/{BOT_TOKEN}"
    try:
        success = await application.bot.set_webhook(webhook_url)
        if success:
            logger.info(f"Webhook erfolgreich gesetzt: {webhook_url}")
        else:
            logger.error("Fehler beim Setzen des Webhooks.")
    except Exception as e:
        logger.error(f"Error setting webhook: {e}")

async def main():
    logger.info("Bot startet...")
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    await configure_webhook(application)

    await application.run_webhook(
        listen="0.0.0.0",
        port=8443,
        url_path=BOT_TOKEN,
    )

if __name__ == "__main__":
    asyncio.run(main())
