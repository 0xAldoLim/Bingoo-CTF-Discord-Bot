import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import aiosqlite
from datetime import datetime, timezone, timedelta
import logging
import random
import os
import io
import csv
import aiohttp
from dotenv import load_dotenv

# ========= CONFIG =========
load_dotenv()
TOKEN = os.getenv("TOKEN")
GUILD_ID = 1477990463289167912           # your server ID
REMINDER_CHANNEL_ID = None               # set to a channel ID to enable reminders, e.g. 1234567890
DATABASE_PATH = "events.db"

# Malaysia Time (UTC+8)
MYT = timezone(timedelta(hours=8))

logging.basicConfig(level=logging.INFO)

# ========= BOT =========
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
MY_GUILD = discord.Object(id=GUILD_ID)

# ========= UTILS =========

def parse_date(date_str: str) -> datetime:
    """Parse YYYY-MM-DD or YYYY-MM-DD HH:MM as MYT."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(date_str.strip(), fmt)
            return naive.replace(tzinfo=MYT)
        except ValueError:
            continue
    raise Exception(f"Invalid date format: `{date_str}`. Use `YYYY-MM-DD` or `YYYY-MM-DD HH:MM`.")

def format_myt(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MYT)
    return dt.astimezone(MYT).strftime("%a, %d %b %Y %I:%M %p MYT")

def calc_duration(start: datetime, end: datetime) -> str:
    total_hours = (end - start).total_seconds() / 3600
    if total_hours >= 24:
        days = int(total_hours // 24)
        hours = int(total_hours % 24)
        return f"{days}d {hours}h" if hours else f"{days}d"
    return f"{total_hours:.0f}h"

def to_discord_timestamp(dt: datetime, style: str = "F") -> str:
    return f"<t:{int(dt.timestamp())}:{style}>"

def ensure_tz(dt: datetime) -> datetime:
    return dt.replace(tzinfo=MYT) if dt.tzinfo is None else dt

async def auto_complete_past_events():
    now = datetime.now(MYT)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("SELECT id, end_date FROM events WHERE status = 'active'")
        rows = await cursor.fetchall()
        for event_id, end_str in rows:
            if ensure_tz(datetime.fromisoformat(end_str)) < now:
                await db.execute("UPDATE events SET status = 'completed' WHERE id = ?", (event_id,))
        await db.commit()

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
                url TEXT,
                created_by TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                reminded_24h INTEGER NOT NULL DEFAULT 0,
                reminded_1h INTEGER NOT NULL DEFAULT 0,
                placement TEXT
            )
        """)
        # Migration for older databases
        cursor = await db.execute("PRAGMA table_info(events)")
        columns = [row[1] for row in await cursor.fetchall()]
        migrations = {
            "status": "ALTER TABLE events ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
            "url": "ALTER TABLE events ADD COLUMN url TEXT",
            "reminded_24h": "ALTER TABLE events ADD COLUMN reminded_24h INTEGER NOT NULL DEFAULT 0",
            "reminded_1h": "ALTER TABLE events ADD COLUMN reminded_1h INTEGER NOT NULL DEFAULT 0",
            "placement": "ALTER TABLE events ADD COLUMN placement TEXT",
        }
        for col, sql in migrations.items():
            if col not in columns:
                await db.execute(sql)
        await db.commit()

# ========= CHOICES =========

MODE_CHOICES = [
    app_commands.Choice(name="Jeopardy", value="jeopardy"),
    app_commands.Choice(name="Attack & Defend", value="attack_and_defend"),
]

RPS_CHOICES = [
    app_commands.Choice(name="🪨 Rock", value="rock"),
    app_commands.Choice(name="📄 Paper", value="paper"),
    app_commands.Choice(name="✂️ Scissors", value="scissors"),
]
RPS_EMOJIS = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
RPS_BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}

DELETE_CHOICES = [
    app_commands.Choice(name="Single event (by ID)", value="single"),
    app_commands.Choice(name="All completed events", value="all_completed"),
]

EXPORT_CHOICES = [
    app_commands.Choice(name="Active events", value="active"),
    app_commands.Choice(name="Completed events", value="completed"),
    app_commands.Choice(name="All events", value="all"),
]

# ========= PAGINATION VIEW =========

