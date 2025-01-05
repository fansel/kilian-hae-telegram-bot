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
        await client.change_directory(FTP_UPLOAD_DIR)
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
        "Hallo! Sende mir ein Bild, um es hochzuladen. Anschließend kannst du Titel, Datum, Maße und Verfügbarkeit festlegen. "
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
# Maße bearbeiten
async def edit_dimensions(update: Update, context):
    query = update.callback_query
    await query.answer()

    context.user_data["edit_action"] = "dimensions"
    await query.edit_message_text("Bitte sende die neuen Maße im Format 'Breite x Höhe'.")

# Verfügbarkeit ändern
async def edit_availability(update: Update, context):
    query = update.callback_query
    await query.answer()

    selected_image_index = context.user_data.get("selected_image_index")
    files = await list_ftp_files()
    selected_image_name = files[selected_image_index]

    if "_x" in selected_image_name:
        new_name = selected_image_name.replace("_x", "")
        availability = "verfügbar"
    else:
        base_name, ext = os.path.splitext(selected_image_name)
        new_name = f"{base_name}_x{ext}"
        availability = "nicht verfügbar"

    # Datei auf FTP umbenennen
    try:
        client = aioftp.Client()
        await client.connect(FTP_HOST)
        await client.login(FTP_USER, FTP_PASS)
        await client.rename(
            os.path.join(FTP_UPLOAD_DIR, selected_image_name),
            os.path.join(FTP_UPLOAD_DIR, new_name)
        )
        await client.quit()

        await query.edit_message_text(f"Verfügbarkeit geändert: {availability}.")
    except Exception as e:
        await query.edit_message_text(f"Fehler beim Ändern der Verfügbarkeit: {e}")

# Startbild festlegen
async def set_start_image(update: Update, context):
    query = update.callback_query
    await query.answer()

    files = await list_ftp_files()
    # Entferne _S vom alten Startbild
    try:
        client = aioftp.Client()
        await client.connect(FTP_HOST)
        await client.login(FTP_USER, FTP_PASS)

        for file in files:
            if file.endswith("_S.jpg"):
                base_name, ext = os.path.splitext(file)
                new_name = f"{base_name.replace('_S', '')}{ext}"
                await client.rename(
                    os.path.join(FTP_UPLOAD_DIR, file),
                    os.path.join(FTP_UPLOAD_DIR, new_name)
                )

        # Neues Startbild setzen
        selected_image_index = context.user_data.get("selected_image_index")
        selected_image_name = files[selected_image_index]
        base_name, ext = os.path.splitext(selected_image_name)
        new_start_name = f"{base_name}_S{ext}"

        await client.rename(
            os.path.join(FTP_UPLOAD_DIR, selected_image_name),
            os.path.join(FTP_UPLOAD_DIR, new_start_name)
        )
        await client.quit()

        await query.edit_message_text(f"Startbild erfolgreich gesetzt: {new_start_name}.")
    except Exception as e:
        await query.edit_message_text(f"Fehler beim Setzen des Startbildes: {e}")

# Löschen eines Bildes
async def delete_image(update: Update, context):
    query = update.callback_query
    await query.answer()

    selected_image_index = context.user_data.get("selected_image_index")
    files = await list_ftp_files()
    selected_image_name = files[selected_image_index]

    # Bestätigungsdialog
    keyboard = [
        [InlineKeyboardButton("Ja, löschen", callback_data="confirm_delete")],
        [InlineKeyboardButton("Nein, abbrechen", callback_data="cancel_delete")]
    ]
    context.user_data["delete_target"] = selected_image_name
    await query.edit_message_text(
        f"Möchtest du das Bild '{selected_image_name}' wirklich löschen?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def confirm_delete(update: Update, context):
    query = update.callback_query
    await query.answer()

    delete_target = context.user_data.get("delete_target")

    # Bild löschen
    try:
        client = aioftp.Client()
        await client.connect(FTP_HOST)
        await client.login(FTP_USER, FTP_PASS)
        await client.remove_file(os.path.join(FTP_UPLOAD_DIR, delete_target))
        await client.quit()

        await query.edit_message_text(f"Bild '{delete_target}' wurde gelöscht.")
    except Exception as e:
        await query.edit_message_text(f"Fehler beim Löschen: {e}")

async def cancel_delete(update: Update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Löschvorgang abgebrochen.")

# Titel festlegen
async def set_title(update: Update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "title"
    await query.edit_message_text("Bitte sende den neuen Titel für das Bild.")

# Datum bearbeiten
async def edit_date(update: Update, context):
    query = update.callback_query
    await query.answer()

    # Monatsauswahl
    keyboard = [
        [InlineKeyboardButton("Januar", callback_data="month_Januar"), InlineKeyboardButton("Februar", callback_data="month_Februar")],
        [InlineKeyboardButton("März", callback_data="month_März"), InlineKeyboardButton("April", callback_data="month_April")],
        [InlineKeyboardButton("Mai", callback_data="month_Mai"), InlineKeyboardButton("Juni", callback_data="month_Juni")],
        [InlineKeyboardButton("Juli", callback_data="month_Juli"), InlineKeyboardButton("August", callback_data="month_August")],
        [InlineKeyboardButton("September", callback_data="month_September"), InlineKeyboardButton("Oktober", callback_data="month_Oktober")],
        [InlineKeyboardButton("November", callback_data="month_November"), InlineKeyboardButton("Dezember", callback_data="month_Dezember")],
        [InlineKeyboardButton("Kein Monat", callback_data="month_None")]
    ]

    await query.edit_message_text(
        "Bitte wähle den Monat:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Monat auswählen und Jahr festlegen
async def select_month(update: Update, context):
    query = update.callback_query
    await query.answer()

    selected_month = query.data.split("_")[1]
    context.user_data["selected_month"] = selected_month

    await query.edit_message_text(f"Monat '{selected_month}' ausgewählt. Bitte sende jetzt das Jahr (z. B. 2025).")
    context.user_data["edit_action"] = "year"

# Jahr eingeben
async def set_year(update: Update, context):
    year = update.message.text.strip()
    context.user_data["selected_year"] = year
    selected_month = context.user_data.get("selected_month", "None")
    await update.message.reply_text(f"Datum gespeichert: {selected_month} {year}.")
    context.user_data["edit_action"] = "dimensions"
    await update.message.reply_text("Bitte sende die Maße im Format 'Breite x Höhe'.")

# Weitere Funktionen für Maße, Verfügbarkeit, Startbild und Löschen ähnlich ergänzen...

# Hauptfunktion
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Handler hinzufügen
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("list", list_images))
    application.add_handler(CallbackQueryHandler(show_image_options, pattern="select_"))
    application.add_handler(CallbackQueryHandler(set_title, pattern="edit_title"))
    application.add_handler(CallbackQueryHandler(edit_date, pattern="edit_date"))
    application.add_handler(CallbackQueryHandler(edit_dimensions, pattern="edit_dimensions"))
    application.add_handler(CallbackQueryHandler(edit_availability, pattern="edit_availability"))
    application.add_handler(CallbackQueryHandler(set_start_image, pattern="set_start"))
    application.add_handler(CallbackQueryHandler(delete_image, pattern="delete"))
    application.add_handler(CallbackQueryHandler(confirm_delete, pattern="confirm_delete"))
    application.add_handler(CallbackQueryHandler(select_month, pattern="month_"))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, set_year))

    # Webhook setzen und starten
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBURL}/{BOT_TOKEN}",
    )

if __name__ == "__main__":
    main()
