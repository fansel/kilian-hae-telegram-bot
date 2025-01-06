import os
import asyncio
from dotenv import load_dotenv
import argparse
import aioftp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application,CommandHandler, MessageHandler, CallbackQueryHandler, filters, CallbackContext
from telegram.ext.filters import User

if os.path.exists(".env"):
    load_dotenv(".env")

# Konfigurationsparameter
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBURL = os.getenv("WEBURL")
FTP_HOST = os.getenv("FTP_HOST")
FTP_USER = os.getenv("FTP_USER")
FTP_PASS = os.getenv("FTP_PASS")
LOCAL_DOWNLOAD_PATH = "./downloads/"
ADMINISTRATOR_IDS = [int(i) for i in os.getenv("ADMINISTRATOR_IDS").split(",")]



os.makedirs(LOCAL_DOWNLOAD_PATH, exist_ok=True)

user_data = {}
ftp_client = None
inactivity_timer = None



async def start(update: Update, context):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Wow! Admin found!")


# Argumente parsen
def parse_args():
    parser = argparse.ArgumentParser(description="Start the bot in either local or webhook mode.")
    parser.add_argument('--local', action='store_true', help="Run the bot in local polling mode.")
    return parser.parse_args()

# Hilfsfunktion: FTP-Verbindung
async def ftp_connect():
    global ftp_client
    if ftp_client is None:
        ftp_client = aioftp.Client()
        await ftp_client.connect(FTP_HOST)
        await ftp_client.login(FTP_USER, FTP_PASS)
        print("FTP-Verbindung aufgebaut.")
    else:
        try:
            await ftp_client.get_current_directory()
            print("FTP-Verbindung ist aktiv.")
        except (aioftp.StatusCodeError, ConnectionResetError):
            print("FTP-Verbindung verloren gegangen, erneuere die Verbindung.")
            ftp_client = aioftp.Client()
            await ftp_client.connect(FTP_HOST)
            await ftp_client.login(FTP_USER, FTP_PASS)
    return ftp_client

# Hilfsfunktion: FTP-Verbindung trennen
async def ftp_disconnect():
    global ftp_client
    if ftp_client is not None:
        await ftp_client.quit()
        ftp_client = None
        print("FTP-Verbindung getrennt.")

# Hilfsfunktion: Inaktivitäts-Timer starten
def start_inactivity_timer():
    global inactivity_timer
    if inactivity_timer is not None:
        inactivity_timer.cancel()
    inactivity_timer = asyncio.get_event_loop().call_later(300, asyncio.create_task, ftp_disconnect())

async def upload_to_ftp(local_path, filename):
    try:
        client = await ftp_connect()
        print(f"Lade Datei {local_path} hoch als {filename}")
        
        # Zielpfad anpassen, um sicherzustellen, dass die Datei direkt im Zielverzeichnis gespeichert wird
        target_path = f"/{filename}"

        print(f"Ziel: {target_path}")

        
        await client.upload(local_path, target_path, write_into=True)
        
        # Inaktivitäts-Timer neu starten
        start_inactivity_timer()
        
        return True
    except Exception as e:
        print(f"FTP-Upload-Fehler: {e}")
        return False

# Hilfsfunktion: Datei auf FTP umbenennen
async def rename_ftp_file(old_name, new_name):
    try:
        client = await ftp_connect()
        await client.rename(old_name, new_name)
        start_inactivity_timer()
        print(f"Datei {old_name} umbenannt in {new_name}")
        return True
    except Exception as e:
        print(f"Fehler beim Umbenennen der Datei auf dem FTP-Server: {e}")
        return False

# Hilfsfunktion: Datei auf FTP löschen
async def delete_ftp_file(file_name):
    try:
        client = await ftp_connect()
        await client.remove_file(file_name)
        start_inactivity_timer()
        return True
    except Exception as e:
        print(f"Fehler beim Löschen der Datei auf dem FTP-Server: {e}")
        return False

# Hilfsfunktion: Dateien von FTP auflisten
async def list_ftp_files():
    try:
        client = await ftp_connect()
        files = []
        async for path, info in client.list():
            if info["type"] == "file":
                files.append(path.name)
        start_inactivity_timer()
        return files
    except Exception as e:
        print(f"Fehler beim Abrufen der Dateien: {e}")
        return []