class PaginatedEmbed(discord.ui.View):
    def __init__(self, pages: list[discord.Embed], author_id: int):
        super().__init__(timeout=120)
        self.pages = pages
        self.current = 0
        self.author_id = author_id
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current == len(self.pages) - 1
        self.page_label.label = f"{self.current + 1}/{len(self.pages)}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the person who ran this command can use these buttons.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current = max(0, self.current - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.primary, disabled=True)
    async def page_label(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass  # just a label

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current = min(len(self.pages) - 1, self.current + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

def build_event_pages(title: str, color: int, rows: list, footer: str, show_status: bool = False) -> list[discord.Embed]:
    """Build paginated embeds from event rows, 5 events per page."""
    EVENTS_PER_PAGE = 5
    pages = []
    now = datetime.now(MYT)

    for page_start in range(0, len(rows), EVENTS_PER_PAGE):
        page_rows = rows[page_start:page_start + EVENTS_PER_PAGE]
        embed = discord.Embed(title=title, color=color)

        for idx, row in enumerate(page_rows, start=page_start + 1):
            event_id, name, start_str, end_str, mode, prizes, url = row

            start_dt = ensure_tz(datetime.fromisoformat(start_str))
            end_dt = ensure_tz(datetime.fromisoformat(end_str))
            start_rel = to_discord_timestamp(start_dt, "R")
            duration = calc_duration(start_dt, end_dt)
            mode_display = "Jeopardy" if mode == "jeopardy" else "Attack & Defend"

            desc = f"**ID:** `{event_id}`"

            if show_status:
                if start_dt <= now <= end_dt:
                    desc += " | **Status:** 🔴 LIVE NOW"
                elif start_dt > now:
                    hours_until = (start_dt - now).total_seconds() / 3600
                    if hours_until <= 24:
                        desc += " | **Status:** ⚠️ Starting soon!"
                    else:
                        desc += " | **Status:** 🟢 Upcoming"

            desc += (
                f"\n**Start:** {format_myt(start_dt)} ({start_rel})"
                f"\n**End:** {format_myt(end_dt)}"
                f"\n**Duration:** {duration}"
                f"\n**Mode:** {mode_display}"
            )
            if url:
                desc += f"\n**Link:** [CTF Page]({url})"
            if prizes:
                desc += f"\n**Prizes:** {prizes}"

            embed.add_field(name=f"{idx}. {name}", value=desc, inline=False)

        embed.set_footer(text=footer)
        pages.append(embed)

    return pages if pages else [discord.Embed(title=title, description="No events found.", color=color)]


# =============================================
#               SLASH COMMANDS
# =============================================

# ---- /help ----

@bot.tree.command(name="help", description="Show all available commands", guild=MY_GUILD)
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎯 Bingoo — Command List",
        description="Here's everything I can do:",
        color=0x5865F2
    )
    cmds = [
        ("📅 /add_event",        "Add a new CTF event (name, dates, mode, prizes, URL)"),
        ("✏️ /edit_event",        "Edit an existing event's details"),
        ("📋 /list_events",       "List active/upcoming events with pagination"),
        ("⏭️ /upcoming",          "Show the nearest upcoming event"),
        ("✅ /complete_event",    "Manually mark an event as completed"),
        ("🏆 /completed",         "View all completed events with placements"),
        ("🏅 /edit_completed",    "Add or update placement rank on a completed event"),
        ("🗑️ /delete_event",     "Delete a single event or clear all completed"),
        ("📤 /export",            "Export events to a CSV file"),
        ("🌐 /ctftime",           "Pull upcoming CTFs from CTFtime"),
        ("📊 /stats",             "View team CTF statistics"),
        ("🏓 /ping",              "Check bot latency"),
        ("👤 /whoami",            "Show your user info and roles"),
        ("📅 /date",              "Show current date and time"),
        ("🪨 /rps",               "Play Rock Paper Scissors"),
        ("❓ /help",              "Show this message"),
    ]
    for name, desc in cmds:
        embed.add_field(name=name, value=desc, inline=False)
    embed.set_footer(text="All event times are displayed in MYT (UTC+8)")
    await interaction.response.send_message(embed=embed)

# ---- /ping ----

@bot.tree.command(name="ping", description="Check bot latency", guild=MY_GUILD)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! Latency: **{round(bot.latency * 1000)}ms**")

# ---- /whoami ----

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

# ---- /date ----

@bot.tree.command(name="date", description="Show current date and time", guild=MY_GUILD)
async def date_cmd(interaction: discord.Interaction):
    now = datetime.now(MYT)
    ts = int(now.timestamp())
    await interaction.response.send_message(
        f"📅 **Current Time (MYT)**\n"
        f"Full: {format_myt(now)}\n"
        f"Discord: <t:{ts}:F> (<t:{ts}:R>)"
    )

# ---- /rps ----

@bot.tree.command(name="rps", description="Play Rock Paper Scissors!", guild=MY_GUILD)
@app_commands.describe(choice="Pick your weapon!")
@app_commands.choices(choice=RPS_CHOICES)
async def rps(interaction: discord.Interaction, choice: app_commands.Choice[str]):
    await interaction.response.defer()
    player_pick = choice.value
    bot_pick = random.choice(["rock", "paper", "scissors"])

    if player_pick == bot_pick:
        result_text, result_color = "🔄 **It's a tie!** Go again with `/rps`", 0xFFD700
    elif RPS_BEATS[player_pick] == bot_pick:
        result_text, result_color = "🎉 **You win!** GG!", 0x00FF88
    else:
        result_text, result_color = "💀 **You lose!** Better luck next time.", 0xFF4444

    embed = discord.Embed(title="Rock Paper Scissors", color=result_color)
    embed.add_field(name="You", value=f"{RPS_EMOJIS[player_pick]} {player_pick.capitalize()}", inline=True)
    embed.add_field(name="vs", value="⚔️", inline=True)
    embed.add_field(name="Bot", value=f"{RPS_EMOJIS[bot_pick]} {bot_pick.capitalize()}", inline=True)
    embed.add_field(name="Result", value=result_text, inline=False)
    await interaction.followup.send(embed=embed)

# ---- /add_event ----

@bot.tree.command(name="add_event", description="Add a new CTF event", guild=MY_GUILD)
@app_commands.describe(
    name="Name of the CTF event",
    start="Start date — YYYY-MM-DD or YYYY-MM-DD HH:MM",
    end="End date — YYYY-MM-DD or YYYY-MM-DD HH:MM",
    mode="Competition mode",
    url="CTF website link (optional)",
    prizes="Prize details (optional)",
)
@app_commands.choices(mode=MODE_CHOICES)
async def add_event(
    interaction: discord.Interaction,
    name: str,
    start: str,
    end: str,
    mode: app_commands.Choice[str],
    url: str = None,
    prizes: str = None,
):
    try:
        start_date = parse_date(start)
        end_date = parse_date(end)
    except Exception as e:
        await interaction.response.send_message(str(e), ephemeral=True)
        return

    if end_date <= start_date:
        await interaction.response.send_message("❌ End date must be after start date.", ephemeral=True)
        return

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO events (name, start_date, end_date, mode, prizes, url, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, start_date.isoformat(), end_date.isoformat(), mode.value,
              prizes or None, url or None, str(interaction.user)))
        await db.commit()

    start_rel = to_discord_timestamp(start_date, "R")
    duration = calc_duration(start_date, end_date)
    msg = (
        f"✅ Event **{name}** added!\n"
        f"📅 {format_myt(start_date)} → {format_myt(end_date)}\n"
        f"⏳ Starts {start_rel} | Duration: **{duration}**\n"
        f"🎮 Mode: **{mode.name}**"
    )
    if url:
        msg += f"\n🔗 [CTF Page]({url})"
    await interaction.response.send_message(msg)

