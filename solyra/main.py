"""
main.py
-------
Entry point for Sølyra Central Bank bot.
Handles the full startup sequence per the design document:

  1. Load and validate .env / config.py
  2. Init database (schema, WAL, foreign keys)
  3. Start DB worker queue
  4. Crash recovery scan (re-attach ticket views, orphan detection)
  4a. Ensure house account 00000 exists
  4b. Seed general interest config
  4c. Check for missed interest payments
  5. Start backup background task
  6. Sync slash commands with Discord
  7. Connect to gateway (bot online)
"""

from __future__ import annotations
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "solyra.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("solyra")


# ─── Config loading ───────────────────────────────────────────────────────────

def load_config() -> dict:
    """Load and validate all configuration from .env and config.py.
    Exits with a clear error if any required value is missing.
    """
    # Load .env
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        log.critical(".env file not found. Copy .env.example to .env and fill in your values.")
        sys.exit(1)
    load_dotenv(env_path)

    # Required .env values
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        log.critical("BOT_TOKEN is not set in .env.")
        sys.exit(1)

    # Load config.py by path so it works regardless of CWD
    import importlib.util as _ilu
    _config_path = Path(__file__).parent / "config.py"
    if not _config_path.exists():
        log.critical("config.py not found. Copy config.example.py to config.py and fill in your values.")
        sys.exit(1)
    _spec = _ilu.spec_from_file_location("config", _config_path)
    cfg = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(cfg)

    required_int_keys = [
        "MAIN_GUILD_ID",
        "ADMIN_ROLE_ID",
        "ACCOUNTING_ROLE_ID",
        "TICKET_CATEGORY_ID",
        "WITHDRAWAL_CATEGORY_ID",
        "AUDIT_LOG_CHANNEL_ID",
        "TRACKER_CHANNEL_ID",
    ]
    config = {}
    missing = []
    for key in required_int_keys:
        val = getattr(cfg, key, None)
        if val is None:
            missing.append(key)
        else:
            try:
                config[key] = int(val)
            except (ValueError, TypeError):
                log.critical("Config key %s must be an integer, got: %r", key, val)
                sys.exit(1)

    if missing:
        log.critical("Missing required config keys: %s", ", ".join(missing))
        sys.exit(1)

    # Optional keys with defaults
    _base_dir = Path(__file__).parent
    _raw_db = getattr(cfg, "DB_PATH", "./solyra.db")
    config["DB_PATH"] = str(_base_dir / _raw_db) if not Path(_raw_db).is_absolute() else _raw_db
    config["BACKUP_INTERVAL_HOURS"] = int(getattr(cfg, "BACKUP_INTERVAL_HOURS", 24))
    config["BACKUP_RETENTION_COUNT"] = int(getattr(cfg, "BACKUP_RETENTION_COUNT", 7))
    config["BACKUP_DESTINATION_PATH"] = getattr(cfg, "BACKUP_DESTINATION_PATH", "./backups/")
    config["VC_COOLDOWN_MINUTES"] = int(getattr(cfg, "VC_COOLDOWN_MINUTES", 10))
    config["INTEREST_DAY"] = getattr(cfg, "INTEREST_DAY", "monday")
    config["INTEREST_TIME"] = getattr(cfg, "INTEREST_TIME", "00:00")
    config["INTEREST_PAUSED"] = bool(getattr(cfg, "INTEREST_PAUSED", False))
    config["CURRENCY_SYMBOL"] = getattr(cfg, "CURRENCY_SYMBOL", "$")
    config["ENABLE_SHUTDOWN"] = bool(getattr(cfg, "ENABLE_SHUTDOWN", False))
    config["BOT_TOKEN"] = bot_token

    # Validate backup directory — resolve relative paths from main.py's location
    _base_dir = Path(__file__).parent
    backup_path = Path(config["BACKUP_DESTINATION_PATH"])
    if not backup_path.is_absolute():
        backup_path = _base_dir / backup_path
    config["BACKUP_DESTINATION_PATH"] = str(backup_path)
    if not backup_path.exists():
        log.critical(
            "Backup directory at '%s' does not exist. "
            "Please create it or update BACKUP_DESTINATION_PATH in config.py.",
            backup_path,
        )
        sys.exit(1)

    # Validate interest day/time
    from solyra.utils.validators import validate_interest_day, validate_interest_time
    valid, err = validate_interest_day(config["INTEREST_DAY"])
    if not valid:
        log.critical("Invalid INTEREST_DAY in config.py: %s", err)
        sys.exit(1)
    valid, err = validate_interest_time(config["INTEREST_TIME"])
    if not valid:
        log.critical("Invalid INTEREST_TIME in config.py: %s", err)
        sys.exit(1)

    log.info("Configuration loaded successfully.")
    return config


