import os
import asyncio
import argparse
import aioftp
import urllib.parse
from dotenv import load_dotenv
from PIL import Image

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    CallbackContext,
)
from telegram.ext.filters import User

# .env laden, falls vorhanden
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


def encode_title(title: str) -> str:
    """
    Ersetzt Leerzeichen durch Bindestriche und führt ein URL-Encoding für Sonderzeichen durch.
    """
    title = title.replace(" ", "-")
    return urllib.parse.quote(title)


async def ftp_connect():
    """
    Stellt eine Verbindung zum FTP-Server her bzw. erneuert diese, wenn sie abgebrochen wurde.
    """
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
            print("FTP-Verbindung verloren, erneuere die Verbindung.")
            ftp_client = aioftp.Client()
            await ftp_client.connect(FTP_HOST)
            await ftp_client.login(FTP_USER, FTP_PASS)
    return ftp_client


async def ftp_disconnect():
    """
    Trennt die Verbindung zum FTP-Server.
    """
    global ftp_client
    if ftp_client is not None:
        await ftp_client.quit()
        ftp_client = None
        print("FTP-Verbindung getrennt.")


def start_inactivity_timer():
    """
    Startet den Inaktivitäts-Timer (z.B. 300 Sekunden).
    Läuft dieser ab, wird ftp_disconnect() aufgerufen.
    """
    global inactivity_timer
    if inactivity_timer is not None:
        inactivity_timer.cancel()
    inactivity_timer = asyncio.get_event_loop().call_later(300, asyncio.create_task, ftp_disconnect())


async def upload_to_ftp(local_path: str, filename: str) -> bool:
    """
    Lädt eine Datei vom local_path unter dem Namen filename auf den FTP-Server hoch.
    """
    try:
        client = await ftp_connect()
        print(f"Lade Datei {local_path} hoch als {filename}")
        
        # Zielpfad anpassen, damit die Datei direkt im Wurzelverzeichnis landet
        target_path = f"/{filename}"
        print(f"Ziel: {target_path}")

        await client.upload(local_path, target_path, write_into=True)

        # Inaktivitäts-Timer neu starten
        start_inactivity_timer()
        return True
    except Exception as e:
        print(f"FTP-Upload-Fehler: {e}")
        return False


async def rename_ftp_file(old_name: str, new_name: str) -> bool:
    """
    Bennent eine Datei auf dem FTP-Server um.
    """
    try:
        client = await ftp_connect()
        await client.rename(old_name, new_name)
        start_inactivity_timer()
        print(f"Datei {old_name} umbenannt in {new_name}")
        return True
    except Exception as e:
        print(f"Fehler beim Umbenennen der Datei auf dem FTP-Server: {e}")
        return False


async def delete_ftp_file(file_name: str) -> bool:
    """
    Löscht eine Datei auf dem FTP-Server.
    """
    try:
        client = await ftp_connect()
        await client.remove_file(file_name)
        start_inactivity_timer()
        return True
    except Exception as e:
        print(f"Fehler beim Löschen der Datei auf dem FTP-Server: {e}")
        return False


async def list_ftp_files() -> list:
    """
    Listet alle Dateien im Root-Verzeichnis des FTP-Servers auf.
    """
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


# -----------------------------------------
#   HILFSFUNKTION ZUM KONVERTIEREN NACH WEBP
# -----------------------------------------
def convert_image_to_webp(input_path: str, output_path: str):
    """
    Konvertiert eine Bilddatei mithilfe von Pillow ins WebP-Format.
    """
    try:
        with Image.open(input_path) as img:
            # Optional kann man hier Quality oder andere Parameter setzen:
            img.save(output_path, format="WEBP")
        return True
    except Exception as e:
        print(f"Fehler beim Konvertieren nach WebP: {e}")
        return False


