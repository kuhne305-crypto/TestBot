import discord
from discord.ext import commands
from discord import app_commands
import json
import os

# ─── CONFIG ───────────────────────────────────────────────────────────────────
TOKEN = os.environ.get("DISCORD_TOKEN")
GUILD_ID = os.environ.get("GUILD_ID")  # deine Server-ID als Railway Variable
EMBED_COLOR = 0x5865F2  # Discord Blurple (neutral)
DATA_FILE = "data.json"

# ─── DATA HANDLER ─────────────────────────────────────────────────────────────
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {
        "familien": {},                    # { "blau": {"passwort": "blau", "rolle_id": "123"} }
        "verifizierung_channel": None,
        "verifizierung_nachricht_id": None
    }

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

data = load_data()

# ─── BOT SETUP ────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ─── EMBED & VIEW BUILDER ─────────────────────────────────────────────────────
def build_familien_embed():
    embed = discord.Embed(
        title="Familien-Auswahl",
        description=(
            "Wähle deine Familie aus, um Zugriff auf die passenden Channels zu bekommen.\n"
            "Klick auf den passenden Button und trag deinen Namen sowie das Passwort deiner Familie ein."
        ),
        color=EMBED_COLOR
    )
    if not data["familien"]:
        embed.add_field(
            name="Noch keine Familien eingerichtet",
            value="Ein Admin muss zuerst /familie_hinzufuegen benutzen.",
            inline=False
        )
    else:
        namen = ", ".join(name.capitalize() for name in data["familien"].keys())
        embed.add_field(name="Verfügbare Familien", value=namen, inline=False)
    embed.set_footer(text="Verifizierung")
    return embed

async def familie_button_callback(interaction: discord.Interaction):
    custom_id = interaction.data["custom_id"]
    familie_key = custom_id.split("::", 1)[1]
    if familie_key not in data["familien"]:
        await interaction.response.send_message("❌ Diese Familie existiert nicht mehr.", ephemeral=True)
        return
    modal = FamilieModal(familie_key)
    await interaction.response.send_modal(modal)

def build_familien_view():
    view = discord.ui.View(timeout=None)
    styles = [
        discord.ButtonStyle.primary,
        discord.ButtonStyle.success,
        discord.ButtonStyle.danger,
        discord.ButtonStyle.secondary,
    ]
    for i, name in enumerate(data["familien"].keys()):
        button = discord.ui.Button(
            label=name.capitalize(),
            style=styles[i % len(styles)],
            custom_id=f"familie_btn::{name}"
        )
        button.callback = familie_button_callback
        view.add_item(button)
    return view

# ─── MODAL (Name + Passwort Eingabe) ──────────────────────────────────────────
class FamilieModal(discord.ui.Modal):
    def __init__(self, familie_key: str):
        super().__init__(title=f"Familie {familie_key.capitalize()}")
        self.familie_key = familie_key
        self.name_input = discord.ui.TextInput(
            label="Dein Name (Vorname Nachname)",
            placeholder="Max Mustermann",
            required=True,
            max_length=32
        )
        self.passwort_input = discord.ui.TextInput(
            label="Passwort der Familie",
            placeholder="Passwort eingeben",
            required=True,
            max_length=64
        )
        self.add_item(self.name_input)
        self.add_item(self.passwort_input)

    async def on_submit(self, interaction: discord.Interaction):
        familie = data["familien"].get(self.familie_key)
        if not familie:
            await interaction.response.send_message("❌ Diese Familie existiert nicht mehr.", ephemeral=True)
            return

        eingegeben = self.passwort_input.value.strip()
        korrekt    = familie["passwort"]

        if eingegeben.lower() != korrekt.lower():
            await interaction.response.send_message(
                "❌ Falsches Passwort. Klick einfach nochmal auf den Button und versuch's erneut.",
                ephemeral=True
            )
            return

        rolle = interaction.guild.get_role(int(familie["rolle_id"]))
        if not rolle:
            await interaction.response.send_message(
                "❌ Die Rolle für diese Familie wurde nicht gefunden. Bitte einen Admin kontaktieren.",
                ephemeral=True
            )
            return

        member = interaction.user

        # Alte Familien-Rolle entfernen, falls jemand die Familie wechselt
        alle_familien_rollen_ids = {int(f["rolle_id"]) for f in data["familien"].values()}
        alte_rollen = [r for r in member.roles if r.id in alle_familien_rollen_ids and r.id != rolle.id]
        if alte_rollen:
            try:
                await member.remove_roles(*alte_rollen)
            except discord.Forbidden:
                pass

        try:
            await member.add_roles(rolle)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Ich habe keine Berechtigung, dir diese Rolle zu geben. Bitte einen Admin kontaktieren "
                "(meine Bot-Rolle muss über der Familien-Rolle stehen).",
                ephemeral=True
            )
            return

        name_eingabe = self.name_input.value.strip()
        nickname_fehler = False
        try:
            await member.edit(nick=name_eingabe)
        except discord.Forbidden:
            nickname_fehler = True

        antwort = f"✅ Willkommen bei **{self.familie_key.capitalize()}**! Du hast jetzt Zugriff auf die passenden Channels."
        if nickname_fehler:
            antwort += "\n⚠️ Dein Nickname konnte nicht automatisch geändert werden (fehlende Berechtigung, z.B. bei Server-Owner)."

        await interaction.response.send_message(antwort, ephemeral=True)

