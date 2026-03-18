import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import aiosqlite
from datetime import datetime
import logging
import random
import os
from dotenv import load_dotenv

# ========= CONFIG =========
load_dotenv()
TOKEN = os.getenv("TOKEN")
GUILD_ID = 1477990463289167912  # your server ID (int)
DATABASE_PATH = "events.db"

logging.basicConfig(level=logging.INFO)

# ========= BOT =========
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

MY_GUILD = discord.Object(id=GUILD_ID)

# ========= UTILS =========
def parse_date(date_str: str) -> datetime:
    """Parse a date string in YYYY-MM-DD or YYYY-MM-DD HH:MM format."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    raise Exception(f"Invalid date format: `{date_str}`. Use `YYYY-MM-DD` or `YYYY-MM-DD HH:MM`.")

def to_discord_timestamp(dt: datetime, style: str = "F") -> str:
    """Convert a datetime to a Discord timestamp string.
    Styles: F = full date+time, D = date only, R = relative (e.g. 'in 3 days')
    """
    return f"<t:{int(dt.timestamp())}:{style}>"

# ========= DATABASE =========
async def init_db():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                mode TEXT NOT NULL,
                prizes TEXT,
                created_by TEXT NOT NULL
            )
        """)
        await db.commit()

# ========= MODE CHOICES =========
MODE_CHOICES = [
    app_commands.Choice(name="Jeopardy", value="jeopardy"),
    app_commands.Choice(name="Attack & Defend", value="attack_and_defend"),
]

# ========= RPS CHOICES =========
RPS_CHOICES = [
    app_commands.Choice(name="🪨 Rock", value="rock"),
    app_commands.Choice(name="📄 Paper", value="paper"),
    app_commands.Choice(name="✂️ Scissors", value="scissors"),
]

RPS_EMOJIS = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
RPS_BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}

# ========= SLASH COMMANDS =========

@bot.tree.command(name="ping", description="Test command", guild=MY_GUILD)
async def ping(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong! Latency: **{latency_ms}ms**")

# ------------------------

@bot.tree.command(name="whoami", description="Show info about yourself", guild=MY_GUILD)
async def whoami(interaction: discord.Interaction):
    user = interaction.user
    joined = int(user.joined_at.timestamp()) if hasattr(user, "joined_at") and user.joined_at else None
    created = int(user.created_at.timestamp())

    roles = [r.mention for r in user.roles if r.name != "@everyone"] if hasattr(user, "roles") else []

    embed = discord.Embed(title=f"👤 {user.display_name}", color=user.accent_color or 0x5865F2)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="Username", value=f"`{user.name}`", inline=True)
    embed.add_field(name="User ID", value=f"`{user.id}`", inline=True)
    embed.add_field(name="Account Created", value=f"<t:{created}:D> (<t:{created}:R>)", inline=False)

    if joined:
        embed.add_field(name="Joined Server", value=f"<t:{joined}:D> (<t:{joined}:R>)", inline=False)

    if roles:
        embed.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles), inline=False)

    await interaction.response.send_message(embed=embed)

# ------------------------

@bot.tree.command(name="date", description="Show the current date and time", guild=MY_GUILD)
async def date_cmd(interaction: discord.Interaction):
    now = datetime.now()
    ts = int(now.timestamp())
    await interaction.response.send_message(
        f"📅 **Current Time**\n"
        f"Full: <t:{ts}:F>\n"
        f"Relative: <t:{ts}:R>"
    )

# ------------------------

@bot.tree.command(name="rps", description="Play Rock Paper Scissors!", guild=MY_GUILD)
@app_commands.describe(choice="Pick your weapon!")
@app_commands.choices(choice=RPS_CHOICES)
async def rps(interaction: discord.Interaction, choice: app_commands.Choice[str]):
    await interaction.response.defer()

    player_pick = choice.value
    bot_pick = random.choice(["rock", "paper", "scissors"])

    player_emoji = RPS_EMOJIS[player_pick]
    bot_emoji = RPS_EMOJIS[bot_pick]

    # Determine result
    if player_pick == bot_pick:
        result_text = "🔄 **It's a tie!** Go again with `/rps`"
        result_color = 0xFFD700  # gold
    elif RPS_BEATS[player_pick] == bot_pick:
        result_text = "🎉 **You win!** GG!"
        result_color = 0x00FF88  # green
    else:
        result_text = "💀 **You lose!** Better luck next time."
        result_color = 0xFF4444  # red

    embed = discord.Embed(title="Rock Paper Scissors", color=result_color)
    embed.add_field(name="You", value=f"{player_emoji} {player_pick.capitalize()}", inline=True)
    embed.add_field(name="vs", value="⚔️", inline=True)
    embed.add_field(name="Bot", value=f"{bot_emoji} {bot_pick.capitalize()}", inline=True)
    embed.add_field(name="Result", value=result_text, inline=False)

    await interaction.followup.send(embed=embed)

