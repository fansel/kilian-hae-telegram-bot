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

# Hilfsfunktion: FTP-Verbindung
async def ftp_connect():
    client = aioftp.Client()
    await client.connect(FTP_HOST)
    await client.login(FTP_USER, FTP_PASS)
    await client.change_directory(FTP_UPLOAD_DIR)
    return client

# Hilfsfunktion: Datei auf FTP hochladen
async def upload_to_ftp(local_path, new_name):
    try:
        client = await ftp_connect()
        await client.upload(local_path, new_name)
        await client.quit()
        return True
    except Exception as e:
        print(f"FTP-Upload-Fehler: {e}")
        return False

# Hilfsfunktion: Dateien von FTP auflisten
async def list_ftp_files():
    try:
        client = await ftp_connect()
        files = []
        async for path, info in client.list(FTP_UPLOAD_DIR):
            if info["type"] == "file":
                files.append(path.name)
        await client.quit()
        return files
    except Exception as e:
        print(f"Fehler beim Abrufen der Dateien: {e}")
        return []

# Start-Befehl
async def start(update: Update, context):
    await update.message.reply_text(
        "Hallo! Sende mir ein Bild, um es hochzuladen. Anschließend kannst du Titel, Material, Monat, Jahr und Verfügbarkeit festlegen. "
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

    context.user_data["files"] = files
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
        [InlineKeyboardButton("2. Material ändern", callback_data="edit_material")],
        [InlineKeyboardButton("3. Datum ändern", callback_data="edit_date")],
        [InlineKeyboardButton("4. Verfügbarkeit ändern", callback_data="edit_availability")],
        [InlineKeyboardButton("5. Fertig", callback_data="discard_changes")]
    ]

    await query.edit_message_text(
        "Was möchtest du tun?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Foto-Handler
async def photo_handler(update: Update, context):
    chat_id = update.message.chat.id
    status = await update.message.reply_text("📥 Herunterladen des Bildes...")
    try:
        # Bild herunterladen und lokal speichern
        file = await update.message.photo[-1].get_file()
        local_path = os.path.join(LOCAL_DOWNLOAD_PATH, file.file_id + ".jpg")
        await file.download_to_drive(local_path)

        # Speichere Bilddaten für den Benutzer
        user_data[chat_id] = {
            "file_path": local_path,
            "file_name": file.file_id + ".jpg",
            "step": "set_title",  # Startet mit der Titelabfrage
        }

        # Starte Multi-Step-Prozess
        await status.edit_text("✅ Bild erfolgreich heruntergeladen. Bitte sende jetzt den Titel für das Bild:")
    except Exception as e:
        print(f"Fehler beim Herunterladen: {e}")
        await status.edit_text("❌ Fehler beim Herunterladen des Bildes.")

# Multi-Step-Handler
async def multi_step_handler(update: Update, context):
    chat_id = update.message.chat.id
    file_data = user_data.get(chat_id)

    if not file_data:
        await update.message.reply_text("❌ Kein Bild ausgewählt. Bitte lade zuerst ein Bild hoch.")
        return

    # Bestimme den aktuellen Schritt
    current_step = file_data.get("step", "set_title")  # Standardmäßig mit "set_title" starten

    if current_step == "set_title":
        # Speichere den Titel
        file_data["title"] = update.message.text.strip()
        file_data["step"] = "set_material"  # Weiter zum nächsten Schritt
        await update.message.reply_text("✅ Titel gespeichert. Bitte sende jetzt das Material (z. B. Leinwand):")

    elif current_step == "set_material":
        # Speichere das Material
        file_data["material"] = update.message.text.strip()
        file_data["step"] = "select_month"  # Weiter zum nächsten Schritt
        await update.message.reply_text("✅ Material gespeichert. Bitte wähle jetzt den Monat aus:", reply_markup=month_selection_keyboard())

    elif current_step == "select_month":
        # Speichere den Monat
        file_data["month"] = update.message.text.strip()
        file_data["step"] = "set_year"  # Weiter zum nächsten Schritt
        await update.message.reply_text("✅ Monat gespeichert. Bitte sende jetzt das Jahr (z. B. 2024):")

    elif current_step == "set_year":
        # Speichere das Jahr
        file_data["year"] = update.message.text.strip()
        # Prüfen, ob alle Details ausgefüllt sind
        if all(file_data.get(key) for key in ["title", "material", "month", "year"]):
            # Neuen Dateinamen erstellen
            new_name = f"{file_data['title']}_{file_data['material']}_{file_data['month']}-{file_data['year']}.jpg"
            # Datei hochladen
            if await upload_to_ftp(file_data["file_path"], new_name):
                await update.message.reply_text(f"✅ Alle Details gespeichert und Bild hochgeladen: {new_name}")
            else:
                await update.message.reply_text("❌ Fehler beim Hochladen des Bildes.")
            user_data.pop(chat_id)  # Daten für diesen Benutzer löschen
        else:
            await update.message.reply_text("❌ Es fehlen noch Informationen. Bitte starte erneut.")

    else:
        await update.message.reply_text("❌ Unbekannter Schritt. Bitte starte erneut mit dem Hochladen eines Bildes.")

# Bearbeitungsfunktionen
async def edit_title(update: Update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "title"
    await query.edit_message_text("Bitte sende den neuen Titel für das Bild:")

async def edit_material(update: Update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "material"
    await query.edit_message_text("Bitte sende das neue Material für das Bild:")

async def edit_date(update: Update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "month"
    await query.edit_message_text("Bitte wähle den neuen Monat für das Bild:", reply_markup=month_selection_keyboard())

async def edit_availability(update: Update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "availability"
    keyboard = [
        [InlineKeyboardButton("Verfügbar", callback_data="set_available")],
        [InlineKeyboardButton("Nicht verfügbar", callback_data="set_unavailable")],
    ]
    await query.edit_message_text("Bitte wähle die Verfügbarkeit aus:", reply_markup=InlineKeyboardMarkup(keyboard))

# Hilfsfunktion: Monat-Auswahl-Tastatur
def month_selection_keyboard():
    months = [
        "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember"
    ]
    keyboard = [
        [InlineKeyboardButton(month, callback_data=month) for month in months]
    ]
    return InlineKeyboardMarkup(keyboard)

# Hauptfunktion
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Handler hinzufügen
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("list", list_images))
    application.add_handler(CallbackQueryHandler(show_image_options, pattern="select_"))
    application.add_handler(CallbackQueryHandler(edit_title, pattern="edit_title"))
    application.add_handler(CallbackQueryHandler(edit_material, pattern="edit_material"))
    application.add_handler(CallbackQueryHandler(edit_date, pattern="edit_date"))
    application.add_handler(CallbackQueryHandler(edit_availability, pattern="edit_availability"))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, multi_step_handler))

    # Webhook setzen und starten
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBURL}/{BOT_TOKEN}",
    )

if __name__ == "__main__":
    main()