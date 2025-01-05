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

# Hilfsfunktion: Datei auf FTP umbenennen
async def rename_ftp_file(old_name, new_name):
    try:
        client = await ftp_connect()
        await client.rename(old_name, new_name)
        await client.quit()
        return True
    except Exception as e:
        print(f"Fehler beim Umbenennen der Datei auf dem FTP-Server: {e}")
        return False

# Hilfsfunktion: Datei auf FTP löschen
async def delete_ftp_file(file_name):
    try:
        client = await ftp_connect()
        await client.remove_file(file_name)
        await client.quit()
        return True
    except Exception as e:
        print(f"Fehler beim Löschen der Datei auf dem FTP-Server: {e}")
        return False

# Start-Befehl
async def start(update: Update, context):
    await update.message.reply_text(
        "Hallo! Sende mir ein Bild, um es hochzuladen. Anschließend kannst du Titel, Material, Datum und Verfügbarkeit festlegen. "
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
        [InlineKeyboardButton("3. Material ändern", callback_data="edit_material")],
        [InlineKeyboardButton("4. Verfügbarkeit ändern", callback_data="edit_availability")],
        [InlineKeyboardButton("5. Startbild festlegen", callback_data="set_start")],
        [InlineKeyboardButton("6. Löschen", callback_data="delete")],
        [InlineKeyboardButton("7. Fertig", callback_data="discard_changes")]
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
        file_data["step"] = "set_date"  # Weiter zum nächsten Schritt
        await update.message.reply_text("✅ Material gespeichert. Bitte sende jetzt das Datum im Format 'Monat-Jahr' (z. B. Februar-2024):")

    elif current_step == "set_date":
        # Speichere das Datum
        file_data["date"] = update.message.text.strip()
        # Prüfen, ob alle Details ausgefüllt sind
        if all(file_data.get(key) for key in ["title", "material", "date"]):
            # Neuen Dateinamen erstellen
            new_name = f"{file_data['title']}_{file_data['material']}_{file_data['date']}.jpg"
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
    await query.edit_message_text("Bitte sende den neuen Titel für das Bild.")

async def edit_date(update: Update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "date"
    await query.edit_message_text("Bitte sende das neue Datum im Format 'Monat-Jahr' (z. B. Februar-2024).")

async def edit_material(update: Update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "material"
    await query.edit_message_text("Bitte sende das neue Material für das Bild.")

async def edit_availability(update: Update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "availability"
    keyboard = [
        [InlineKeyboardButton("Verfügbar", callback_data="set_available")],
        [InlineKeyboardButton("Nicht verfügbar", callback_data="set_unavailable")],
    ]
    await query.edit_message_text("Bitte wähle die Verfügbarkeit aus:", reply_markup=InlineKeyboardMarkup(keyboard))

async def set_start_image(update: Update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "start_image"
    await query.edit_message_text("Startbild wird festgelegt...")

    files = await list_ftp_files()
    old_start_image = None
    for file in files:
        if "_S" in file:
            old_start_image = file
            break

    # Neuen Startbildnamen erstellen
    selected_image_index = context.user_data.get("selected_image_index")
    selected_image_name = files[selected_image_index]
    base_name, ext = os.path.splitext(selected_image_name)
    new_start_name = f"{base_name}_S{ext}"

    try:
        client = await ftp_connect()
        if old_start_image:
            await client.rename(old_start_image, old_start_image.replace("_S", ""))
        await client.rename(selected_image_name, new_start_name)
        await client.quit()
        await query.edit_message_text(f"Startbild erfolgreich gesetzt: {new_start_name}.")
    except Exception as e:
        await query.edit_message_text(f"Fehler beim Setzen des Startbildes: {e}")

async def delete_image(update: Update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "delete"
    await query.edit_message_text("Bild wird gelöscht...")

    selected_image_index = context.user_data.get("selected_image_index")
    files = await list_ftp_files()
    selected_image_name = files[selected_image_index]

    if await delete_ftp_file(selected_image_name):
        await query.edit_message_text(f"Bild '{selected_image_name}' wurde erfolgreich gelöscht.")
    else:
        await query.edit_message_text(f"Fehler beim Löschen des Bildes '{selected_image_name}'.")

# Änderungs-Handler
async def handle_edit_action(update: Update, context):
    chat_id = update.message.chat.id
    edit_action = context.user_data.get("edit_action")

    if not edit_action:
        await update.message.reply_text("Es wurde keine Bearbeitungsaktion gestartet. Bitte wähle zuerst eine Option aus dem Menü.")
        return

    # Nachricht löschen (falls möglich)
    try:
        await update.message.delete()
    except Exception as e:
        print(f"Fehler beim Löschen der Nachricht: {e}")

    selected_image_index = context.user_data.get("selected_image_index")
    files = await list_ftp_files()
    selected_image_name = files[selected_image_index]

    if edit_action == "title":
        new_title = update.message.text.strip()
        parts = selected_image_name.split("_")
        if len(parts) < 3:
            await update.message.reply_text("❌ Fehler: Dateiname hat ein unerwartetes Format.")
            return
        parts[0] = new_title  # Ersetze den ersten Teil mit dem neuen Titel
        new_name = "_".join(parts)
        if await rename_ftp_file(selected_image_name, new_name):
            await update.message.reply_text(f"Titel erfolgreich geändert zu: {new_title}.")
        else:
            await update.message.reply_text("❌ Fehler beim Ändern des Titels.")

    elif edit_action == "date":
        new_date = update.message.text.strip()
        parts = selected_image_name.split("_")
        if len(parts) < 3:
            await update.message.reply_text("❌ Fehler: Dateiname hat ein unerwartetes Format.")
            return
        parts[2] = new_date  # Ersetze den dritten Teil mit dem neuen Datum
        new_name = "_".join(parts)
        if await rename_ftp_file(selected_image_name, new_name):
            await update.message.reply_text(f"Datum erfolgreich geändert zu: {new_date}.")
        else:
            await update.message.reply_text("❌ Fehler beim Ändern des Datums.")

    elif edit_action == "material":
        new_material = update.message.text.strip()
        parts = selected_image_name.split("_")
        if len(parts) < 3:
            await update.message.reply_text("❌ Fehler: Dateiname hat ein unerwartetes Format.")
            return
        parts[1] = new_material  # Ersetze den zweiten Teil mit dem neuen Material
        new_name = "_".join(parts)
        if await rename_ftp_file(selected_image_name, new_name):
            await update.message.reply_text(f"Material erfolgreich geändert zu: {new_material}.")
        else:
            await update.message.reply_text("❌ Fehler beim Ändern des Materials.")

    elif edit_action == "availability":
        availability_status = update.callback_query.data
        if availability_status == "set_available":
            new_name = selected_image_name.replace("_x", "")
        else:
            new_name = selected_image_name.replace(".jpg", "_x.jpg")
        if await rename_ftp_file(selected_image_name, new_name):
            await update.message.reply_text(f"Verfügbarkeit erfolgreich geändert zu: {'verfügbar' if availability_status == 'set_available' else 'nicht verfügbar'}.")
        else:
            await update.message.reply_text("❌ Fehler beim Ändern der Verfügbarkeit.")

    context.user_data["edit_action"] = None  # Aktion abschließen

# Hauptfunktion
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Handler hinzufügen
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("list", list_images))
    application.add_handler(CallbackQueryHandler(show_image_options, pattern="select_"))
    application.add_handler(CallbackQueryHandler(edit_title, pattern="edit_title"))
    application.add_handler(CallbackQueryHandler(edit_date, pattern="edit_date"))
    application.add_handler(CallbackQueryHandler(edit_material, pattern="edit_material"))
    application.add_handler(CallbackQueryHandler(edit_availability, pattern="edit_availability"))
    application.add_handler(CallbackQueryHandler(set_start_image, pattern="set_start"))
    application.add_handler(CallbackQueryHandler(delete_image, pattern="delete"))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, multi_step_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_action))

    # Webhook setzen und starten
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBURL}/{BOT_TOKEN}",
    )

if __name__ == "__main__":
    main()