# -----------------------------------------
#   TELEGRAM HANDLER
# -----------------------------------------
async def start(update: Update, context: CallbackContext):
    # FTP-Verbindung aufbauen, Timer starten
    await ftp_connect()
    start_inactivity_timer()
    await update.message.reply_text(
        "Hallo! Sende mir ein Bild, um es hochzuladen. "
        "Anschließend kannst du Titel, Material, Datum (Monat/Jahr) und Maße festlegen.\n"
        "Verwende /help, um weitere Informationen zu erhalten."
    )


async def discard_changes(update: Update, context: CallbackContext):
    """
    Schließt die Bearbeitung ab, entfernt Inline-Keyboard und setzt Kontext zurück.
    """
    await update.callback_query.edit_message_reply_markup(reply_markup=None)
    context.user_data.clear()
    await update.callback_query.answer("Bearbeitungsaktion wurde abgeschlossen.")
    await update.callback_query.message.reply_text("Bearbeitungsaktion wurde abgeschlossen.")


async def help_command(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "Verfügbare Befehle:\n"
        "/start - Startet den Bot\n"
        "/help - Zeigt diese Hilfe an\n"
        "/list - Listet alle Bilder auf dem FTP auf\n"
        "/convert - Konvertiert alle Bilder auf dem FTP in WebP\n"
    )