# ─── VERIFIZIERUNGS-NACHRICHT POSTEN / AKTUALISIEREN ─────────────────────────
async def verifizierung_posten_intern(guild):
    if not data.get("verifizierung_channel"):
        return
    kanal = guild.get_channel(int(data["verifizierung_channel"]))
    if not kanal:
        return

    embed = build_familien_embed()
    view  = build_familien_view()

    msg_id = data.get("verifizierung_nachricht_id")
    if msg_id:
        try:
            msg = await kanal.fetch_message(int(msg_id))
            await msg.edit(embed=embed, view=view)
            bot.add_view(view, message_id=msg.id)
            return
        except Exception as e:
            print(f"Alte Verifizierungs-Nachricht nicht gefunden, poste neu: {e}")

    msg = await kanal.send(embed=embed, view=view)
    data["verifizierung_nachricht_id"] = str(msg.id)
    save_data(data)
    bot.add_view(view, message_id=msg.id)

# ─── SLASH COMMANDS ───────────────────────────────────────────────────────────

@tree.command(name="familie_hinzufuegen", description="Erstellt eine neue Familie: Rolle + Kategorie + Channels (Chat, Mitglieder, Infos)")
@app_commands.describe(
    name="Name der Familie (z.B. Rot, Blau)",
    passwort="Passwort für diese Familie"
)
@app_commands.checks.has_permissions(administrator=True)
async def familie_hinzufuegen(interaction: discord.Interaction, name: str, passwort: str):
    key = name.strip().lower()
    if key in data["familien"]:
        await interaction.response.send_message(
            f"❌ Familie **{name}** existiert bereits.\n"
            f"Nutze **/familie_entfernen** falls du sie komplett neu aufsetzen willst.",
            ephemeral=True
        )
        return

    # Rolle-/Kategorie-/Channel-Erstellung kann länger als 3 Sekunden dauern
    await interaction.response.defer(ephemeral=True)

    guild = interaction.guild

    try:
        rolle = await guild.create_role(
            name=f"Familie {name.capitalize()}",
            mentionable=True,
            reason=f"Familie {name} angelegt via /familie_hinzufuegen"
        )

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            rolle:               discord.PermissionOverwrite(view_channel=True),
            guild.me:            discord.PermissionOverwrite(view_channel=True),
        }

        kategorie = await guild.create_category(
            name=f"Familie {name.capitalize()}",
            overwrites=overwrites,
            reason=f"Familie {name} angelegt"
        )

        chat_ch       = await guild.create_text_channel("chat",       category=kategorie, overwrites=overwrites)
        mitglieder_ch = await guild.create_text_channel("mitglieder", category=kategorie, overwrites=overwrites)
        infos_ch      = await guild.create_text_channel("infos",      category=kategorie, overwrites=overwrites)

    except discord.Forbidden:
        await interaction.followup.send(
            "❌ Mir fehlen die Berechtigungen um Rollen/Kategorien/Channels zu erstellen.\n"
            "Der Bot braucht **Manage Roles** und **Manage Channels**.",
            ephemeral=True
        )
        return

    data["familien"][key] = {
        "passwort": passwort.strip(),
        "rolle_id": str(rolle.id),
        "kategorie_id": str(kategorie.id),
        "channels": {
            "chat": str(chat_ch.id),
            "mitglieder": str(mitglieder_ch.id),
            "infos": str(infos_ch.id),
        }
    }
    save_data(data)

    await interaction.followup.send(
        f"✅ Familie **{name}** komplett eingerichtet!\n\n"
        f"**Rolle:** {rolle.mention}\n"
        f"**Kategorie:** {kategorie.name}\n"
        f"**Channels:** {chat_ch.mention}, {mitglieder_ch.mention}, {infos_ch.mention}\n\n"
        f"Nicht vergessen: **/verifizierung_posten** benutzen, damit der neue Button auftaucht!",
        ephemeral=True
    )