# ---- /edit_event ----

@bot.tree.command(name="edit_event", description="Edit an existing event's details", guild=MY_GUILD)
@app_commands.describe(
    event_id="ID of the event to edit",
    name="New name (leave empty to keep current)",
    start="New start date — YYYY-MM-DD or YYYY-MM-DD HH:MM",
    end="New end date — YYYY-MM-DD or YYYY-MM-DD HH:MM",
    mode="New competition mode",
    url="New CTF website link",
    prizes="New prize details",
)
@app_commands.choices(mode=MODE_CHOICES)
async def edit_event(
    interaction: discord.Interaction,
    event_id: int,
    name: str = None,
    start: str = None,
    end: str = None,
    mode: app_commands.Choice[str] = None,
    url: str = None,
    prizes: str = None,
):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT name, start_date, end_date, mode, prizes, url FROM events WHERE id = ?",
            (event_id,)
        )
        row = await cursor.fetchone()

        if not row:
            await interaction.response.send_message(f"❌ No event with ID `{event_id}`", ephemeral=True)
            return

        old_name, old_start, old_end, old_mode, old_prizes, old_url = row

        # Apply changes (keep old values if not provided)
        new_name = name if name else old_name
        new_mode = mode.value if mode else old_mode
        new_prizes = prizes if prizes else old_prizes
        new_url = url if url else old_url

        if start:
            try:
                new_start_dt = parse_date(start)
                new_start = new_start_dt.isoformat()
            except Exception as e:
                await interaction.response.send_message(str(e), ephemeral=True)
                return
        else:
            new_start = old_start

        if end:
            try:
                new_end_dt = parse_date(end)
                new_end = new_end_dt.isoformat()
            except Exception as e:
                await interaction.response.send_message(str(e), ephemeral=True)
                return
        else:
            new_end = old_end

        # Validate dates
        s = ensure_tz(datetime.fromisoformat(new_start))
        e = ensure_tz(datetime.fromisoformat(new_end))
        if e <= s:
            await interaction.response.send_message("❌ End date must be after start date.", ephemeral=True)
            return

        await db.execute("""
            UPDATE events SET name=?, start_date=?, end_date=?, mode=?, prizes=?, url=?
            WHERE id=?
        """, (new_name, new_start, new_end, new_mode, new_prizes, new_url, event_id))
        await db.commit()

    # Build summary of what changed
    changes = []
    if name:                changes.append(f"Name → **{new_name}**")
    if start:               changes.append(f"Start → {format_myt(s)}")
    if end:                 changes.append(f"End → {format_myt(e)}")
    if mode:                changes.append(f"Mode → **{mode.name}**")
    if prizes:              changes.append(f"Prizes → {new_prizes}")
    if url:                 changes.append(f"URL → [link]({new_url})")

    if not changes:
        await interaction.response.send_message("ℹ️ No changes provided — event unchanged.", ephemeral=True)
        return

    await interaction.response.send_message(
        f"✏️ Updated event `{event_id}` — **{new_name}**\n" + "\n".join(f"• {c}" for c in changes)
    )

