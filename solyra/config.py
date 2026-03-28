# config.example.py
# ------------------
# Copy this file to config.py and fill in your values.
# This file is safe to commit. config.py should be gitignored.
#
# BOT_TOKEN lives in .env — never put it here.

# ─── Discord IDs ──────────────────────────────────────────────────────────────
# Right-click any Discord element with Developer Mode enabled to copy its ID.

MAIN_GUILD_ID = 1484299189944062065 # Discord ID of your main server
ADMIN_ROLE_ID = 1484300173642301471 # Role ID for the Admin role
ACCOUNTING_ROLE_ID = 1484300358053531769 # Role ID for the Accounting role
TICKET_CATEGORY_ID = 1484299944994013284 # Category ID for deposit ticket channels
WITHDRAWAL_CATEGORY_ID = 1484299972429217862 # Category ID for withdrawal ticket channels
AUDIT_LOG_CHANNEL_ID = 1484299811858415747 # Channel ID for the real-time audit log feed
TRACKER_CHANNEL_ID = 1484299367094423582 # Voice channel ID for the bank total tracker

# ─── Database ─────────────────────────────────────────────────────────────────

DB_PATH = "./solyra.db"          # Path to the SQLite database file

# ─── Backups ──────────────────────────────────────────────────────────────────
# BACKUP_DESTINATION_PATH must exist before the bot starts — it will not be
# auto-created. The bot exits with a clear error if the directory is missing.

BACKUP_INTERVAL_HOURS    = 24    # How often to back up (hours)
BACKUP_RETENTION_COUNT   = 7     # How many backup files to keep
BACKUP_DESTINATION_PATH  = "./backups/"  # Directory to write backups into

# ─── Voice Channel Tracker ────────────────────────────────────────────────────

VC_COOLDOWN_MINUTES = 10         # Minimum minutes between tracker name updates

# ─── Interest Scheduler ───────────────────────────────────────────────────────
# INTEREST_TIME is in UTC (24-hour format HH:MM).
# Convert from your local timezone before setting this value.
# Example: if you want Monday 8pm Eastern (UTC-5), set INTEREST_TIME = "01:00"
#          and INTEREST_DAY = "tuesday" (since 8pm Mon EST = 1am Tue UTC).

INTEREST_DAY    = "sunday"       # Day of week (monday–sunday)
INTEREST_TIME   = "01:00"        # UTC time in HH:MM (24-hour)
INTEREST_PAUSED = False          # Set True to start with scheduler paused

# ─── Display ──────────────────────────────────────────────────────────────────

CURRENCY_SYMBOL = "$"            # Symbol used in all embeds and displays

# ─── Testing ──────────────────────────────────────────────────────────────────
# Set ENABLE_SHUTDOWN = True to enable the /admin shutdown command.
# Disable (False or remove) before going to production.
 
ENABLE_SHUTDOWN = True           # Allow /admin shutdown — testing only