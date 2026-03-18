import discord
from discord.ext import commands
import asyncio
import aiosqlite
from datetime import datetime
import logging

# ========= CONFIG =========
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TOKEN")
GUILD_ID = 1477990463289167912  # your server ID (int)
DATABASE_PATH = "events.db"

logging.basicConfig(level=logging.INFO)

# ========= BOT =========
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Create a guild object for registering commands to a specific server
MY_GUILD = discord.Object(id=GUILD_ID)

# ========= UTILS =========
def parse_date(date_str: str) -> datetime:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise Exception(f"Invalid date format: {date_str}. Use YYYY-MM-DD.")

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

# ========= SLASH COMMANDS =========

@bot.tree.command(name="ping", description="Test command", guild=MY_GUILD)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong")

# ------------------------

@bot.tree.command(name="add_event", description="Add a new CTF event", guild=MY_GUILD)
async def add_event(
    interaction: discord.Interaction,
    name: str,
    start: str,
    end: str,
    mode: str,
    prizes: str = None
):
    valid_modes = {"jeopardy", "a&d", "attack & defend", "attack_and_defend"}

    if mode.lower() not in valid_modes:
        await interaction.response.send_message(
            "❌ Invalid mode. Use 'jeopardy' or 'a&d'.",
            ephemeral=True
        )
        return

    try:
        start_date = parse_date(start)
        end_date = parse_date(end)
    except Exception as e:
        await interaction.response.send_message(str(e), ephemeral=True)
        return

    if end_date < start_date:
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
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            mode.lower(),
            prizes if prizes else None,
            str(interaction.user)
        ))
        await db.commit()

    await interaction.response.send_message(f"✅ Event '{name}' added!")

# ------------------------

@bot.tree.command(name="list_events", description="List all events", guild=MY_GUILD)
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
        event_id, name, start, end, mode, prizes = row
        mode_display = "Jeopardy" if mode.startswith("jeop") else "Attack & Defend"

        desc = f"Start: {start}\nEnd: {end}\nMode: {mode_display}"
        if prizes:
            desc += f"\nPrizes: {prizes}"

        embed.add_field(name=f"{event_id}. {name}", value=desc, inline=False)

    await interaction.response.send_message(embed=embed)

# ------------------------

@bot.tree.command(name="delete_event", description="Delete event by ID", guild=MY_GUILD)
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

    # Sync guild-scoped commands — they appear instantly (no 1-hour delay)
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