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
        [InlineKeyboardButton("4. Material ändern", callback_data="edit_material")],
        [InlineKeyboardButton("5. Verfügbarkeit ändern", callback_data="edit_availability")],
        [InlineKeyboardButton("6. Startbild festlegen", callback_data="set_start")],
        [InlineKeyboardButton("7. Löschen", callback_data="delete")],
        [InlineKeyboardButton("8. Änderungen abschließen", callback_data="confirm_changes")],
        [InlineKeyboardButton("9. Änderungen verwerfen", callback_data="discard_changes")]
    ]

    await query.edit_message_text(
        "Was möchtest du tun?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

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
        file_data["step"] = "set_date"  # Weiter zum nächsten Schritt
        await update.message.reply_text("✅ Titel gespeichert. Bitte sende jetzt das Datum (z. B. 2025-01-05):")

    elif current_step == "set_date":
        # Speichere das Datum
        file_data["date"] = update.message.text.strip()
        file_data["step"] = "set_material"  # Weiter zum nächsten Schritt
        await update.message.reply_text("✅ Datum gespeichert. Bitte sende jetzt das Material (z. B. Leinwand):")

    elif current_step == "set_material":
        # Speichere das Material
        file_data["material"] = update.message.text.strip()

        # Prüfen, ob alle Details ausgefüllt sind
        if all(file_data[key] for key in ["title", "date", "material"]):
            # Neuen Dateinamen erstellen
            new_name = f"{file_data['title']}_{file_data['date']}_{file_data['material']}.jpg"
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


# Maße bearbeiten
async def edit_dimensions(update: Update, context):
    query = update.callback_query
    await query.answer()

    context.user_data["edit_action"] = "dimensions"
    await query.edit_message_text("Bitte sende die neuen Maße im Format 'Breite x Höhe'.")

async def edit_availability(update: Update, context):
    query = update.callback_query
    await query.answer()

    chat_id = update.effective_chat.id
    file_data = user_data.get(chat_id)

    if not file_data:
        await query.edit_message_text("❌ Kein Bild ausgewählt.")
        return

    old_name = file_data["file_name"]
    base_name, ext = os.path.splitext(old_name)

    # Verfügbarkeitsstatus bestimmen
    if "_x" in base_name:
        availability = "nicht verfügbar"
        new_availability = "verfügbar"
    else:
        availability = "verfügbar"
        new_availability = "nicht verfügbar"

    # Bestätigungs-Keyboard
    keyboard = [
        [InlineKeyboardButton("Ja, ändern", callback_data="confirm_availability")],
        [InlineKeyboardButton("Nein, zurück", callback_data="cancel_availability")],
    ]

    # Verfügbarkeitsstatus anzeigen und Änderung vorschlagen
    context.user_data["edit_availability"] = {
        "old_name": old_name,
        "new_name": base_name.replace("_x", "") + ext if "_x" in base_name else base_name + "_x" + ext,
        "new_status": new_availability,
    }
    await query.edit_message_text(
        f"📂 Der aktuelle Status ist: {availability}.\n"
        f"Möchtest du den Status auf {new_availability} ändern?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
async def confirm_availability(update: Update, context):
    query = update.callback_query
    await query.answer()

    edit_data = context.user_data.get("edit_availability")
    if not edit_data:
        await query.edit_message_text("❌ Fehler: Keine Verfügbarkeitsänderung gefunden.")
        return

    old_name = edit_data["old_name"]
    new_name = edit_data["new_name"]
    new_status = edit_data["new_status"]

    # Datei umbenennen
    if await rename_ftp_file(old_name, new_name):
        # Aktualisiere Benutzerdaten
        chat_id = update.effective_chat.id
        user_data[chat_id]["file_name"] = new_name
        await query.edit_message_text(f"✅ Verfügbarkeit erfolgreich geändert zu: {new_status}.")

        # Kontextmenü erneut anzeigen
        await show_image_options(update, context)
    else:
        await query.edit_message_text("❌ Fehler beim Ändern der Verfügbarkeit.")

async def rename_ftp_file(old_name, new_name):
    try:
        client = aioftp.Client()
        await client.connect(FTP_HOST)
        await client.login(FTP_USER, FTP_PASS)
        await client.rename(
            os.path.join(FTP_UPLOAD_DIR, old_name),
            os.path.join(FTP_UPLOAD_DIR, new_name)
        )
        await client.quit()
        return True
    except Exception as e:
        print(f"Fehler beim Umbenennen der Datei: {e}")
        return False

async def cancel_availability(update: Update, context):
    query = update.callback_query
    await query.answer()

    # Kontextmenü erneut anzeigen
    await show_image_options(update, context)


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

# Material bearbeiten
async def edit_material(update: Update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "material"
    await query.edit_message_text("Bitte sende das neue Material für das Bild.")

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
# Änderungen abschließen
async def finish_config(update: Update, context):
    query = update.callback_query
    await query.answer()
    
    # Hier könnte Logik stehen, um Änderungen auf dem FTP zu bestätigen, falls erforderlich
    context.user_data.clear()  # User-Daten zurücksetzen
    await query.edit_message_text("Änderungen wurden erfolgreich abgeschlossen.")

# Änderungen verwerfen
async def discard_changes(update: Update, context):
    query = update.callback_query
    await query.answer()

    # User-Daten verwerfen
    context.user_data.clear()
    await query.edit_message_text("Alle Änderungen wurden verworfen.")

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
    await return_to_menu(update, context)

# Änderungen abschließen
async def confirm_changes(update: Update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Alle Änderungen wurden erfolgreich gespeichert.")
    context.user_data.clear()

# Änderungen verwerfen
async def discard_changes(update: Update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Alle Änderungen wurden verworfen.")
    context.user_data.clear()

# Hauptmenü erneut anzeigen
async def return_to_menu(update: Update, context):
    """
    Kehrt zurück zum Bildoptionen-Menü, nachdem eine Aktion abgeschlossen wurde.
    Löscht vorherige Nachrichten, wenn möglich.
    """
    query = update.callback_query

    # Wenn es eine CallbackQuery gibt, bestätigen wir die Aktion.
    if query:
        await query.answer()

    # Nachricht löschen, wenn aus Text-Handler aufgerufen
    if update.message:
        try:
            await update.message.delete()
        except Exception as e:
            print(f"Fehler beim Löschen der Nachricht: {e}")

    selected_image_index = context.user_data.get("selected_image_index", None)
    if selected_image_index is None:
        await update.message.reply_text("Kein Bild ausgewählt. Bitte wähle ein Bild aus der Liste aus.")
        return

    # Hauptmenü anzeigen
    keyboard = [
        [InlineKeyboardButton("1. Titel ändern", callback_data="edit_title")],
        [InlineKeyboardButton("2. Datum ändern", callback_data="edit_date")],
        [InlineKeyboardButton("3. Maße ändern", callback_data="edit_dimensions")],
        [InlineKeyboardButton("4. Material ändern", callback_data="edit_material")],
        [InlineKeyboardButton("5. Verfügbarkeit ändern", callback_data="edit_availability")],
        [InlineKeyboardButton("6. Startbild festlegen", callback_data="set_start")],
        [InlineKeyboardButton("7. Löschen", callback_data="delete")],
        [InlineKeyboardButton("8. Änderungen abschließen", callback_data="confirm_changes")],
        [InlineKeyboardButton("9. Änderungen verwerfen", callback_data="discard_changes")]
    ]

    # Hauptmenü senden
    if query:
        await query.edit_message_text(
            "Was möchtest du tun?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            "Was möchtest du tun?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def text_handler(update: Update, context):
    chat_id = update.message.chat.id
    edit_action = context.user_data.get("edit_action", None)

    if not edit_action:
        await update.message.reply_text("Es wurde keine Bearbeitungsaktion gestartet. Bitte wähle zuerst eine Option aus dem Menü.")
        return

    # Nachricht löschen (falls möglich)
    try:
        await update.message.delete()
    except Exception as e:
        print(f"Fehler beim Löschen der Nachricht: {e}")

    if edit_action == "title":
        new_title = update.message.text.strip()
        # Logik zum Speichern des neuen Titels hier hinzufügen
        await update.message.reply_text(f"Titel geändert zu: {new_title}.")
        context.user_data["edit_action"] = None  # Aktion abschließen
        await return_to_menu(update, context)

    elif edit_action == "material":
        new_material = update.message.text.strip()
        # Logik zum Speichern des neuen Materials hier hinzufügen
        await update.message.reply_text(f"Material geändert zu: {new_material}.")
        context.user_data["edit_action"] = None  # Aktion abschließen
        await return_to_menu(update, context)

    elif edit_action == "dimensions":
        new_dimensions = update.message.text.strip()
        if "x" not in new_dimensions:
            await update.message.reply_text("Ungültiges Format. Bitte sende die Maße im Format 'Breite x Höhe'.")
            return

        # Logik zum Speichern der neuen Maße hier hinzufügen
        await update.message.reply_text(f"Maße geändert zu: {new_dimensions}.")
        context.user_data["edit_action"] = None  # Aktion abschließen
        await return_to_menu(update, context)

    elif edit_action == "year":
        year = update.message.text.strip()
        selected_month = context.user_data.get("selected_month", "None")
        await update.message.reply_text(f"Datum gespeichert: {selected_month} {year}.")
        context.user_data["edit_action"] = None  # Aktion abschließen
        await return_to_menu(update, context)

    else:
        await update.message.reply_text("Unbekannte Aktion. Bitte wähle erneut aus dem Menü.")



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
    application.add_handler(CallbackQueryHandler(edit_material, pattern="edit_material"))
    application.add_handler(CallbackQueryHandler(edit_availability, pattern="edit_availability"))
    application.add_handler(CallbackQueryHandler(set_start_image, pattern="set_start"))
    application.add_handler(CallbackQueryHandler(delete_image, pattern="delete"))
    application.add_handler(CallbackQueryHandler(confirm_delete, pattern="confirm_delete"))
    application.add_handler(CallbackQueryHandler(cancel_delete, pattern="cancel_delete"))
    application.add_handler(CallbackQueryHandler(select_month, pattern="month_"))
    application.add_handler(CallbackQueryHandler(confirm_changes, pattern="confirm_changes"))
    application.add_handler(CallbackQueryHandler(discard_changes, pattern="discard_changes"))
    application.add_handler(CallbackQueryHandler(finish_config, pattern="finish_config"))
    application.add_handler(CallbackQueryHandler(confirm_availability, pattern="confirm_availability"))
    application.add_handler(CallbackQueryHandler(cancel_availability, pattern="cancel_availability"))
    application.add_handler(CallbackQueryHandler(discard_changes, pattern="discard_changes"))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, multi_step_handler))
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