# ---- /list_events ----

@bot.tree.command(name="list_events", description="List all active/upcoming CTF events", guild=MY_GUILD)
async def list_events(interaction: discord.Interaction):
    await auto_complete_past_events()

    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("""
            SELECT id, name, start_date, end_date, mode, prizes, url
            FROM events WHERE status = 'active' ORDER BY start_date ASC
        """)
        rows = await cursor.fetchall()

    if not rows:
        await interaction.response.send_message("No active events found. Check `/completed` for past events.")
        return

    # Sort: ongoing first, then upcoming nearest-first
    now = datetime.now(MYT)
    ongoing = [r for r in rows if ensure_tz(datetime.fromisoformat(r[2])) <= now <= ensure_tz(datetime.fromisoformat(r[3]))]
    upcoming = [r for r in rows if r not in ongoing]
    sorted_rows = ongoing + upcoming

    pages = build_event_pages(
        "📅 Active CTF Events", 0x00FF88, sorted_rows,
        "All times in MYT (UTC+8) • Past events auto-move to /completed",
        show_status=True
    )
    view = PaginatedEmbed(pages, interaction.user.id) if len(pages) > 1 else None
    await interaction.response.send_message(embed=pages[0], view=view)

# ---- /upcoming ----

@bot.tree.command(name="upcoming", description="Show the nearest upcoming event", guild=MY_GUILD)
async def upcoming_event(interaction: discord.Interaction):
    await auto_complete_past_events()
    now = datetime.now(MYT)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("""
            SELECT id, name, start_date, end_date, mode, prizes, url
            FROM events WHERE status = 'active' ORDER BY start_date ASC
        """)
        rows = await cursor.fetchall()

    if not rows:
        await interaction.response.send_message("No upcoming events. Time to find a CTF!")
        return

    # Find first upcoming or ongoing event
    picked = None
    for row in rows:
        start_dt = ensure_tz(datetime.fromisoformat(row[2]))
        end_dt = ensure_tz(datetime.fromisoformat(row[3]))
        if end_dt >= now:
            picked = row
            break

    if not picked:
        await interaction.response.send_message("No upcoming events. Time to find a CTF!")
        return

    event_id, name, start_str, end_str, mode, prizes, url = picked
    start_dt = ensure_tz(datetime.fromisoformat(start_str))
    end_dt = ensure_tz(datetime.fromisoformat(end_str))
    duration = calc_duration(start_dt, end_dt)
    mode_display = "Jeopardy" if mode == "jeopardy" else "Attack & Defend"

    if start_dt <= now <= end_dt:
        status = "🔴 LIVE NOW"
        color = 0xFF4444
    elif (start_dt - now).total_seconds() / 3600 <= 24:
        status = "⚠️ Starting soon!"
        color = 0xFFD700
    else:
        status = "🟢 Upcoming"
        color = 0x00FF88

    embed = discord.Embed(title=f"⏭️ Next Up: {name}", color=color)
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(name="ID", value=f"`{event_id}`", inline=True)
    embed.add_field(name="Mode", value=mode_display, inline=True)
    embed.add_field(name="Start", value=f"{format_myt(start_dt)}\n{to_discord_timestamp(start_dt, 'R')}", inline=True)
    embed.add_field(name="End", value=format_myt(end_dt), inline=True)
    embed.add_field(name="Duration", value=f"**{duration}**", inline=True)
    if url:
        embed.add_field(name="Link", value=f"[CTF Page]({url})", inline=False)
    if prizes:
        embed.add_field(name="Prizes", value=prizes, inline=False)
    embed.set_footer(text="All times in MYT (UTC+8)")
    await interaction.response.send_message(embed=embed)