# ─── Bot class ────────────────────────────────────────────────────────────────

class SolyraBankBot(commands.Bot):
    def __init__(self, config: dict) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.config = config
        self.db = None  # Set during setup_hook
        self._start_time = time.monotonic()
        self.vc_tracker = None  # Set after admin cog loads
        self.interest_scheduler = None  # Set during setup_hook

    async def setup_hook(self) -> None:
        """Called before the bot connects to Discord."""
        log.info("=== Sølyra Central Bank starting up ===")

        # ── Step 2: Init database ─────────────────────────────────────────────
        log.info("Step 2: Initialising database...")
        from solyra.db.database import init_db
        self.db = await init_db(self.config["DB_PATH"])

        # ── Step 3: DB worker queue already started by init_db ────────────────
        log.info("Step 3: Database worker queue active.")

        # ── Step 4a: Ensure house account ────────────────────────────────────
        log.info("Step 4a: Verifying house account 00000...")
        from solyra.services.account_service import ensure_house_account
        await ensure_house_account(self.db, self.application_id or 0)

        # ── Step 4a(ii): Seed general interest config ─────────────────────────
        log.info("Step 4a(ii): Seeding general interest config...")
        from solyra.db.queries.interest import seed_general_if_missing
        await seed_general_if_missing(self.db)

        # ── Step 5: Start backup task ─────────────────────────────────────────
        log.info("Step 5: Starting backup task...")
        from solyra.tasks.backup_task import BackupTask
        audit_channel_id = self.config["AUDIT_LOG_CHANNEL_ID"]

        async def _alert(embed):
            ch = self.get_channel(audit_channel_id)
            if ch:
                await ch.send(embed=embed)

        self.backup_task = BackupTask(
            db_path=self.config["DB_PATH"],
            backup_dir=self.config["BACKUP_DESTINATION_PATH"],
            interval_hours=self.config["BACKUP_INTERVAL_HOURS"],
            retention_count=self.config["BACKUP_RETENTION_COUNT"],
            alert_fn=_alert,
        )
        self.backup_task.start()

        # ── Interest scheduler (started after on_ready so channel is available) ─
        log.info("Interest scheduler will start after on_ready.")

    async def on_ready(self) -> None:
        log.info("Bot connected as %s (ID: %s)", self.user, self.user.id)

        # ── Step 6: Load cogs ─────────────────────────────────────────────────
        log.info("Step 6: Loading cogs...")
        cog_modules = [
            "solyra.cogs.deposits",
            "solyra.cogs.withdrawals",
            "solyra.cogs.accounts",
            "solyra.cogs.transfers",
            "solyra.cogs.admin",
        ]
        for module in cog_modules:
            try:
                await self.load_extension(module)
                log.info("  Loaded: %s", module)
            except Exception as exc:
                log.critical("  FAILED to load %s: %s", module, exc, exc_info=True)
                await self.close()
                return

        # ── Step 6b: Sync slash commands ─────────────────────────────────────
        log.info("Step 6b: Syncing slash commands...")
        log.info("  MAIN_GUILD_ID = %s", self.config["MAIN_GUILD_ID"])
        try:
            dev_server = discord.Object(id=self.config["MAIN_GUILD_ID"])
            self.tree.copy_global_to(guild=dev_server)
            synced = await self.tree.sync(guild=dev_server)

            guild = self.get_guild(dev_server.id)
            if guild is None:
                guild = await self.fetch_guild(dev_server.id)

            log.info("  Synced %d commands. Guild: %s | ID: %s", len(synced), guild.name, guild.id)
            for cmd in self.tree.get_commands():
                if hasattr(cmd, "commands"):
                    for sub in cmd.commands:
                        if hasattr(sub, "commands"):
                            for subsub in sub.commands:
                                log.info("    /%s %s %s", cmd.name, sub.name, subsub.name)
                        else:
                            log.info("    /%s %s", cmd.name, sub.name)
                else:
                    log.info("    /%s", cmd.name)
        except Exception as exc:
            log.error("  Command sync failed: %s", exc)

        # ── Step 4: Crash recovery ────────────────────────────────────────────
        log.info("Step 4: Running crash recovery scan...")
        await self._crash_recovery()

        # ── Step 4b: Check missed interest ────────────────────────────────────
        log.info("Step 4b: Checking for missed interest payments...")
        await self._check_missed_interest()

        # ── Start interest scheduler ──────────────────────────────────────────
        log.info("Starting interest scheduler...")
        await self._start_interest_scheduler()

        log.info("=== Sølyra Central Bank is online ===")

    async def _crash_recovery(self) -> None:
        """Re-attach button views to existing ticket channels."""
        from solyra.services.transaction_service import get_pending_tickets, mark_orphaned
        from solyra.utils.formatting import cents_to_display, format_account_id
        from solyra.utils import embeds as E

        pending = await get_pending_tickets(self.db)
        if not pending:
            log.info("  No pending tickets to recover.")
            return

        log.info("  Found %d pending ticket(s) to recover.", len(pending))
        audit_channel = self.get_channel(self.config["AUDIT_LOG_CHANNEL_ID"])

        deposits_cog = self.cogs.get("Deposits")
        withdrawals_cog = self.cogs.get("Withdrawals")

        for tx in pending:
            channel = self.get_channel(int(tx["channel_id"]))
            if channel is None:
                log.warning("  Channel %s not found for tx %s — marking orphaned.", tx["channel_id"], tx["transaction_id"])
                await mark_orphaned(self.db, tx["transaction_id"])
                # Post alert to audit channel
                if audit_channel:
                    alert = E.orphaned_transaction_alert(
                        transaction_id=tx["transaction_id"],
                        account_name=tx.get("account_name", "Unknown"),
                        account_id_display=format_account_id(tx["account_id"]),
                        tx_type=tx["type"],
                        amount_display=cents_to_display(tx["amount"]),
                    )
                    await audit_channel.send(embed=alert)
            else:
                log.info("  Recovering tx %s in channel %s", tx["transaction_id"], channel.id)

        # Delegate view re-attachment to cogs
        if deposits_cog:
            await deposits_cog.reattach_views(pending)
        if withdrawals_cog:
            await withdrawals_cog.reattach_views(pending)

    async def _check_missed_interest(self) -> None:
        """Check for missed scheduled interest runs and post alerts."""
        from solyra.tasks.interest_scheduler import InterestScheduler
        # Temporarily create a scheduler just for the startup check
        audit_channel = self.get_channel(self.config["AUDIT_LOG_CHANNEL_ID"])
        if audit_channel is None:
            log.warning("Audit channel not found — skipping missed interest check.")
            return

        async def _alert(**kwargs):
            await audit_channel.send(**kwargs)

        scheduler = InterestScheduler(
            db=self.db,
            scheduled_day=self.config["INTEREST_DAY"],
            scheduled_time=self.config["INTEREST_TIME"],
            alert_fn=_alert,
            apply_view_fn=self._make_interest_apply_view,
        )
        await scheduler.check_missed_on_startup()

    async def _start_interest_scheduler(self) -> None:
        audit_channel = self.get_channel(self.config["AUDIT_LOG_CHANNEL_ID"])
        if audit_channel is None:
            log.warning("Audit channel not found — interest scheduler not started.")
            return

        async def _alert(**kwargs):
            await audit_channel.send(**kwargs)

        from solyra.tasks.interest_scheduler import InterestScheduler
        self.interest_scheduler = InterestScheduler(
            db=self.db,
            scheduled_day=self.config["INTEREST_DAY"],
            scheduled_time=self.config["INTEREST_TIME"],
            alert_fn=_alert,
            apply_view_fn=self._make_interest_apply_view,
        )
        self.interest_scheduler.start()

    def _make_interest_apply_view(self, account_type: str) -> discord.ui.View:
        """Build an interest Apply/Dismiss view for alert embeds."""
        from solyra.cogs.accounts import InterestConfirmView
        accounts_cog = self.cogs.get("Accounts")
        if accounts_cog:
            return InterestConfirmView(account_type, accounts_cog, self.user)
        return discord.ui.View()

    async def on_application_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Global slash command error handler."""
        log.error("Unhandled command error: %s", error, exc_info=True)
        try:
            from solyra.utils import embeds as E
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=E.error("Unexpected Error", "An unexpected error occurred. Please try again."),
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    embed=E.error("Unexpected Error", "An unexpected error occurred."),
                    ephemeral=True,
                )
        except Exception:
            pass


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    config = load_config()
    bot = SolyraBankBot(config)
    bot.run(config["BOT_TOKEN"], log_handler=None)


if __name__ == "__main__":
    main()