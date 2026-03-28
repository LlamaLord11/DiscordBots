# Sølyra Central Bank

A Discord economy/banking bot for a Minecraft server. Built with Discord.py and aiosqlite.

## Setup

### 1. Install dependencies
```
pip install -r requirements.txt
```

### 2. Configure
```
cp config.example.py config.py    # fill in your Discord IDs and settings
cp .env.example .env              # add your BOT_TOKEN
```

### 3. Create the backups directory
The bot will not start if this directory does not exist.
```
mkdir backups
```

### 4. Run
```
python -m solyra.main
```

---

## Project structure

```
solyra/
├── main.py                    Entry point, startup sequence, crash recovery
├── config.example.py          Template — copy to config.py
├── .env.example               Template — copy to .env (never commit .env)
├── requirements.txt
├── backups/                   Database backup files (auto-managed by bot)
│
├── utils/                     Stateless helpers — no Discord or DB imports
│   ├── formatting.py          Currency display, amount parsing, date formatting
│   ├── validators.py          File type, amount, name, schedule validation
│   ├── permissions.py         Role checks, account ownership checks
│   └── embeds.py              All branded embed builders
│
├── db/                        Raw SQL only — no business logic
│   ├── database.py            Connection, WAL setup, worker queue, schema
│   └── queries/
│       ├── accounts.py        SQL for accounts + account_users tables
│       ├── transactions.py    SQL for transactions table
│       ├── interest.py        SQL for interest_config table
│       └── audit.py           SQL for audit_log table
│
├── services/                  Business logic — Discord-agnostic, reusable
│   ├── account_service.py     Create, close, freeze, user management
│   ├── transaction_service.py Deposits, withdrawals, transfers, history
│   ├── interest_service.py    Rate config, application logic, remainder handling
│   └── audit_service.py       Audit log writes and paginated retrieval
│
├── tasks/                     Background async loops
│   ├── backup_task.py         Periodic DB backup with retention rotation
│   └── interest_scheduler.py  Weekly interest scheduler with missed-run detection
│
└── cogs/                      Discord layer — commands and button views
    ├── deposits.py            /deposit command + Approve/Deny/Close ticket buttons
    ├── withdrawals.py         /withdraw command + Completed/Deny ticket buttons
    ├── accounts.py            /account subcommands + interest management
    ├── transfers.py           /transfer, /bal, /balHistory
    └── admin.py               /admin subcommands + VC tracker
```

## Layer rules

- `cogs/` imports from `services/` and `utils/` only
- `services/` imports from `db/` and `utils/` only
- `db/` imports nothing internal
- `tasks/` imports from `services/` and `utils/` only

Violations of this hierarchy are structural bugs.

## Runtime files

These are created automatically and should not be committed:
- `solyra.db` — SQLite database (created on first run)
- `solyra.log` — log file (created on first run)
- `backups/solyra_backup_*.db` — rolling backups (managed by backup task)