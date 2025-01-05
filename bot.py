import os
import aioftp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

# Konfigurationsparameter
BOT_TOKEN = os.environ.get('BOT_TOKEN')
WEBURL = os.environ.get('WEBURL')
FTP_HOST = os.environ.get('FTP_HOST')
FTP_USER = os.environ.get('FTP_USER')
FTP_PASS = os.environ.get('FTP_PASS')
FTP_UPLOAD_DIR = "./"
LOCAL_DOWNLOAD_PATH = "./downloads/"
os.makedirs(LOCAL_DOWNLOAD_PATH, exist_ok=True)

# Temporäre Speicherung von Benutzerdaten
user_data = {}
debug_mode = False
debug_chat_id = None

# Hilfsfunktion: Debug-Nachrichten senden
async def send_debug_message(context, message):
    if debug_mode and debug_chat_id:
        await context.bot.send_message(chat_id=debug_chat_id, text=message)

# Hilfsfunktion: Datei auf FTP hochladen
async def upload_to_ftp(local_path, file_name):
    try:
        client = aioftp.Client()
        await client.connect(FTP_HOST)
        await client.login(FTP_USER, FTP_PASS)
        await client.change_directory(FTP_UPLOAD_DIR)
        await client.upload(local_path)
        await client.quit()
        await send_debug_message(context, f"Datei erfolgreich hochgeladen: {file_name}")
        return True
    except Exception as e:
        await send_debug_message(context, f"FTP-Upload-Fehler: {e}")
        return False

# Hilfsfunktion: Datei von FTP löschen
async def delete_from_ftp(file_name):
    try:
        client = aioftp.Client()
        await client.connect(FTP_HOST)
        await client.login(FTP_USER, FTP_PASS)
        await client.change_directory(FTP_UPLOAD_DIR)
        await client.remove(file_name)
        await client.quit()
        await send_debug_message(context, f"Datei erfolgreich gelöscht: {file_name}")
        return True
    except Exception as e:
        await send_debug_message(context, f"FTP-Lösch-Fehler: {e}")
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
        await send_debug_message(context, f"Dateien auf FTP gelistet: {files}")
        return files
    except Exception as e:
        await send_debug_message(context, f"Fehler beim Abrufen der Dateien: {e}")
        return []

# Start-Befehl
async def start(update: Update, context):
    await update.message.reply_text(
        "Hallo! Sende mir ein Bild, um es hochzuladen. Anschließend kannst du Titel, Material, Datum und Maße festlegen."
    )

# Hilfe-Befehl
async def help_command(update: Update, context):
    await update.message.reply_text(
        "/start - Startet den Bot\n"
        "/help - Zeigt diese Hilfe an\n"
        "/list - Listet alle Bilder aus dem Verzeichnis\n"
        "/delete - Löscht ein Bild aus dem Verzeichnis\n"
        "/debug - Schaltet den Debug-Modus ein oder aus\n"
    )

# Debug-Befehl
async def debug_command(update: Update, context):
    global debug_mode, debug_chat_id
    debug_mode = not debug_mode
    debug_chat_id = update.message.chat.id if debug_mode else None
    status = "aktiviert" wenn debug_mode sonst "deaktiviert"
    await update.message.reply_text(f"Debug-Modus {status}.")

# Bild hochladen
async def photo_handler(update: Update, context):
    chat_id = update.message.chat.id
    status = await update.message.reply_text("📥 Herunterladen des Bildes...")

    # Bild herunterladen
    file = await update.message.photo[-1].get_file()
    local_path = os.path.join(LOCAL_DOWNLOAD_PATH, file.file_id + ".jpg")
    await file.download_to_drive(local_path)

    user_data[chat_id] = {"file_path": local_path, "file_name": file.file_id + ".jpg", "step": "title"}
    await status.edit_text("✅ Bild hochgeladen! Bitte sende jetzt den Titel des Bildes.")
    await send_debug_message(context, f"Bild heruntergeladen und gespeichert unter: {local_path}")

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
        user_info["title"] = update.message.text.replace(" ", "-")
        user_info["step"] = "material"
        await update.message.reply_text("Titel gespeichert. Bitte sende das Material des Bildes.")
    elif step == "material":
        user_info["material"] = update.message.text.replace(" ", "-")
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
        try:
            width, height = update.message.text.split("x")
            user_info["dimensions"] = f"{width}-{height}"
            user_info["step"] = None

            # Neuer Dateiname erstellen
            new_name = f"{user_info['title']}_{user_info['material']}_{user_info['month']}-{user_info['year']}_{user_info['dimensions']}.jpg"
            new_local_path = os.path.join(LOCAL_DOWNLOAD_PATH, new_name)

            # Datei lokal umbenennen
            os.rename(local_path, new_local_path)
            await send_debug_message(context, f"Datei lokal umbenannt: {local_path} -> {new_local_path}")

            # Datei auf FTP hochladen
            success = await upload_to_ftp(new_local_path, new_name)

            if success:
                await update.message.reply_text(f"✅ Datei erfolgreich hochgeladen: {new_name}")
            else:
                await update.message.reply_text("❌ Fehler beim Hochladen der Datei.")

            # Lokale Datei löschen
            if os.path.exists(new_local_path):
                os.remove(new_local_path)
                await send_debug_message(context, f"Datei lokal gelöscht: {new_local_path}")

            # Benutzerdaten entfernen
            del user_data[chat_id]
        except ValueError:
            await update.message.reply_text("Ungültiges Format. Bitte sende die Maße im Format 'Breite x Höhe'.")