# ---- /completed ----

@bot.tree.command(name="completed", description="View all completed CTF events", guild=MY_GUILD)
async def completed_events(interaction: discord.Interaction):
    await auto_complete_past_events()

    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("""
            SELECT id, name, start_date, end_date, placement
            FROM events WHERE status = 'completed' ORDER BY end_date DESC
        """)
        rows = await cursor.fetchall()

    if not rows:
        await interaction.response.send_message("No completed events yet.")
        return

    EVENTS_PER_PAGE = 5
    pages = []

    for page_start in range(0, len(rows), EVENTS_PER_PAGE):
        page_rows = rows[page_start:page_start + EVENTS_PER_PAGE]
        embed = discord.Embed(title="🏆 Completed CTF Events", color=0xFFD700)

        for idx, row in enumerate(page_rows, start=page_start + 1):
            event_id, name, start_str, end_str, placement = row

            start_dt = ensure_tz(datetime.fromisoformat(start_str))
            end_dt = ensure_tz(datetime.fromisoformat(end_str))
            end_rel = to_discord_timestamp(end_dt, "R")

            desc = (
                f"**ID:** `{event_id}`\n"
                f"**Ran:** {format_myt(start_dt)} → {format_myt(end_dt)}\n"
                f"**Ended:** {end_rel}"
            )
            if placement:
                desc += f"\n**Placement:** 🏅 {placement}"
            else:
                desc += f"\n**Placement:** _Not set — use `/edit_completed`_"

            embed.add_field(name=f"{idx}. {name}", value=desc, inline=False)

        embed.set_footer(text="Use /edit_completed to add placement • /delete_event to clear")
        pages.append(embed)

    view = PaginatedEmbed(pages, interaction.user.id) if len(pages) > 1 else None
    await interaction.response.send_message(embed=pages[0], view=view)

# ---- /edit_completed ----