# Start-Befehl
async def start(update: Update, context: CallbackContext):
    await ftp_connect()  # FTP-Verbindung aufbauen
    start_inactivity_timer()
    await update.message.reply_text(
        "Hallo! Sende mir ein Bild, um es hochzuladen. Anschließend kannst du Titel, Material, Datum und Maße festlegen. "
        "Verwende /help, um weitere Informationen zu erhalten."
    )

# Hilfe-Befehl
async def help_command(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "/start - Startet den Bot\n"
        "/help - Zeigt diese Hilfe an\n"
        "/list - Listet alle Bilder aus dem Verzeichnis\n"
    )

# Bilder auflisten
async def list_images(update: Update, context: CallbackContext):
    files = await list_ftp_files()
    if not files:
        await update.message.reply_text("📂 Keine Bilder gefunden.")
        return

    titles = [file.split("_")[0] for file in files]
    titles = [file.replace("-", " ") for file in titles]
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
async def show_image_options(update: Update, context: CallbackContext):
    query = update.callback_query
    index = int(query.data.split("_")[1])
    context.user_data["selected_image_index"] = index

    keyboard = [
        [InlineKeyboardButton("1. Titel ändern", callback_data="edit_title")],
        [InlineKeyboardButton("2. Material ändern", callback_data="edit_material")],
        [InlineKeyboardButton("3. Datum ändern", callback_data="edit_date")],
        [InlineKeyboardButton("4. Maße ändern", callback_data="edit_dimensions")],
        [InlineKeyboardButton("5. Verfügbarkeit ändern", callback_data="edit_availability")],
        [InlineKeyboardButton("6. Löschen", callback_data="delete")],
        [InlineKeyboardButton("7. Startbild festlegen", callback_data="set_start_image")],
        [InlineKeyboardButton("8. Fertig", callback_data="discard_changes")]
    ]

    await query.edit_message_text(
        "Was möchtest du tun?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Kommando zum Ändern des Titels
async def change_title(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "change_title"
    await query.edit_message_text("Bitte sende den neuen Titel für das Bild:")

# Kommando zum Ändern des Materials
async def change_material(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "change_material"
    await query.edit_message_text("Bitte sende das neue Material für das Bild:")

async def change_date(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    # Aktion setzen
    context.user_data["edit_action"] = "change_date"

    # Monatsauswahl anzeigen
    keyboard = [
        [InlineKeyboardButton("Kein Monat angeben", callback_data="none")],
        [InlineKeyboardButton("Januar", callback_data="Januar"), InlineKeyboardButton("Februar", callback_data="Februar"), InlineKeyboardButton("März", callback_data="März")],
        [InlineKeyboardButton("April", callback_data="April"), InlineKeyboardButton("Mai", callback_data="Mai"), InlineKeyboardButton("Juni", callback_data="Juni")],
        [InlineKeyboardButton("Juli", callback_data="Juli"), InlineKeyboardButton("August", callback_data="August"), InlineKeyboardButton("September", callback_data="September")],
        [InlineKeyboardButton("Oktober", callback_data="Oktober"), InlineKeyboardButton("November", callback_data="November"), InlineKeyboardButton("Dezember", callback_data="Dezember")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Bitte wähle den Monat aus:", reply_markup=reply_markup)


        


# Kommando zum Ändern der Verfügbarkeit
async def change_availability(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "change_availability"
    keyboard = [
        [InlineKeyboardButton("Verfügbar", callback_data="set_available")],
        [InlineKeyboardButton("Nicht verfügbar", callback_data="set_unavailable")]
    ]
    await query.edit_message_text("Bitte wähle die Verfügbarkeit aus:", reply_markup=InlineKeyboardMarkup(keyboard))

# Verfügbarkeit festlegen
async def set_availability(update: Update, context: CallbackContext):
    query = update.callback_query
    availability_status = query.data
    files = context.user_data.get("files", [])
    selected_image_index = context.user_data.get("selected_image_index")
    selected_image_name = files[selected_image_index]

    # Trenne den Dateinamen von der Endung
    if "." in selected_image_name:
        name_part, file_extension = selected_image_name.rsplit(".", 1)
    else:
        name_part = selected_image_name
        file_extension = ""

    rename_needed = False

    if availability_status == "set_available":
        # Entferne _x am Ende, falls vorhanden
        if name_part.endswith("_x"):
            name_part = name_part[:-2]
            rename_needed = True
        elif name_part.endswith("_x_S"):
            name_part = name_part[:-4] + "_S"
            rename_needed = True
    elif availability_status == "set_unavailable":
        # Füge _x am Ende hinzu, falls nicht vorhanden
        if not name_part.endswith("_x") and not name_part.endswith("_x_S"):
            if name_part.endswith("_S"):
                name_part = name_part[:-2] + "_x_S"
            else:
                name_part += "_x"
            rename_needed = True

    if rename_needed:
        # Neuen Dateinamen zusammensetzen und Dateiendung wieder hinzufügen
        new_name = f"{name_part}.{file_extension}" if file_extension else name_part
        if await rename_ftp_file(selected_image_name, new_name):
            await query.edit_message_text(f"Verfügbarkeit erfolgreich geändert: {new_name}.")
        else:
            await query.edit_message_text("❌ Fehler bei der Durchführung der Aktion.")
    else:
        await query.edit_message_text("Keine Änderung erforderlich. Dateiname bleibt unverändert.")
    
    context.user_data["edit_action"] = None  # Aktion abschließen

# Kommando zum Ändern der Maße
async def change_dimensions(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "change_dimensions"
    await query.edit_message_text("Bitte sende die neuen Maße im Format 'Breite x Höhe':")

# Kommando zum Festlegen des Startbildes
async def set_start_image(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "set_start_image"
    await query.edit_message_text("Möchtest du dieses Bild als Startbild festlegen? Bestätige mit /confirm oder brich ab mit /cancel.")

# Kommando zum Löschen eines Bildes
async def delete_image(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "delete"
    await query.edit_message_text("Möchtest du dieses Bild wirklich löschen? Bestätige mit /confirm oder brich ab mit /cancel.")

# Bestätigung des Löschens oder Festlegen des Startbildes
async def confirm(update: Update, context: CallbackContext):
    chat_id = update.message.chat.id
    edit_action = context.user_data.get("edit_action")
    if not edit_action:
        await update.message.reply_text("❌ Keine Aktion zur Bestätigung gefunden.")
        return

    selected_image_index = context.user_data.get("selected_image_index")
    files = context.user_data.get("files", [])
    selected_image_name = files[selected_image_index]

    if edit_action == "delete":
        if await delete_ftp_file(selected_image_name):
            await update.message.reply_text(f"✅ Bild {selected_image_name} wurde erfolgreich gelöscht.")
        else:
            await update.message.reply_text(f"❌ Fehler beim Löschen des Bildes {selected_image_name}.")
    elif edit_action == "set_start_image":
        # Entferne _S von allen anderen Bildern
        for i, file in enumerate(files):
            if file.endswith("_S.png") or file.endswith("_S.jpg"):
                new_file_name = file.replace("_S", "")
                await rename_ftp_file(file, new_file_name)
        # Setze _S für das ausgewählte Bild
        parts = selected_image_name.rsplit(".", maxsplit=1)
        if len(parts) == 2:
            name, extension = parts
            if "_x." in name or "_x_" in name:
                print(name)
                name = name.replace("_x", "_x_S")
            else:
                name += "_S"
            new_name = f"{name}.{extension}"
            if await rename_ftp_file(selected_image_name, new_name):
                await update.message.reply_text(f"✅ Bild {new_name} wurde erfolgreich als Startbild festgelegt.")
            else:
                await update.message.reply_text("❌ Fehler beim Festlegen des Startbildes.")
        else:
            await update.message.reply_text("❌ Fehler beim Verarbeiten des Dateinamens.")
    context.user_data["edit_action"] = None  # Aktion abschließen

# Abbrechen der Aktion
async def cancel(update: Update, context: CallbackContext):
    chat_id = update.message.chat.id
    context.user_data[chat_id] = None
    await update.message.reply_text("❌ Aktion abgebrochen.")
# Foto empfangen und Upload starten
async def receive_photo(update: Update, context: CallbackContext):
    photo = update.message.photo[-1]  # Nimm die höchste Auflösung
    file = await context.bot.get_file(photo.file_id)

    # Dynamische Erkennung der Dateiendung
    file_extension = os.path.splitext(file.file_path)[-1]
    file_path = os.path.join(LOCAL_DOWNLOAD_PATH, f"{photo.file_id}{file_extension}")
    
    await file.download_to_drive(file_path)

    # Initialisiere Upload-Schritte
    context.user_data["photo_upload"] = True
    context.user_data["current_photo_path"] = file_path
    context.user_data["current_file_extension"] = file_extension
    context.user_data["upload_step"] = "title"  # Startpunkt: Titel
    await update.message.reply_text("📷 Foto empfangen! Bitte gib einen Titel ein:")

# Dialog zur Eingabe der Foto-Metadaten
async def photo_upload_dialog(update: Update, context: CallbackContext):

    if not context.user_data.get("photo_upload"):
        return  # Kein aktiver Foto-Upload → Ignoriere Eingaben
    upload_step = context.user_data.get("upload_step")

    if not upload_step:
        await update.message.reply_text("❌ Kein Upload-Prozess aktiv. Sende ein Foto, um zu starten.")
        return

    if upload_step == "title":
        context.user_data["title"] = update.message.text.strip()
        context.user_data["upload_step"] = "material"
        await update.message.reply_text("Bitte gib das Material ein:")

    elif upload_step == "material":
        context.user_data["material"] = update.message.text.strip()
        context.user_data["upload_step"] = "month"
        #wähle monat oder keinen monat auswählen aus inline keyboard
        keyboard = [
            [InlineKeyboardButton("Kein Monat angeben", callback_data="none")],
            [InlineKeyboardButton("Januar", callback_data="Januar"), InlineKeyboardButton("Februar", callback_data="Februar"), InlineKeyboardButton("März", callback_data="März")],
            [InlineKeyboardButton("April", callback_data="April"), InlineKeyboardButton("Mai", callback_data="Mai"), InlineKeyboardButton("Juni", callback_data="Juni")],
            [InlineKeyboardButton("Juli", callback_data="Juli"), InlineKeyboardButton("August", callback_data="August"), InlineKeyboardButton("September", callback_data="September")],
            [InlineKeyboardButton("Oktober", callback_data="Oktober"), InlineKeyboardButton("November", callback_data="November"), InlineKeyboardButton("Dezember", callback_data="Dezember")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.user_data["upload_step"] = "year"
        await update.message.reply_text("Bitte wähle den Monat aus:", reply_markup=reply_markup)


    elif upload_step == "year":
        #next is dimensions
        context.user_data["year"] = update.message.text.strip()
        context.user_data["upload_step"] = "dimensions"
        await update.message.reply_text("Bitte gib die Maße im Format 'Breite x Höhe' ein:")

    elif upload_step == "dimensions":
        #check if dimensions are in correct format
        dimensions = update.message.text.strip()
        if "x" not in dimensions:
            await update.message.reply_text("❌ Fehler: Maße müssen im Format 'Breite x Höhe' sein. Bitte versuche es erneut.")
            #repeat context for dimensions
            context.user_data["upload_step"] = "dimensions"
            return
        #upload photo
        await upload_photo(update, context)



        # Upload-Schritte abschließen
        context.user_data.pop("upload_step", None)
        context.user_data.pop("current_photo_path", None)
        context.user_data.pop("current_file_extension", None)
        context.user_data.pop("title", None)
        context.user_data.pop("material", None)
        context.user_data.pop("year", None)
        context.user_data.pop("selected_month", None)

# Foto hochladen
async def upload_photo(update: Update, context: CallbackContext):
    local_path = context.user_data.get("current_photo_path")
    file_extension = context.user_data.get("current_file_extension", ".jpg")
    title = context.user_data.get("title").replace(" ", "-")
    material = context.user_data.get("material").replace(" ", "-")
    month = context.user_data.get("selected_month")
    year = context.user_data.get("year").replace(" ", "-")
    dimensions = update.message.text.strip().replace("x", "-")
    
    # Erstelle den Dateinamen
    filename = f"{title}_{material}_{month}-{year}_{dimensions}{file_extension}"
    #rename file
    new_local_path = os.path.join(LOCAL_DOWNLOAD_PATH, filename)
    if os.path.exists(local_path):
        os.rename(local_path, new_local_path)
        # Datei auf FTP hochladen
        success = await upload_to_ftp(new_local_path, filename)
        if success:
            await update.message.reply_text(f"📷 Bild erfolgreich hochgeladen: {filename}"
                                        
                            )
        else:
            await update.message.reply_text("❌ Fehler beim Hochladen des Bildes.")
    
    # Lokale Datei löschen
    if os.path.exists(local_path):
        os.remove(local_path)

    context.user_data["photo_upload"] = False
    context.user_data.pop("current_photo_path", None)
    context.user_data.pop("current_file_extension", None)
    context.user_data.pop("title", None)
    context.user_data.pop("material", None)
    context.user_data.pop("year", None)

async def handle_month_selection(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    # Speichere den ausgewählten Monat
    selected_month = query.data
    context.user_data["selected_month"] = selected_month

    # Fordere den Nutzer auf, das Jahr einzugeben
    await query.edit_message_text("Bitte gib das Jahr ein (z. B. 2025):")
    context.user_data["awaiting_year"] = True
# Multi-Step-Handler für Benutzerinteraktionen
async def multi_step_handler(update: Update, context: CallbackContext):
    chat_id = update.message.chat.id
    #if photo upload running then dont interrupt
    if context.user_data.get("photo_upload"):
        await photo_upload_dialog(update, context)
        return
    else:
        edit_action = context.user_data.get("edit_action")
        if not edit_action:
            await update.message.reply_text("❌ Keine Bearbeitungsaktion gestartet. Bitte wähle zuerst eine Option aus dem Menü.")
            return

    selected_image_index = context.user_data.get("selected_image_index")
    files = context.user_data.get("files", [])
    selected_image_name = files[selected_image_index]
    parts = selected_image_name.rsplit("_", maxsplit=-1)

    # Überprüfen, ob der Dateiname das erwartete Format hat (mindestens 4 Teile + Endung)
    if len(parts) < 4:
        await update.message.reply_text("❌ Fehler: Dateiname hat ein unerwartetes Format.")
        return

    # Entferne die Dateiendung (.png oder .jpg) aus dem letzten Teil
    file_extension = parts[-1].rsplit(".", maxsplit=1)[-1]
    parts[-1] = parts[-1].rsplit(".", maxsplit=1)[0]

    if edit_action == "change_title":
        new_title = update.message.text.strip().replace(" ", "-")
        parts[0] = new_title

    elif edit_action == "change_material":
        new_material = update.message.text.strip()
        if len(new_material.split()) > 1:
            await update.message.reply_text("❌ Fehler: Material kann nur ein Wort sein.")
            return
        parts[1] = new_material

    elif edit_action == "change_date":
        # Prüfe, ob der Monat bereits gesetzt ist
        if "selected_month" not in context.user_data:
            await update.message.reply_text("❌ Kein Monat gewählt. Bitte starte die Aktion erneut.")
            context.user_data["edit_action"] = None  # Aktion zurücksetzen
            return

        # Hole den Monat aus context.user_data
        selected_month = context.user_data["selected_month"].strip()

        # Prüfe, ob das Jahr bereits erwartet wird
        if "awaiting_year" not in context.user_data:
            # Fordere den Nutzer auf, das Jahr einzugeben
            await update.message.reply_text("Bitte gib das Jahr ein (z. B. 2025):")
            context.user_data["awaiting_year"] = True
            return

        # Verarbeite die Jahreingabe
        year = update.message.text.strip()
        if not year.isdigit():
            await update.message.reply_text("❌ Ungültiges Jahr. Bitte gib ein gültiges Jahr ein.")
            return

        # Jahr speichern und vollständiges Datum erstellen
        selected_year = year
        new_date = f"{selected_month}-{selected_year}" if selected_month != "none" else selected_year

        # Aktualisiere die Teile des Dateinamens
        parts[2] = new_date

        # Feedback an den Nutzer
        await update.message.reply_text(f"Datum erfolgreich geändert: {new_date}")

        # Kontext zurücksetzen
        context.user_data["edit_action"] = None
        context.user_data.pop("awaiting_year", None)
        context.user_data.pop("selected_month", None)



    elif edit_action == "change_availability":
        # Die Verfügbarkeit wird hier geändert, indem der entsprechende CallbackQueryHandler aufgerufen wird.
        pass

    elif edit_action == "change_dimensions":
        new_dimensions = update.message.text.strip().replace("x", "-")
        parts[3] = new_dimensions

    elif edit_action == "set_start_image":
        # Entferne _S von allen anderen Bildern
        for i, file in enumerate(files):
            if file.endswith("_S.png") or file.endswith("_S.jpg"):
                new_file_name = file.replace("_S", "")
                await rename_ftp_file(file, new_file_name)

        # Setze _S für das ausgewählte Bild
        if "_x" in parts[-1]:
            parts[-1] = parts[-1].replace("_x", "_S_x")
        else:
            parts[-1] += "_S"

    elif edit_action == "delete":
        if await delete_ftp_file(selected_image_name):
            await update.message.reply_text(f"Bild {selected_image_name} erfolgreich gelöscht.")
        else:
            await update.message.reply_text(f"Fehler beim Löschen des Bildes {selected_image_name}.")
        context.user_data[chat_id] = None  # Aktion abschließen
        return

    else:
        await update.message.reply_text("❌ Unbekannte Bearbeitungsaktion.")
        context.user_data[chat_id] = None  # Aktion abschließen
        return

    # Neuen Dateinamen zusammensetzen und Dateiendung wieder hinzufügen
    new_name = "_".join(parts) + "." + file_extension
    if await rename_ftp_file(selected_image_name, new_name):
        await update.message.reply_text(f"Aktion erfolgreich durchgeführt: {new_name}.")
    else:
        await update.message.reply_text("❌ Fehler bei der Durchführung der Aktion.")
   #clear context data
    context.user_data[chat_id] = None


def main():
    args = parse_args()

    application = Application.builder().token(BOT_TOKEN).build()



    # Handler für Start- und Hilfekommandos
# Handler für Start- und Hilfekommandos

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

    # Handler für das Auflisten von Bildern und das Anzeigen von Bildoptionen
    application.add_handler(CommandHandler("list", list_images,filters=User(ADMINISTRATOR_IDS)))
    application.add_handler(CallbackQueryHandler(show_image_options, pattern="select_"))

    # Handler für Bearbeitungsaktionen
    application.add_handler(CallbackQueryHandler(change_title, pattern="edit_title"))
    application.add_handler(CallbackQueryHandler(change_material, pattern="edit_material"))
    application.add_handler(CallbackQueryHandler(change_date, pattern="edit_date"))
    application.add_handler(CallbackQueryHandler(change_availability, pattern="edit_availability"))
    application.add_handler(CallbackQueryHandler(change_dimensions, pattern="edit_dimensions"))
    application.add_handler(CallbackQueryHandler(set_start_image, pattern="set_start_image"))
    application.add_handler(CallbackQueryHandler(delete_image, pattern="delete"))

#   handle
    application.add_handler(CallbackQueryHandler(handle_month_selection, pattern="Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|none"))

    # Handler für die Verfügbarkeit
    application.add_handler(CallbackQueryHandler(set_availability, pattern="set_available|set_unavailable"))

    # Handler für den Multi-Step-Prozess
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, multi_step_handler))
    application.add_handler(MessageHandler(filters.PHOTO & User(ADMINISTRATOR_IDS), receive_photo))

    # Bestätigungs- und Abbruch-Handler
    application.add_handler(CommandHandler("confirm", confirm))
    application.add_handler(CommandHandler("cancel", cancel))
    # admin handler

    # Webhook oder Polling Modus basierend auf der USAGE-Umgebungsvariablen
    if args.local:
        print("Bot läuft im lokalen Modus")
        application.run_polling()
    else:
        print("Bot läuft im Webhook-Modus")
        application.run_webhook(
            listen="0.0.0.0",
            port=int(os.getenv("PORT", 8443)),
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBURL}/{BOT_TOKEN}",
        )

if __name__ == "__main__":
    main()