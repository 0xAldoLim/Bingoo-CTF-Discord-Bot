# 🎯 Bingoo — CTF Event Manager Discord Bot

> A Discord bot built for CTF teams to manage, track, and review Capture The Flag events — all from within your server.

---

## 🚀 Features

- 📅 Add, edit, and delete CTF events with slash commands
- ⏭️ Quickly view the nearest upcoming event
- 🔴 Live status tags (Upcoming / Starting Soon / Live Now)
- 🏆 Auto-complete past events and track placement rankings
- 🌐 Pull upcoming CTFs directly from CTFtime
- 🔔 Automatic reminders at 24h, 1h, 10m, 5m before start, when LIVE, and 1h/30m before end (requires 24/7 hosting)
- 📤 Export events to CSV for record-keeping
- 📊 Team statistics dashboard
- 📄 Paginated embeds for large event lists
- 🕐 All timestamps displayed in MYT (UTC+8)
- 🔗 CTF website URL support on all events
- 👤 User info lookup
- 🗄️ Lightweight SQLite database with auto-migration

---

## 🛠️ Tech Stack

- Python 3.10+
- discord.py
- aiosqlite
- aiohttp
- python-dotenv

---

## 📦 Installation

1. Clone the repository:

```bash
git clone https://github.com/0xAldoLim/Bingoo-CTF-Discord-Bot.git
cd Bingoo-CTF-Discord-Bot
```

2. Create and activate virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate
```

3. Install dependencies:

```bash
pip install discord.py aiosqlite aiohttp python-dotenv
```

---

## ⚙️ Configuration

Create a `.env` file in the root directory:

```
TOKEN=your_discord_bot_token_here
```

> ⚠️ Never expose your token publicly.

**Optional — Event Reminders:**

To enable automatic reminders, set `REMINDER_CHANNEL_ID` in the bot script to the channel ID where you want pings sent. This requires the bot to be running 24/7 (see Hosting below).

---

## ▶️ Running the Bot

```bash
python ctf_event_manager_bot.py
```

---

## 🤖 Commands

### Event Management

| Command | Description |
|---------|-------------|
| `/add_event` | Add a new CTF event (name, dates, mode, prizes, URL) |
| `/edit_event` | Edit an existing event's details |
| `/list_events` | List all active/upcoming events with pagination |
| `/upcoming` | Show the nearest upcoming event in detail |
| `/complete_event` | Manually mark an event as completed |
| `/completed` | View all completed events with placements |
| `/edit_completed` | Add or update placement rank on a completed event |
| `/delete_event` | Delete a single event or clear all completed events |

### Tools & Integrations

| Command | Description |
|---------|-------------|
| `/ctftime` | Pull upcoming CTFs from CTFtime (next 30 days) |
| `/export` | Export active, completed, or all events to CSV |
| `/stats` | View team CTF statistics and leaderboard |

### Utility

| Command | Description |
|---------|-------------|
| `/ping` | Check if bot is online and see latency |
| `/whoami` | Show your user info, roles, and join date |
| `/date` | Show current date and time in MYT |
| `/help` | Show all available commands |

---

## 📁 Project Structure

```
.
├── ctf_event_manager_bot.py
├── events.db
├── .env
├── .gitignore
└── README.md
```

---

## 🔐 Security

- Tokens are stored in `.env`
- `.env` is excluded via `.gitignore`
- Do not commit secrets to GitHub

---

## 🖥️ Hosting (for Reminders)

The event reminder feature requires the bot to run 24/7. Free options include:

- **Oracle Cloud Free Tier** — free forever VM (recommended)
- **Google Cloud Free Tier** — free e2-micro VM
- **Railway.app** — free tier with monthly hours

Without 24/7 hosting, all features work normally except automatic reminder pings. The `/list_events` command still shows ⚠️ warnings for events starting within 24h.

---

## 📌 Future Improvements

- Multi-server support
- Role-based permissions for event management
- Web dashboard interface

---

## 👤 Author

**Aldo Lim Saputra**
Cybersecurity Student @ APU
CTF Player & Developer

---

## ⭐ Support

If you find this useful, consider giving the repository a star!