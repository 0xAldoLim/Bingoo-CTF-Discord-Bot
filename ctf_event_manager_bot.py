import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import aiosqlite
from datetime import datetime, timezone, timedelta
import logging

# Malaysia Time (UTC+8)
MYT = timezone(timedelta(hours=8))
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
    """Parse a date string in YYYY-MM-DD or YYYY-MM-DD HH:MM format (assumed MYT)."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(date_str.strip(), fmt)
            return naive.replace(tzinfo=MYT)  # treat input as MYT
        except ValueError:
            continue
    raise Exception(f"Invalid date format: `{date_str}`. Use `YYYY-MM-DD` or `YYYY-MM-DD HH:MM`.")

def format_myt(dt: datetime) -> str:
    """Format a datetime as a readable MYT string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MYT)
    myt_dt = dt.astimezone(MYT)
    return myt_dt.strftime("%a, %d %b %Y %I:%M %p MYT")

def calc_duration(start: datetime, end: datetime) -> str:
    """Calculate duration between two datetimes as a human-readable string."""
    delta = end - start
    total_hours = delta.total_seconds() / 3600
    if total_hours >= 24:
        days = int(total_hours // 24)
        hours = int(total_hours % 24)
        return f"{days}d {hours}h" if hours else f"{days}d"
    return f"{total_hours:.0f}h"

async def auto_complete_past_events():
    """Mark any active events whose end_date has passed as 'completed'."""
    now = datetime.now(MYT)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT id, end_date FROM events WHERE status = 'active'"
        )
        rows = await cursor.fetchall()
        for event_id, end_str in rows:
            end_dt = datetime.fromisoformat(end_str)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=MYT)
            if end_dt < now:
                await db.execute(
                    "UPDATE events SET status = 'completed' WHERE id = ?",
                    (event_id,)
                )
        await db.commit()

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
                created_by TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            )
        """)
        # Migration: add status column if upgrading from older schema
        cursor = await db.execute("PRAGMA table_info(events)")
        columns = [row[1] for row in await cursor.fetchall()]
        if "status" not in columns:
            await db.execute("ALTER TABLE events ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
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

@bot.tree.command(name="help", description="Show all available commands", guild=MY_GUILD)
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎯 Bingoo — Command List",
        description="Here's everything I can do:",
        color=0x5865F2
    )

    commands_info = [
        ("📅 /add_event", "Add a new CTF event with name, start/end date, mode, and optional prizes"),
        ("📋 /list_events", "List all active/upcoming CTF events sorted by nearest date"),
        ("✅ /complete_event", "Manually mark an event as completed by its ID"),
        ("🏆 /completed", "View all completed events"),
        ("🗑️ /delete_event", "Delete a single event by ID, or clear all past/completed events"),
        ("🏓 /ping", "Check if the bot is online and see latency"),
        ("👤 /whoami", "Show your user info, roles, and server join date"),
        ("📅 /date", "Show the current date and time"),
        ("🪨 /rps", "Play Rock Paper Scissors against the bot"),
        ("❓ /help", "Show this help message"),
    ]

    for name, desc in commands_info:
        embed.add_field(name=name, value=desc, inline=False)

    embed.set_footer(text="All event times are displayed in MYT (UTC+8)")
    await interaction.response.send_message(embed=embed)

# ------------------------

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

    start_rel = to_discord_timestamp(start_date, "R")
    duration = calc_duration(start_date, end_date)

    await interaction.response.send_message(
        f"✅ Event **{name}** added!\n"
        f"📅 {format_myt(start_date)} → {format_myt(end_date)}\n"
        f"⏳ Starts {start_rel} | Duration: **{duration}**\n"
        f"🎮 Mode: **{mode.name}**"
    )

# ------------------------

@bot.tree.command(name="list_events", description="List all active/upcoming CTF events", guild=MY_GUILD)
async def list_events(interaction: discord.Interaction):
    # Auto-complete any events whose end date has passed
    await auto_complete_past_events()

    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("""
            SELECT id, name, start_date, end_date, mode, prizes
            FROM events WHERE status = 'active' ORDER BY start_date ASC
        """)
        rows = await cursor.fetchall()

    if not rows:
        await interaction.response.send_message("No active events found. Check `/completed` for past events.")
        return

    now = datetime.now(MYT)
    upcoming = []
    ongoing = []

    for row in rows:
        start_dt = datetime.fromisoformat(row[2])
        end_dt = datetime.fromisoformat(row[3])
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=MYT)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=MYT)
        if start_dt <= now <= end_dt:
            ongoing.append(row)
        else:
            upcoming.append(row)

    # Ongoing first, then upcoming (nearest first)
    sorted_rows = ongoing + upcoming

    embed = discord.Embed(title="📅 Active CTF Events", color=0x00ff88)

    for idx, row in enumerate(sorted_rows, start=1):
        event_id, name, start_str, end_str, mode, prizes = row

        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=MYT)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=MYT)

        start_rel = to_discord_timestamp(start_dt, "R")
        duration = calc_duration(start_dt, end_dt)
        mode_display = "Jeopardy" if mode == "jeopardy" else "Attack & Defend"

        if start_dt <= now <= end_dt:
            status_tag = "🔴 LIVE NOW"
        else:
            status_tag = "🟢 Upcoming"

        desc = (
            f"**ID:** `{event_id}` | **Status:** {status_tag}\n"
            f"**Start:** {format_myt(start_dt)} ({start_rel})\n"
            f"**End:** {format_myt(end_dt)}\n"
            f"**Duration:** {duration}\n"
            f"**Mode:** {mode_display}"
        )
        if prizes:
            desc += f"\n**Prizes:** {prizes}"

        embed.add_field(name=f"{idx}. {name}", value=desc, inline=False)

    embed.set_footer(text="All times shown in MYT (UTC+8) • Past events auto-move to /completed")
    await interaction.response.send_message(embed=embed)

# ------------------------

DELETE_CHOICES = [
    app_commands.Choice(name="Single event (by ID)", value="single"),
    app_commands.Choice(name="All completed events", value="all_completed"),
]

@bot.tree.command(name="delete_event", description="Delete events", guild=MY_GUILD)
@app_commands.describe(
    action="What to delete",
    event_id="Event ID to delete (only needed for 'Single event')",
)
@app_commands.choices(action=DELETE_CHOICES)
async def delete_event(
    interaction: discord.Interaction,
    action: app_commands.Choice[str],
    event_id: int = None,
):
    if action.value == "single":
        if event_id is None:
            await interaction.response.send_message(
                "❌ Please provide an `event_id` when deleting a single event.",
                ephemeral=True
            )
            return

        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                "SELECT name FROM events WHERE id = ?", (event_id,)
            )
            row = await cursor.fetchone()

            if not row:
                await interaction.response.send_message(
                    f"❌ No event with ID `{event_id}`",
                    ephemeral=True
                )
                return

            await db.execute("DELETE FROM events WHERE id = ?", (event_id,))
            await db.commit()

        await interaction.response.send_message(f"🗑️ Deleted event **{row[0]}** (ID: `{event_id}`)")

    elif action.value == "all_completed":
        await auto_complete_past_events()

        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM events WHERE status = 'completed'"
            )
            count = (await cursor.fetchone())[0]

            if count == 0:
                await interaction.response.send_message(
                    "No completed events to clear.",
                    ephemeral=True
                )
                return

            await db.execute("DELETE FROM events WHERE status = 'completed'")
            await db.commit()

        await interaction.response.send_message(
            f"🧹 Cleared **{count}** completed event{'s' if count != 1 else ''}!"
        )

# ------------------------

@bot.tree.command(name="complete_event", description="Manually mark an event as completed", guild=MY_GUILD)
@app_commands.describe(event_id="The ID of the event to mark as completed")
async def complete_event(interaction: discord.Interaction, event_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT name, status FROM events WHERE id = ?", (event_id,)
        )
        row = await cursor.fetchone()

        if not row:
            await interaction.response.send_message(
                f"❌ No event with ID `{event_id}`",
                ephemeral=True
            )
            return

        if row[1] == "completed":
            await interaction.response.send_message(
                f"ℹ️ Event **{row[0]}** is already marked as completed.",
                ephemeral=True
            )
            return

        await db.execute(
            "UPDATE events SET status = 'completed' WHERE id = ?", (event_id,)
        )
        await db.commit()

    await interaction.response.send_message(
        f"✅ Event **{row[0]}** (ID: `{event_id}`) marked as completed!"
    )

# ------------------------

@bot.tree.command(name="completed", description="View all completed CTF events", guild=MY_GUILD)
async def completed_events(interaction: discord.Interaction):
    await auto_complete_past_events()

    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("""
            SELECT id, name, start_date, end_date, mode, prizes
            FROM events WHERE status = 'completed' ORDER BY end_date DESC
        """)
        rows = await cursor.fetchall()

    if not rows:
        await interaction.response.send_message("No completed events yet.")
        return

    embed = discord.Embed(title="🏆 Completed CTF Events", color=0xFFD700)

    for idx, row in enumerate(rows, start=1):
        event_id, name, start_str, end_str, mode, prizes = row

        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=MYT)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=MYT)

        duration = calc_duration(start_dt, end_dt)
        mode_display = "Jeopardy" if mode == "jeopardy" else "Attack & Defend"
        end_rel = to_discord_timestamp(end_dt, "R")

        desc = (
            f"**ID:** `{event_id}`\n"
            f"**Ran:** {format_myt(start_dt)} → {format_myt(end_dt)}\n"
            f"**Ended:** {end_rel}\n"
            f"**Duration:** {duration}\n"
            f"**Mode:** {mode_display}"
        )
        if prizes:
            desc += f"\n**Prizes:** {prizes}"

        embed.add_field(name=f"{idx}. {name}", value=desc, inline=False)

    embed.set_footer(text="Use /delete_event → 'All completed events' to clear this list")
    await interaction.response.send_message(embed=embed)

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