# Bilder auflisten
async def list_images(update: Update, context):
    files = await list_ftp_files()
    if not files:
        await update.message.reply_text("📂 Keine Bilder gefunden.")
        return

    keyboard = [
        [InlineKeyboardButton(f"{i+1}. {file}", callback_data=f"select_{i}")]
        for i, file in enumerate(files)
    ]

    await update.message.reply_text(
        "📂 Verfügbare Bilder:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Bildauswahl-Handler
async def button_handler(update: Update, context):
    query = update.callback_query
    await query.answer()
    file_index = int(query.data.split('_')[1])

    files = await list_ftp_files()
    if file_index >= len(files):
        await query.edit_message_text("Ungültige Auswahl.")
        return

    selected_file = files[file_index]
    chat_id = query.message.chat.id

    user_data[chat_id] = {
        "file_name": selected_file,
        "step": "edit_title"
    }

    await query.edit_message_text(f"Ausgewählte Datei: {selected_file}\nBitte sende den neuen Titel.")

# Benutzerinformationen zum Bearbeiten abfragen und Datei umbenennen
async def edit_text_handler(update: Update, context):
    chat_id = update.message.chat.id
    if chat_id not in user_data:
        await update.message.reply_text("Kein Bild ausgewählt. Verwende /list, um ein Bild auszuwählen.")
        return

    user_info = user_data[chat_id]
    step = user_info.get("step")
    old_name = user_info.get("file_name")

    if step == "edit_title":
        user_info["title"] = update.message.text.replace(" ", "-")
        user_info["step"] = "edit_material"
        await update.message.reply_text("Titel gespeichert. Bitte sende das neue Material.")
    elif step == "edit_material":
        user_info["material"] = update.message.text.replace(" ", "-")
        user_info["step"] = "edit_date"
        await update.message.reply_text("Material gespeichert. Bitte sende das neue Datum im Format 'Monat Jahr'.")
    elif step == "edit_date":
        try:
            month, year = update.message.text.split()
            user_info["month"] = month
            user_info["year"] = year
            user_info["step"] = "edit_dimensions"
            await update.message.reply_text("Datum gespeichert. Bitte sende die neuen Maße im Format 'Breite x Höhe'.")
        except ValueError:
            await update.message.reply_text("Ungültiges Format. Bitte sende das Datum im Format 'Monat Jahr'.")
    elif step == "edit_dimensions":
        user_info["dimensions"] = update.message.text.replace(" ", "")
        user_info["step"] = None

        # Neuer Dateiname erstellen
        new_name = f"{user_info['title']}_{user_info['material']}_{user_info['month']}-{user_info['year']}_{user_info['dimensions']}.jpg"
        old_path = os.path.join(FTP_UPLOAD_DIR, old_name)
        new_path = os.path.join(FTP_UPLOAD_DIR, new_name)

        # Datei auf FTP umbenennen
        try:
            client = aioftp.Client()
            await client.connect(FTP_HOST)
            await client.login(FTP_USER, FTP_PASS)
            await client.rename(old_path, new_path)
            await client.quit()
            await update.message.reply_text(f"✅ Datei erfolgreich umbenannt: {new_name}")
            await send_debug_message(context, f"Datei auf FTP umbenannt: {old_path} -> {new_path}")
        except Exception as e:
            await update.message.reply_text(f"❌ Fehler beim Umbenennen der Datei: {e}")
            await send_debug_message(context, f"Fehler beim Umbenennen der Datei: {e}")

        # Benutzerdaten entfernen
        del user_data[chat_id]

# Bild löschen
async def delete_image(update: Update, context):
    files = await list_ftp_files()
    if not files:
        await update.message.reply_text("📂 Keine Bilder gefunden.")
        return

    keyboard = [
        [InlineKeyboardButton(f"{i+1}. {file} löschen", callback_data=f"delete_{i}")]
        for i, file in enumerate(files)
    ]

    await update.message.reply_text(
        "📂 Wähle ein Bild zum Löschen:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Bild löschen Handler
async def delete_button_handler(update: Update, context):
    query = update.callback_query
    await query.answer()
    file_index = int(query.data.split('_')[1])

    files = await list_ftp_files()
    if file_index >= len(files):
        await query.edit_message_text("Ungültige Auswahl.")
        return

    selected_file = files[file_index]

    # Datei von FTP löschen
    success = await delete_from_ftp(selected_file)
    if success:
        await query.edit_message_text(f"✅ Datei erfolgreich gelöscht: {selected_file}")
    else:
        await query.edit_message_text("❌ Fehler beim Löschen der Datei.")

# Hauptfunktion
def main():
    # Anwendung erstellen
    application = Application.builder().token(BOT_TOKEN).build()

    # Handler hinzufügen
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("list", list_images))
    application.add_handler(CommandHandler("delete", delete_image))
    application.add_handler(CommandHandler("debug", debug_command))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    application.add_handler(CallbackQueryHandler(button_handler, pattern='^select_'))
    application.add_handler(CallbackQueryHandler(delete_button_handler, pattern='^delete_'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, edit_text_handler))

    # Webhook setzen und starten
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBURL}/{BOT_TOKEN}",
    )

if __name__ == "__main__":
    main()