async def list_images(update: Update, context: CallbackContext):
    """
    Listet alle Bilder vom FTP auf und zeigt ein Inline-Keyboard, um eines auszuwählen.
    """
    files = await list_ftp_files()
    if not files:
        await update.message.reply_text("📂 Keine Bilder gefunden.")
        return

    # Nur den Titel also alles bis zum ersten _ und alle - mit " " ersetzen
    titles = [f.split("_")[0].replace("-", " ") for f in files]
    keyboard = [
        [InlineKeyboardButton(f"{i+1}. {titles[i]}", callback_data=f"select_{i}")]
        for i in range(len(files))
    ]

    context.user_data["files"] = files
    await update.message.reply_text(
        "📂 Verfügbare Bilder:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_image_options(update: Update, context: CallbackContext):
    """
    Zeigt das Bearbeitungsmenü für ein ausgewähltes Bild.
    """
    await update.callback_query.message.edit_reply_markup(reply_markup=None)
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

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.message.reply_text(
        "Bitte wähle eine Bearbeitungsoption:",
        reply_markup=reply_markup
    )


# -----------------------------------------
#   BEARBEITUNGSAKTIONEN
# -----------------------------------------
async def change_title(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "change_title"
    await query.edit_message_text("Bitte sende den neuen Titel für das Bild (keine Bindestriche oder Unterstriche):")


async def change_material(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "change_material"
    await query.edit_message_text("Bitte sende das neue Material für das Bild (nur Buchstaben, keine Bindestriche/Unterstriche):")


async def change_date(update: Update, context: CallbackContext):
    """
    Startet den Prozess des Datumswechsels (Monat + Jahr).
    """
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "change_date"

    # Inline-Keyboard zur Monatseingabe
    keyboard = [
        [InlineKeyboardButton("Kein Monat angeben", callback_data="none")],
        [
            InlineKeyboardButton("Januar", callback_data="Januar"),
            InlineKeyboardButton("Februar", callback_data="Februar"),
            InlineKeyboardButton("März", callback_data="März"),
        ],
        [
            InlineKeyboardButton("April", callback_data="April"),
            InlineKeyboardButton("Mai", callback_data="Mai"),
            InlineKeyboardButton("Juni", callback_data="Juni"),
        ],
        [
            InlineKeyboardButton("Juli", callback_data="Juli"),
            InlineKeyboardButton("August", callback_data="August"),
            InlineKeyboardButton("September", callback_data="September"),
        ],
        [
            InlineKeyboardButton("Oktober", callback_data="Oktober"),
            InlineKeyboardButton("November", callback_data="November"),
            InlineKeyboardButton("Dezember", callback_data="Dezember"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Bitte wähle den Monat aus:", reply_markup=reply_markup)


async def change_availability(update: Update, context: CallbackContext):
    """
    Ändert die Verfügbarkeit eines Bildes (Suffix _x).
    """
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "change_availability"
    keyboard = [
        [InlineKeyboardButton("Verfügbar", callback_data="set_available")],
        [InlineKeyboardButton("Nicht verfügbar", callback_data="set_unavailable")]
    ]
    await query.edit_message_text(
        "Bitte wähle die Verfügbarkeit aus:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def set_availability(update: Update, context: CallbackContext):
    """
    Setzt Verfügbarkeit (_x = nicht verfügbar) oder entfernt das Suffix.
    """
    query = update.callback_query
    availability_status = query.data
    files = context.user_data.get("files", [])
    selected_image_index = context.user_data.get("selected_image_index")
    selected_image_name = files[selected_image_index]

    # Endung abtrennen
    if "." in selected_image_name:
        name_part, file_extension = selected_image_name.rsplit(".", 1)
    else:
        name_part = selected_image_name
        file_extension = ""

    rename_needed = False

    if availability_status == "set_available":
        # Entferne _x
        if name_part.endswith("_x"):
            name_part = name_part[:-2]
            rename_needed = True
        elif name_part.endswith("_x_S"):
            name_part = name_part[:-4] + "_S"
            rename_needed = True
    elif availability_status == "set_unavailable":
        # Füge _x hinzu
        if not name_part.endswith("_x") and not name_part.endswith("_x_S"):
            if name_part.endswith("_S"):
                name_part = name_part[:-2] + "_x_S"
            else:
                name_part += "_x"
            rename_needed = True

    if rename_needed:
        new_name = f"{name_part}.{file_extension}" if file_extension else name_part
        if await rename_ftp_file(selected_image_name, new_name):
            await query.edit_message_text(f"Verfügbarkeit erfolgreich geändert: {new_name}.")
        else:
            await query.edit_message_text("❌ Fehler bei der Durchführung der Aktion.")
    else:
        await query.edit_message_text("Keine Änderung erforderlich. Dateiname bleibt unverändert.")

    context.user_data["edit_action"] = None  # Aktion abschließen


async def change_dimensions(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "change_dimensions"
    await query.edit_message_text("Bitte sende die neuen Maße im Format 'Breite x Höhe':")


async def set_start_image(update: Update, context: CallbackContext):
    """
    Setzt für ein Bild das Suffix _S als "Startbild" und entfernt es für andere.
    """
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "set_start_image"
    await query.edit_message_text(
        "Möchtest du dieses Bild als Startbild festlegen? Bestätige mit /confirm oder brich ab mit /cancel."
    )


async def delete_image(update: Update, context: CallbackContext):
    """
    Löscht das ausgewählte Bild (per /confirm bestätigen).
    """
    query = update.callback_query
    await query.answer()
    context.user_data["edit_action"] = "delete"
    await query.edit_message_text(
        "Möchtest du dieses Bild wirklich löschen? Bestätige mit /confirm oder brich ab mit /cancel."
    )


async def confirm(update: Update, context: CallbackContext):
    """
    Bestätigt Löschaktion oder Setzen des Startbildes.
    """
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
            if file.endswith("_S.png") or file.endswith("_S.jpg") or file.endswith("_S.webp"):
                new_file_name = file.replace("_S", "")
                await rename_ftp_file(file, new_file_name)
        # Füge beim ausgewählten Bild _S hinzu
        parts = selected_image_name.rsplit(".", maxsplit=1)
        if len(parts) == 2:
            name, extension = parts
            if "_x." in name or "_x_" in name:
                name = name.replace("_x", "_x_S")  # Falls bereits _x existiert
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


async def cancel(update: Update, context: CallbackContext):
    """
    Bricht eine Aktion ab.
    """
    context.user_data[update.message.chat.id] = None
    await update.message.reply_text("❌ Aktion abgebrochen.")


# -----------------------------------------
#   FOTO-UPLOAD
# -----------------------------------------
async def receive_photo(update: Update, context: CallbackContext):
    """
    Nimmt ein Foto entgegen und speichert es lokal. Dann startet der Dialog zur Eingabe von Titel etc.
    """
    photo = update.message.photo[-1]  # Nimm die höchste Auflösung
    file = await context.bot.get_file(photo.file_id)

    # Ursprüngliche Dateiendung ermitteln
    original_file_extension = os.path.splitext(file.file_path)[-1].lower()
    # Falls Telegram-URL-Ende keine eindeutige Endung hat, defaulten wir auf .jpg
    if original_file_extension not in [".jpg", ".jpeg", ".png", ".webp"]:
        original_file_extension = ".jpg"

    local_path = os.path.join(LOCAL_DOWNLOAD_PATH, f"{photo.file_id}{original_file_extension}")
    await file.download_to_drive(local_path)

    # Start der Dialog-Schritte
    context.user_data["photo_upload"] = True
    context.user_data["current_photo_path"] = local_path
    context.user_data["current_file_extension"] = original_file_extension
    context.user_data["upload_step"] = "title"  # Erster Schritt: Titel

    await update.message.reply_text("📷 Foto empfangen! Bitte gib einen Titel ein (keine Bindestriche/Unterstriche):")


async def photo_upload_dialog(update: Update, context: CallbackContext):
    """
    Multi-Step-Dialog für den Upload eines Fotos mit Titel, Material, Datum und Maßen.
    """
    if not context.user_data.get("photo_upload"):
        return  # Kein aktiver Foto-Upload → Ignoriere Texteingaben

    upload_step = context.user_data.get("upload_step")
    if not upload_step:
        await update.message.reply_text("❌ Kein Upload-Prozess aktiv. Sende ein Foto, um zu starten.")
        return

    # Schritt 1: Titel
    if upload_step == "title":
        title = update.message.text.strip()
        if "-" in title or "_" in title:
            await update.message.reply_text(
                "❌ Fehler: Titel darf keine Bindestriche oder Unterstriche enthalten. Bitte versuche es erneut."
            )
            return
        context.user_data["title"] = encode_title(title)
        context.user_data["upload_step"] = "material"
        await update.message.reply_text("Bitte gib das Material ein (nur Buchstaben, keine Bindestriche/Unterstriche):")

    # Schritt 2: Material
    elif upload_step == "material":
        material = update.message.text.strip()
        # Beispielhafte Prüfung
        if not material.isalpha() or "-" in material or "_" in material:
            await update.message.reply_text(
                "❌ Fehler: Material darf nur alphabetische Zeichen enthalten und keine Bindestriche/Unterstriche. Bitte erneut versuchen."
            )
            return
        context.user_data["material"] = material
        # Inline-Keyboard für Monat
        keyboard = [
            [InlineKeyboardButton("Kein Monat angeben", callback_data="none")],
            [
                InlineKeyboardButton("Januar", callback_data="Januar"),
                InlineKeyboardButton("Februar", callback_data="Februar"),
                InlineKeyboardButton("März", callback_data="März"),
            ],
            [
                InlineKeyboardButton("April", callback_data="April"),
                InlineKeyboardButton("Mai", callback_data="Mai"),
                InlineKeyboardButton("Juni", callback_data="Juni"),
            ],
            [
                InlineKeyboardButton("Juli", callback_data="Juli"),
                InlineKeyboardButton("August", callback_data="August"),
                InlineKeyboardButton("September", callback_data="September"),
            ],
            [
                InlineKeyboardButton("Oktober", callback_data="Oktober"),
                InlineKeyboardButton("November", callback_data="November"),
                InlineKeyboardButton("Dezember", callback_data="Dezember"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.user_data["upload_step"] = "choose_month"
        await update.message.reply_text("Bitte wähle den Monat aus:", reply_markup=reply_markup)

    # Schritt 3a: Wenn der User den Monat bereits gewählt hat (upload_step == "year") → Jahr eingeben
    elif upload_step == "year":
        year = update.message.text.strip()
        if not year.isdigit() or len(year) != 4:
            await update.message.reply_text("❌ Ungültiges Jahr. Bitte gib ein gültiges Jahr ein (z.B. 2024).")
            return
        context.user_data["year"] = year
        context.user_data["upload_step"] = "dimensions"
        await update.message.reply_text("Bitte gib die Maße im Format 'Breite x Höhe' ein:")

    # Schritt 4: Maße
    elif upload_step == "dimensions":
        dimensions = update.message.text.strip().replace(" ", "")
        if ("x" not in dimensions) or ("-" in dimensions) or ("_" in dimensions):
            await update.message.reply_text(
                "❌ Fehler: Maße müssen im Format 'Breite x Höhe' sein (keine Bindestriche/Unterstriche). Versuche es erneut."
            )
            return
        context.user_data["dimensions"] = dimensions
        # Jetzt wird hochgeladen
        await upload_photo(update, context)

        # Upload abgeschlossen: Context aufräumen
        context.user_data.pop("upload_step", None)
        context.user_data.pop("photo_upload", None)
        context.user_data.pop("current_photo_path", None)
        context.user_data.pop("current_file_extension", None)
        context.user_data.pop("title", None)
        context.user_data.pop("material", None)
        context.user_data.pop("year", None)
        context.user_data.pop("selected_month", None)


async def upload_photo(update: Update, context: CallbackContext):
    """
    Führt die tatsächliche Umwandlung nach WebP und den Upload zum FTP durch.
    """
    local_path = context.user_data.get("current_photo_path")
    original_extension = context.user_data.get("current_file_extension", ".jpg")
    title = context.user_data.get("title", "no-title").replace(" ", "-")
    material = context.user_data.get("material", "unknown").replace(" ", "-")
    month = context.user_data.get("selected_month", "")
    year = context.user_data.get("year", "")
    dimensions = context.user_data.get("dimensions", "").replace("x", "-")

    # Monat/Jahr kombinieren
    if month and month != "none" and year:
        date_str = f"{month}-{year}"
    elif month and month != "none":
        date_str = month
    else:
        date_str = year if year else ""

    # Dateinamen zusammensetzen
    # Beispiel: TTT_MMM_Monat-Jahr_BxH.webp
    filename = f"{title}_{material}"
    if date_str:
        filename += f"_{date_str}"
    if dimensions:
        filename += f"_{dimensions}"
    # final .webp
    filename += ".webp"

    # Lokaler Name, den wir hochladen wollen (nach Konvertierung):
    new_local_path = os.path.join(LOCAL_DOWNLOAD_PATH, filename)

    # 1) Zuerst in WebP konvertieren
    success = convert_image_to_webp(local_path, new_local_path)
    if not success:
        await update.message.reply_text("❌ Fehler beim Konvertieren in WebP.")
        return

    # 2) Upload zum FTP
    success = await upload_to_ftp(new_local_path, filename)
    if success:
        await update.message.reply_text(f"✅ Bild erfolgreich hochgeladen als: {filename}")
    else:
        await update.message.reply_text("❌ Fehler beim Hochladen des Bildes.")

    # 3) Lokale Dateien wieder entfernen
    if os.path.exists(local_path):
        os.remove(local_path)
    if os.path.exists(new_local_path):
        os.remove(new_local_path)


async def handle_month_selection(update: Update, context: CallbackContext):
    """
    CallbackQueryHandler, der den ausgewählten Monat entgegennimmt und anschließend nach dem Jahr fragt.
    """
    query = update.callback_query
    await query.answer()

    selected_month = query.data  # z.B. 'Januar', 'Februar', ... oder 'none'

    if selected_month != "none":
        context.user_data["selected_month"] = selected_month
        await query.edit_message_text(f"Du hast {selected_month} ausgewählt. Bitte gib nun das Jahr ein (z.B. 2024):")
    else:
        context.user_data["selected_month"] = ""
        await query.edit_message_text("Kein Monat ausgewählt. Bitte gib nun das Jahr ein (z.B. 2024) oder lass es leer.")

    context.user_data["upload_step"] = "year"


# -----------------------------------------
#   MULTI-STEP-HANDLER FÜR BEARBEITUNGEN
# -----------------------------------------
async def multi_step_handler(update: Update, context: CallbackContext):
    """
    Wird aufgerufen, wenn der Nutzer etwas eintippt (TEXT), während eine Bearbeitungsaktion läuft.
    Oder wenn ein Foto-Upload läuft, leiten wir an photo_upload_dialog weiter.
    """
    # 1) Handhaben, wenn gerade ein Foto-Upload-Prozess aktiv ist
    if context.user_data.get("photo_upload"):
        await photo_upload_dialog(update, context)
        return

    # 2) Liegt eine Bearbeitungsaktion vor?
    edit_action = context.user_data.get("edit_action")
    if not edit_action:
        await update.message.reply_text("❌ Keine Bearbeitungsaktion gestartet. Bitte wähle zuerst eine Option aus dem Menü.")
        return

    # Wenn eine Bearbeitung eines vorhandenen Bildes läuft:
    files = context.user_data.get("files", [])
    selected_image_index = context.user_data.get("selected_image_index")
    if selected_image_index is None or selected_image_index >= len(files):
        await update.message.reply_text("❌ Kein gültiges Bild ausgewählt.")
        return

    selected_image_name = files[selected_image_index]
    parts = selected_image_name.rsplit("_", maxsplit=3)  # versuche den Dateinamen in 4 Blöcke zu teilen
    # Wir müssen die Dateiendung noch isolieren
    file_extension = ""
    if "." in parts[-1]:
        last_part, file_extension = parts[-1].rsplit(".", 1)
        parts[-1] = last_part

    # Notfallprüfung
    if len(parts) < 1:
        await update.message.reply_text("❌ Fehler: Dateiname hat ein unerwartetes Format.")
        return

    # Nun die Bearbeitung:
    if edit_action == "change_title":
        new_title = update.message.text.strip()
        if "-" in new_title or "_" in new_title:
            await update.message.reply_text("❌ Titel darf keine Bindestriche oder Unterstriche enthalten.")
            return
        parts[0] = encode_title(new_title)
        await finalize_rename(update, context, parts, file_extension)

    elif edit_action == "change_material":
        new_material = update.message.text.strip()
        if not new_material.isalpha() or "-" in new_material or "_" in new_material:
            await update.message.reply_text("❌ Material darf nur Buchstaben enthalten. Keine Bindestriche/Unterstriche.")
            return
        # Wir nehmen an, dass parts[1] existiert, sonst müssen wir anpassen
        if len(parts) < 2:
            parts.append(new_material)
        else:
            parts[1] = new_material
        await finalize_rename(update, context, parts, file_extension)

    elif edit_action == "change_date":
        # In diesem Flow haben wir schon den Monat per InlineKeyboard:
        if "selected_month" not in context.user_data:
            await update.message.reply_text("❌ Kein Monat gewählt. Bitte nutze das Menü erneut.")
            context.user_data["edit_action"] = None
            return

        # Wir warten hier auf das Jahr
        year = update.message.text.strip()
        if not year.isdigit() or len(year) != 4:
            await update.message.reply_text("❌ Ungültiges Jahr. Bitte gib ein 4-stelliges Jahr ein.")
            return

        selected_month = context.user_data["selected_month"]
        if selected_month and selected_month != "none":
            new_date = f"{selected_month}-{year}"
        else:
            new_date = year  # nur Jahr
        # Wir nehmen an, das parts[2] existiert
        if len(parts) < 3:
            # ggf. auffüllen
            while len(parts) < 3:
                parts.append("")  
        parts[2] = new_date
        # Aufräumen
        context.user_data.pop("selected_month", None)
        await finalize_rename(update, context, parts, file_extension)

    elif edit_action == "change_dimensions":
        new_dimensions = update.message.text.strip().replace(" ", "")
        if "x" not in new_dimensions or "-" in new_dimensions or "_" in new_dimensions:
            await update.message.reply_text("❌ Maße müssen im Format 'Breite x Höhe' (keine Bindestriche/Unterstriche).")
            return
        if len(parts) < 4:
            while len(parts) < 4:
                parts.append("")  
        parts[3] = new_dimensions
        await finalize_rename(update, context, parts, file_extension)

    else:
        await update.message.reply_text("❌ Unbekannte Bearbeitungsaktion.")
        context.user_data["edit_action"] = None


async def finalize_rename(update: Update, context: CallbackContext, parts: list, file_extension: str):
    """
    Hilfsfunktion, um das Umbennen auf dem FTP durchzuführen und dem Nutzer das Ergebnis zu melden.
    Anschließend werden wieder die Bildoptionen gezeigt.
    """
    files = context.user_data.get("files", [])
    selected_image_index = context.user_data.get("selected_image_index")
    old_name = files[selected_image_index]

    # Neuen Dateinamen zusammenbauen
    new_name_parts = []
    for p in parts:
        if p:  # Nur nicht-leere Teile hinzufügen
            new_name_parts.append(p)
    new_name = "_".join(new_name_parts)
    if file_extension:
        new_name += f".{file_extension}"

    success = await rename_ftp_file(old_name, new_name)
    if success:
        # In der Liste ersetzen
        files[selected_image_index] = new_name
        await update.message.reply_text(f"✅ Aktion erfolgreich durchgeführt: {new_name}.")
    else:
        await update.message.reply_text("❌ Fehler bei der Durchführung der Aktion.")

    # Bearbeitung beenden
    context.user_data["edit_action"] = None
    # Nochmal das Optionen-Menü anbieten:
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
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Bitte wähle eine Bearbeitungsoption:", reply_markup=reply_markup)


# -----------------------------------------
#   /convert-BEFEHL: ALLE FTP-DATEIEN IN WEBP KONVERTIEREN
# -----------------------------------------
async def convert_all_images_to_webp(update: Update, context: CallbackContext):
    """
    /convert-Befehl: Lädt alle Dateien vom FTP herunter, wandelt sie in WebP um
    und lädt sie mit gleichem Basisnamen (aber .webp) wieder hoch. Original wird gelöscht.
    """
    await update.message.reply_text("Starte Konvertierung aller Bilder zu WebP ...")
    files = await list_ftp_files()
    if not files:
        await update.message.reply_text("Keine Dateien auf dem FTP gefunden.")
        return

    converted_count = 0
    client = await ftp_connect()
    for f in files:
        # Prüfe, ob es bereits .webp ist
        if f.lower().endswith(".webp"):
            print(f"Datei {f} ist bereits webp, überspringe.")
            continue

        # Lade die Datei herunter
        local_temp_path = os.path.join(LOCAL_DOWNLOAD_PATH, f)
        try:
            await client.download(f, local_temp_path,write_into=True)
        except Exception as e:
            await update.message.reply_text(f"Fehler beim Download von {f}: {e}")
            continue

        # Dateiendung rausfischen
        base_name, ext = os.path.splitext(f)
        new_name = base_name + ".webp"
        local_converted_path = os.path.join(LOCAL_DOWNLOAD_PATH, new_name)

        # Konvertiere nach WebP
        success = convert_image_to_webp(local_temp_path, local_converted_path)
        if not success:
            await update.message.reply_text(f"Fehler beim Konvertieren von {f} nach WebP.")
            # Lokale Dateien wegräumen
            if os.path.exists(local_temp_path):
                print(f"Lösche temporäre Datei {local_temp_path}")
                try:
                    os.remove(local_temp_path)
                except Exception as e:
                    print(f"Fehler beim Löschen der temporären Datei: {e}")
            if os.path.exists(local_converted_path):
                os.remove(local_converted_path)
            continue

        # WebP wieder hochladen
        upload_success = await upload_to_ftp(local_converted_path, new_name)
        if upload_success:
            converted_count += 1
            # Original auf FTP löschen
            await delete_ftp_file(f)
        else:
            await update.message.reply_text(f"Fehler beim Hochladen von {new_name}.")

        # Lokale Dateien wegräumen
        if os.path.exists(local_temp_path):
            os.remove(local_temp_path)
        if os.path.exists(local_converted_path):
            os.remove(local_converted_path)

    await update.message.reply_text(f"Konvertierung abgeschlossen. {converted_count} Dateien wurden nach WebP konvertiert.")
    # Timer neu starten
    start_inactivity_timer()


# -----------------------------------------
#   HAUPTPROGRAMM
# -----------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(description="Start the bot in either local or webhook mode.")
    parser.add_argument("--local", action="store_true", help="Run the bot in local polling mode.")
    return parser.parse_args()


def main():
    args = parse_args()
    application = Application.builder().token(BOT_TOKEN).build()

    # Start/Hilfe
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

    # Bilder auflisten, Optionen anzeigen
    application.add_handler(CommandHandler("list", list_images, filters=User(ADMINISTRATOR_IDS)))
    application.add_handler(CallbackQueryHandler(show_image_options, pattern="select_"))

    # Bearbeitungsoptionen
    application.add_handler(CallbackQueryHandler(change_title, pattern="edit_title"))
    application.add_handler(CallbackQueryHandler(change_material, pattern="edit_material"))
    application.add_handler(CallbackQueryHandler(change_date, pattern="edit_date"))
    application.add_handler(CallbackQueryHandler(change_availability, pattern="edit_availability"))
    application.add_handler(CallbackQueryHandler(change_dimensions, pattern="edit_dimensions"))
    application.add_handler(CallbackQueryHandler(set_start_image, pattern="set_start_image"))
    application.add_handler(CallbackQueryHandler(delete_image, pattern="delete"))
    application.add_handler(CallbackQueryHandler(discard_changes, pattern="discard_changes"))

    # Verfügbarkeit
    application.add_handler(CallbackQueryHandler(set_availability, pattern="set_available|set_unavailable"))

    # Monat für Datum beim Hochladen oder nachträglich ändern
    application.add_handler(
        CallbackQueryHandler(
            handle_month_selection,
            pattern="Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|none"
        )
    )

    # Multi-Step-Eingaben (Titel/Material/Datum usw.)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, multi_step_handler))

    # Fotoempfang
    application.add_handler(MessageHandler(filters.PHOTO & User(ADMINISTRATOR_IDS), receive_photo))

    # Bestätigung/Abbruch
    application.add_handler(CommandHandler("confirm", confirm))
    application.add_handler(CommandHandler("cancel", cancel))

    # /convert
    application.add_handler(CommandHandler("convert", convert_all_images_to_webp, filters=User(ADMINISTRATOR_IDS)))

    # Webhook vs. Polling
    if args.local:
        print("Bot läuft im lokalen Polling-Modus.")
        application.run_polling()
    else:
        print("Bot läuft im Webhook-Modus.")
        application.run_webhook(
            listen="0.0.0.0",
            port=int(os.getenv("PORT", 8443)),
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBURL}/{BOT_TOKEN}",
        )


if __name__ == "__main__":
    main()