@tree.command(name="familie_entfernen", description="Entfernt eine Familie inkl. Rolle, Kategorie und Channels")
@app_commands.describe(name="Name der Familie die entfernt werden soll")
@app_commands.checks.has_permissions(administrator=True)
async def familie_entfernen(interaction: discord.Interaction, name: str):
    key = name.strip().lower()
    if key not in data["familien"]:
        await interaction.response.send_message(f"❌ Familie **{name}** existiert nicht.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    guild  = interaction.guild
    info   = data["familien"][key]

    # Channels löschen
    for channel_id in info.get("channels", {}).values():
        kanal = guild.get_channel(int(channel_id))
        if kanal:
            try:
                await kanal.delete(reason=f"Familie {name} entfernt")
            except discord.Forbidden:
                pass

    # Kategorie löschen
    kategorie_id = info.get("kategorie_id")
    if kategorie_id:
        kategorie = guild.get_channel(int(kategorie_id))
        if kategorie:
            try:
                await kategorie.delete(reason=f"Familie {name} entfernt")
            except discord.Forbidden:
                pass

    # Rolle löschen
    rolle = guild.get_role(int(info["rolle_id"]))
    if rolle:
        try:
            await rolle.delete(reason=f"Familie {name} entfernt")
        except discord.Forbidden:
            pass

    del data["familien"][key]
    save_data(data)

    await interaction.followup.send(
        f"✅ Familie **{name}** komplett entfernt (Rolle, Kategorie und Channels gelöscht).\n"
        f"Nicht vergessen: **/verifizierung_posten** benutzen, damit der Button verschwindet!",
        ephemeral=True
    )

@tree.command(name="familien", description="Zeigt alle eingerichteten Familien")
@app_commands.checks.has_permissions(administrator=True)
async def familien_liste(interaction: discord.Interaction):
    if not data["familien"]:
        await interaction.response.send_message("❌ Noch keine Familien eingerichtet.", ephemeral=True)
        return
    zeilen = []
    for key, info in data["familien"].items():
        rolle     = interaction.guild.get_role(int(info["rolle_id"]))
        kategorie = interaction.guild.get_channel(int(info["kategorie_id"])) if info.get("kategorie_id") else None
        zeilen.append(
            f"**{key.capitalize()}** — Passwort: `{info['passwort']}` — "
            f"Rolle: {rolle.mention if rolle else '❌ nicht gefunden'} — "
            f"Kategorie: {kategorie.name if kategorie else '❌ nicht gefunden'}"
        )
    await interaction.response.send_message("\n".join(zeilen), ephemeral=True)

@tree.command(name="set_verifizierung_channel", description="Setzt den Channel für die Familien-Auswahl-Nachricht")
@app_commands.describe(channel="Der Channel wo neue Mitglieder ihre Familie auswählen")
@app_commands.checks.has_permissions(administrator=True)
async def set_verifizierung_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    data["verifizierung_channel"] = channel.id
    data["verifizierung_nachricht_id"] = None
    save_data(data)
    await interaction.response.send_message(f"✅ Verifizierungs-Channel gesetzt: {channel.mention}", ephemeral=True)
    await verifizierung_posten_intern(interaction.guild)

@tree.command(name="verifizierung_posten", description="Postet oder aktualisiert die Familien-Auswahl-Nachricht")
@app_commands.checks.has_permissions(administrator=True)
async def verifizierung_posten(interaction: discord.Interaction):
    if not data.get("verifizierung_channel"):
        await interaction.response.send_message(
            "❌ Kein Verifizierungs-Channel gesetzt!\nBitte zuerst **/set_verifizierung_channel #channel** benutzen.",
            ephemeral=True
        )
        return
    await verifizierung_posten_intern(interaction.guild)
    await interaction.response.send_message("✅ Familien-Auswahl-Nachricht gepostet/aktualisiert.", ephemeral=True)

# ─── BOT EVENTS ───────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"Bot online: {bot.user}")

    # Bestehende Familien-Buttons als persistent registrieren, damit sie nach
    # einem Neustart weiter funktionieren
    if data.get("familien"):
        bot.add_view(build_familien_view())

    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=int(GUILD_ID))
            tree.copy_global_to(guild=guild_obj)
            synced = await tree.sync(guild=guild_obj)
            print(f"✅ {len(synced)} Commands SOFORT auf Guild {GUILD_ID} gesynct: {[c.name for c in synced]}")
        else:
            print("⚠️ Keine GUILD_ID gesetzt — sync läuft global (kann bis zu 1h dauern).")

        synced_global = await tree.sync()
        print(f"✅ {len(synced_global)} Commands global gesynct: {[c.name for c in synced_global]}")
    except Exception as e:
        print(f"❌ FEHLER beim Sync: {e}")

    print("Bot ist bereit!")

@bot.event
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "Du hast keine Berechtigung für diesen Befehl.", ephemeral=True
        )
    else:
        print(f"Command Error: {error}")
        try:
            await interaction.response.send_message("Ein Fehler ist aufgetreten.", ephemeral=True)
        except Exception:
            pass

# ─── START ────────────────────────────────────────────────────────────────────
bot.run(TOKEN)
