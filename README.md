# 🎯 Bingoo — CTF Event Manager Discord Bot

> A Discord bot designed to manage and track upcoming Capture The Flag (CTF) events efficiently within your server.

---

## 🚀 Features

- ➕ Add new CTF events via slash commands
- 📅 List all upcoming events with Discord timestamps (auto timezone)
- ❌ Delete events by ID
- 🎮 Mode selection dropdown (Jeopardy / Attack & Defend)
- 🪨 Rock Paper Scissors mini-game
- 👤 User info lookup
- ⚡ Instant slash command support (guild-based sync)
- 🗄️ Lightweight SQLite database

---

## 🛠️ Tech Stack

- Python 3.10+
- discord.py
- aiosqlite
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
pip install discord.py aiosqlite python-dotenv
```

---

## ⚙️ Configuration

Create a `.env` file in the root directory:

```
TOKEN=your_discord_bot_token_here
```

> ⚠️ Never expose your token publicly.

---

## ▶️ Running the Bot

```bash
python ctf_event_manager_bot.py
```

---

## 🤖 Commands

| Command | Description |
|---------|-------------|
| `/ping` | Check if bot is online (shows latency) |
| `/add_event` | Add a new CTF event with date, mode, and prizes |
| `/list_events` | List all stored events with timestamps |
| `/delete_event` | Delete an event by ID |
| `/whoami` | Show your user info, roles, and join date |
| `/date` | Show the current date and time |
| `/rps` | Play Rock Paper Scissors against the bot |

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

## 📌 Future Improvements

- Event reminders & notifications
- Multi-server support
- Role-based permissions
- Web dashboard interface

---

## 👤 Author

**Aldo Lim Saputra**
Cybersecurity Student @ APU
CTF Player & Developer

---

## ⭐ Support

If you find this useful, consider giving the repository a star!