@bot.tree.command(name="edit_completed", description="Add or update placement rank on a completed event", guild=MY_GUILD)
@app_commands.describe(
    event_id="ID of the completed event",
    placement="Your team's placement (e.g. '1st', '3rd / 120 teams', 'Top 10')",
)
async def edit_completed(interaction: discord.Interaction, event_id: int, placement: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("SELECT name, status FROM events WHERE id = ?", (event_id,))
        row = await cursor.fetchone()

        if not row:
            await interaction.response.send_message(f"❌ No event with ID `{event_id}`", ephemeral=True)
            return

        if row[1] != "completed":
            await interaction.response.send_message(
                f"❌ Event **{row[0]}** is not completed yet. Use `/complete_event` first.",
                ephemeral=True
            )
            return

        await db.execute("UPDATE events SET placement = ? WHERE id = ?", (placement, event_id))
        await db.commit()

    await interaction.response.send_message(
        f"🏅 Updated placement for **{row[0]}** (ID: `{event_id}`) → **{placement}**"
    )

# ---- /complete_event ----

@bot.tree.command(name="complete_event", description="Manually mark an event as completed", guild=MY_GUILD)
@app_commands.describe(event_id="The ID of the event to mark as completed")
async def complete_event(interaction: discord.Interaction, event_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("SELECT name, status FROM events WHERE id = ?", (event_id,))
        row = await cursor.fetchone()

        if not row:
            await interaction.response.send_message(f"❌ No event with ID `{event_id}`", ephemeral=True)
            return
        if row[1] == "completed":
            await interaction.response.send_message(f"ℹ️ **{row[0]}** is already completed.", ephemeral=True)
            return

        await db.execute("UPDATE events SET status = 'completed' WHERE id = ?", (event_id,))
        await db.commit()

    await interaction.response.send_message(f"✅ Event **{row[0]}** (ID: `{event_id}`) marked as completed!")

# ---- /delete_event ----

@bot.tree.command(name="delete_event", description="Delete events", guild=MY_GUILD)
@app_commands.describe(action="What to delete", event_id="Event ID (for single delete)")
@app_commands.choices(action=DELETE_CHOICES)
async def delete_event(interaction: discord.Interaction, action: app_commands.Choice[str], event_id: int = None):
    if action.value == "single":
        if event_id is None:
            await interaction.response.send_message("❌ Provide an `event_id` for single delete.", ephemeral=True)
            return
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute("SELECT name FROM events WHERE id = ?", (event_id,))
            row = await cursor.fetchone()
            if not row:
                await interaction.response.send_message(f"❌ No event with ID `{event_id}`", ephemeral=True)
                return
            await db.execute("DELETE FROM events WHERE id = ?", (event_id,))
            await db.commit()
        await interaction.response.send_message(f"🗑️ Deleted event **{row[0]}** (ID: `{event_id}`)")

    elif action.value == "all_completed":
        await auto_complete_past_events()
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM events WHERE status = 'completed'")
            count = (await cursor.fetchone())[0]
            if count == 0:
                await interaction.response.send_message("No completed events to clear.", ephemeral=True)
                return
            await db.execute("DELETE FROM events WHERE status = 'completed'")
            await db.commit()
        await interaction.response.send_message(f"🧹 Cleared **{count}** completed event{'s' if count != 1 else ''}!")

# ---- /export ----

@bot.tree.command(name="export", description="Export events to CSV", guild=MY_GUILD)
@app_commands.describe(scope="Which events to export")
@app_commands.choices(scope=EXPORT_CHOICES)
async def export_events(interaction: discord.Interaction, scope: app_commands.Choice[str]):
    await auto_complete_past_events()

    async with aiosqlite.connect(DATABASE_PATH) as db:
        if scope.value == "all":
            cursor = await db.execute("SELECT id, name, start_date, end_date, mode, prizes, url, status, created_by, placement FROM events ORDER BY start_date")
        else:
            cursor = await db.execute(
                "SELECT id, name, start_date, end_date, mode, prizes, url, status, created_by, placement FROM events WHERE status = ? ORDER BY start_date",
                (scope.value,)
            )
        rows = await cursor.fetchall()

    if not rows:
        await interaction.response.send_message(f"No {scope.name.lower()} to export.", ephemeral=True)
        return

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ID", "Name", "Start (MYT)", "End (MYT)", "Duration", "Mode", "Prizes", "URL", "Status", "Created By", "Placement"])
    for row in rows:
        eid, name, start_str, end_str, mode, prizes, url, status, created, placement = row
        s = ensure_tz(datetime.fromisoformat(start_str))
        e = ensure_tz(datetime.fromisoformat(end_str))
        mode_display = "Jeopardy" if mode == "jeopardy" else "Attack & Defend"
        writer.writerow([eid, name, format_myt(s), format_myt(e), calc_duration(s, e), mode_display, prizes or "", url or "", status, created, placement or ""])

    buf.seek(0)
    filename = f"ctf_events_{scope.value}_{datetime.now(MYT).strftime('%Y%m%d')}.csv"
    file = discord.File(fp=io.BytesIO(buf.getvalue().encode("utf-8")), filename=filename)
    await interaction.response.send_message(f"📤 Exported **{len(rows)}** {scope.name.lower()}:", file=file)

# ---- /ctftime ----

@bot.tree.command(name="ctftime", description="Pull upcoming CTFs from CTFtime", guild=MY_GUILD)
@app_commands.describe(limit="Number of events to show (1-10, default 5)")
async def ctftime(interaction: discord.Interaction, limit: int = 5):
    await interaction.response.defer()

    limit = max(1, min(limit, 10))
    now = datetime.now(MYT)
    start_ts = int(now.timestamp())
    end_ts = int((now + timedelta(days=30)).timestamp())

    url = f"https://ctftime.org/api/v1/events/?limit={limit}&start={start_ts}&finish={end_ts}"
    headers = {"User-Agent": "BingooCTFBot/1.0"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    await interaction.followup.send(f"❌ CTFtime API returned status {resp.status}. Try again later.")
                    return
                data = await resp.json()
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to reach CTFtime: {e}")
        return

    if not data:
        await interaction.followup.send("No upcoming CTFs found on CTFtime for the next 30 days.")
        return

    embed = discord.Embed(title="🌐 Upcoming CTFs from CTFtime", color=0xE74C3C)

    for idx, event in enumerate(data[:limit], start=1):
        name = event.get("title", "Unknown")
        ctf_url = event.get("url", "")
        format_name = event.get("format", "")
        start_str = event.get("start", "")
        end_str = event.get("finish", "")
        weight = event.get("weight", 0)

        try:
            s = datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone(MYT)
            e = datetime.fromisoformat(end_str.replace("Z", "+00:00")).astimezone(MYT)
            duration = calc_duration(s, e)
            start_rel = to_discord_timestamp(s, "R")
            time_info = f"**Start:** {format_myt(s)} ({start_rel})\n**End:** {format_myt(e)}\n**Duration:** {duration}"
        except Exception:
            time_info = "**Time:** Unavailable"

        desc = time_info
        if format_name:
            desc += f"\n**Format:** {format_name}"
        if weight:
            desc += f"\n**Weight:** {weight:.2f}"
        if ctf_url:
            desc += f"\n**Link:** [CTFtime Page]({ctf_url})"

        embed.add_field(name=f"{idx}. {name}", value=desc, inline=False)

    embed.set_footer(text="Data from CTFtime.org • Use /add_event to track locally")
    await interaction.followup.send(embed=embed)

# ---- /stats ----

@bot.tree.command(name="stats", description="View team CTF statistics", guild=MY_GUILD)
async def stats(interaction: discord.Interaction):
    await auto_complete_past_events()

    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Total counts
        c = await db.execute("SELECT COUNT(*) FROM events WHERE status = 'active'")
        active_count = (await c.fetchone())[0]
        c = await db.execute("SELECT COUNT(*) FROM events WHERE status = 'completed'")
        completed_count = (await c.fetchone())[0]
        total = active_count + completed_count

        # Mode breakdown (completed only)
        c = await db.execute("SELECT mode, COUNT(*) FROM events WHERE status = 'completed' GROUP BY mode")
        mode_counts = dict(await c.fetchall())

        # Total hours competed
        c = await db.execute("SELECT start_date, end_date FROM events WHERE status = 'completed'")
        rows = await c.fetchall()
        total_hours = 0
        for start_str, end_str in rows:
            s = ensure_tz(datetime.fromisoformat(start_str))
            e = ensure_tz(datetime.fromisoformat(end_str))
            total_hours += (e - s).total_seconds() / 3600

        # Upcoming next event
        c = await db.execute(
            "SELECT name, start_date FROM events WHERE status = 'active' ORDER BY start_date ASC LIMIT 1"
        )
        next_event = await c.fetchone()

        # Most active contributor
        c = await db.execute(
            "SELECT created_by, COUNT(*) as cnt FROM events GROUP BY created_by ORDER BY cnt DESC LIMIT 1"
        )
        top_contributor = await c.fetchone()

    embed = discord.Embed(title="📊 Team CTF Statistics", color=0x9B59B6)

    embed.add_field(name="Total Events", value=f"**{total}**", inline=True)
    embed.add_field(name="Active", value=f"🟢 **{active_count}**", inline=True)
    embed.add_field(name="Completed", value=f"🏆 **{completed_count}**", inline=True)

    # Total time
    if total_hours >= 24:
        days = int(total_hours // 24)
        hours = int(total_hours % 24)
        time_str = f"{days}d {hours}h"
    else:
        time_str = f"{total_hours:.0f}h"
    embed.add_field(name="Total Time Competed", value=f"⏱️ **{time_str}**", inline=True)

    # Mode breakdown
    jeopardy = mode_counts.get("jeopardy", 0)
    ad = mode_counts.get("attack_and_defend", 0)
    embed.add_field(name="Jeopardy", value=f"🧩 **{jeopardy}**", inline=True)
    embed.add_field(name="Attack & Defend", value=f"⚔️ **{ad}**", inline=True)

    # Next event
    if next_event:
        nxt_name, nxt_start = next_event
        nxt_dt = ensure_tz(datetime.fromisoformat(nxt_start))
        embed.add_field(
            name="Next Event",
            value=f"📅 **{nxt_name}** — {to_discord_timestamp(nxt_dt, 'R')}",
            inline=False
        )

    # Top contributor
    if top_contributor:
        embed.add_field(
            name="Most Active Member",
            value=f"👑 **{top_contributor[0]}** ({top_contributor[1]} events added)",
            inline=False
        )

    embed.set_footer(text="Keep grinding! 💪")
    await interaction.response.send_message(embed=embed)

# =============================================
#           REMINDER BACKGROUND TASK
# =============================================

@tasks.loop(minutes=5)
async def reminder_loop():
    """Check for events starting within 24h or 1h and send reminders."""
    if REMINDER_CHANNEL_ID is None:
        return

    channel = bot.get_channel(REMINDER_CHANNEL_ID)
    if channel is None:
        return

    now = datetime.now(MYT)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT id, name, start_date, url, reminded_24h, reminded_1h FROM events WHERE status = 'active'"
        )
        rows = await cursor.fetchall()

        for event_id, name, start_str, url, r24, r1 in rows:
            start_dt = ensure_tz(datetime.fromisoformat(start_str))
            hours_until = (start_dt - now).total_seconds() / 3600

            # 24-hour reminder
            if 0 < hours_until <= 24 and not r24:
                msg = f"⏰ **Reminder:** **{name}** starts {to_discord_timestamp(start_dt, 'R')}! @everyone"
                if url:
                    msg += f"\n🔗 [CTF Page]({url})"
                await channel.send(msg)
                await db.execute("UPDATE events SET reminded_24h = 1 WHERE id = ?", (event_id,))

            # 1-hour reminder
            if 0 < hours_until <= 1 and not r1:
                msg = f"🚨 **Starting soon:** **{name}** begins {to_discord_timestamp(start_dt, 'R')}! Get ready! @everyone"
                if url:
                    msg += f"\n🔗 [CTF Page]({url})"
                await channel.send(msg)
                await db.execute("UPDATE events SET reminded_1h = 1 WHERE id = ?", (event_id,))

        await db.commit()

@reminder_loop.before_loop
async def before_reminder():
    await bot.wait_until_ready()

# =============================================
#                BOT EVENTS
# =============================================

@bot.event
async def on_ready():
    print(f"🔥 Bot ONLINE as {bot.user}")
    for g in bot.guilds:
        print(f"  {g.name} | {g.id}")

    try:
        synced = await bot.tree.sync(guild=MY_GUILD)
        print(f"✅ Synced {len(synced)} commands to guild {GUILD_ID}")
    except Exception as e:
        print("❌ Sync failed:", e)

    if REMINDER_CHANNEL_ID:
        if not reminder_loop.is_running():
            reminder_loop.start()
            print(f"🔔 Reminder loop started (channel: {REMINDER_CHANNEL_ID})")
    else:
        print("⚠️ REMINDER_CHANNEL_ID not set — reminders disabled")

# =============================================
#                   MAIN
# =============================================

async def main():
    print("🚀 Starting bot...")
    try:
        await init_db()
        async with bot:
            await bot.start(TOKEN)
    except Exception as e:
        print("💀 ERROR:", e)

asyncio.run(main())