# ------------------------

@bot.tree.command(name="add_event", description="Add a new CTF event", guild=MY_GUILD)
@app_commands.describe(
    name="Name of the CTF event",
    start="Start date — YYYY-MM-DD or YYYY-MM-DD HH:MM",
    end="End date — YYYY-MM-DD or YYYY-MM-DD HH:MM",
    mode="Competition mode",
    prizes="Prize details (optional)",
)
@app_commands.choices(mode=MODE_CHOICES)
async def add_event(
    interaction: discord.Interaction,
    name: str,
    start: str,
    end: str,
    mode: app_commands.Choice[str],
    prizes: str = None
):
    try:
        start_date = parse_date(start)
        end_date = parse_date(end)
    except Exception as e:
        await interaction.response.send_message(str(e), ephemeral=True)
        return

    if end_date <= start_date:
        await interaction.response.send_message(
            "❌ End date must be after start date.",
            ephemeral=True
        )
        return

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO events (name, start_date, end_date, mode, prizes, created_by)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            name,
            start_date.isoformat(),
            end_date.isoformat(),
            mode.value,
            prizes if prizes else None,
            str(interaction.user)
        ))
        await db.commit()

    start_ts = to_discord_timestamp(start_date, "F")
    end_ts = to_discord_timestamp(end_date, "F")
    start_rel = to_discord_timestamp(start_date, "R")

    await interaction.response.send_message(
        f"✅ Event **{name}** added!\n"
        f"📅 {start_ts} → {end_ts}\n"
        f"⏳ Starts {start_rel}\n"
        f"🎮 Mode: **{mode.name}**"
    )

# ------------------------

@bot.tree.command(name="list_events", description="List all CTF events", guild=MY_GUILD)
async def list_events(interaction: discord.Interaction):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("""
            SELECT id, name, start_date, end_date, mode, prizes
            FROM events ORDER BY start_date
        """)
        rows = await cursor.fetchall()

    if not rows:
        await interaction.response.send_message("No events found.")
        return

    embed = discord.Embed(title="📅 CTF Events", color=0x00ff88)

    for row in rows:
        event_id, name, start_str, end_str, mode, prizes = row

        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)

        start_ts = to_discord_timestamp(start_dt, "F")
        end_ts = to_discord_timestamp(end_dt, "F")
        start_rel = to_discord_timestamp(start_dt, "R")

        mode_display = "Jeopardy" if mode == "jeopardy" else "Attack & Defend"

        desc = (
            f"**Start:** {start_ts} ({start_rel})\n"
            f"**End:** {end_ts}\n"
            f"**Mode:** {mode_display}"
        )
        if prizes:
            desc += f"\n**Prizes:** {prizes}"

        embed.add_field(name=f"{event_id}. {name}", value=desc, inline=False)

    await interaction.response.send_message(embed=embed)

# ------------------------

@bot.tree.command(name="delete_event", description="Delete event by ID", guild=MY_GUILD)
@app_commands.describe(event_id="The ID of the event to delete (shown in /list_events)")
async def delete_event(interaction: discord.Interaction, event_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT name FROM events WHERE id = ?", (event_id,)
        )
        row = await cursor.fetchone()

        if not row:
            await interaction.response.send_message(
                f"❌ No event with ID {event_id}",
                ephemeral=True
            )
            return

        await db.execute("DELETE FROM events WHERE id = ?", (event_id,))
        await db.commit()

    await interaction.response.send_message(
        f"🗑️ Deleted event '{row[0]}'"
    )

# ========= EVENTS =========

@bot.event
async def on_ready():
    print(f"🔥 Bot ONLINE as {bot.user}")

    print("Connected guilds:")
    for g in bot.guilds:
        print(f"  {g.name} | {g.id}")

    try:
        synced = await bot.tree.sync(guild=MY_GUILD)
        print(f"✅ Synced {len(synced)} commands to guild {GUILD_ID}")
    except Exception as e:
        print("❌ Sync failed:", e)

# ========= MAIN =========

async def main():
    print("🚀 Starting bot...")

    try:
        await init_db()
        async with bot:
            await bot.start(TOKEN)
    except Exception as e:
        print("💀 ERROR:", e)

asyncio.run(main())