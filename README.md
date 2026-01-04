# bagels-quick (bq)

Quick CLI companion for [Bagels](https://github.com/EnhancedJax/Bagels) expense tracker. Add expenses and income without opening the TUI.

## Installation

```bash
cd C:\Users\VICTUS\projects\bagels-quick
uv build
uv tool install dist/*.whl
```

To update after making changes:
```bash
uv build && uv tool install --force dist/*.whl
```

## Commands

### Add Expense/Income

```bash
bq add <amount> <label> [options]

# Examples
bq add 50 "Coffee and snacks" -c food
bq add 1500 "Monthly salary" -c salary --income
bq add 25.50 "Grab ride" -c taxi -d 2025-01-03
```

| Option | Description |
|--------|-------------|
| `-c, --category` | Category name (partial match OK) |
| `-a, --account` | Account name (partial match OK) |
| `-i, --income` | Mark as income instead of expense |
| `-d, --date` | Date as YYYY-MM-DD (default: today) |

### Transfer Between Accounts

```bash
bq transfer <amount> <label> --from <account> --to <account>

# Examples
bq transfer 500 "Move to savings" --from debit --to savings
bq transfer 1000 "Credit card payment" -f debit -t credit
```

### View Recent Records

```bash
bq last           # Last 10 records
bq last -n 20     # Last 20 records
bq last --all     # All records
```

### Edit Entry

```bash
bq edit [options]

# Examples
bq edit --amount 75                    # Fix amount of last entry
bq edit --label "Correct description"  # Fix label
bq edit -c groceries                   # Change category
bq edit -n 2 --amount 100              # Edit second-to-last entry
bq edit --income                       # Change expense to income
```

| Option | Description |
|--------|-------------|
| `-n, --num` | Which entry to edit (1=last, 2=second-last, etc.) |
| `--amount` | New amount |
| `--label` | New description |
| `-c, --category` | New category |
| `-a, --account` | New account |
| `-d, --date` | New date (YYYY-MM-DD) |
| `--income/--expense` | Change transaction type |

### Delete Last Entry

```bash
bq undo           # With confirmation
bq undo -y        # Skip confirmation
```

### Account Balances

```bash
bq balance                        # Show all account balances with totals

# Set balance to exact amount
bq balance set debit 5000         # Set debit balance to exactly 5000

# Adjust balance by relative amount
bq balance adjust debit 100       # Add 100 to debit balance
bq balance adjust debit -- -50    # Subtract 50 (use -- before negative numbers)
```

### Configuration

```bash
bq config show                           # View current settings
bq config set default_account debit      # Set default account
bq config set default_category food      # Set default category
bq config set confirm_undo false         # Disable delete confirmation
bq config reset                          # Reset to defaults
```

| Setting | Description |
|---------|-------------|
| `default_account` | Account used when `-a` not specified |
| `default_category` | Category used when `-c` not specified |
| `confirm_undo` | Ask before deleting (true/false) |

### Reference Commands

```bash
bq balance        # Show current account balances
bq cats           # List categories (tree view)
bq cats --flat    # List categories (flat table)
bq accs           # List accounts (with starting balances)
bq where          # Show database and config paths
```

## File Locations

| File | Path |
|------|------|
| Bagels Database | `C:\Users\VICTUS\.local\share\bagels\db.db` |
| bq Config | `C:\Users\VICTUS\.config\bagels-quick\config.json` |

## How It Works

This CLI writes directly to the same SQLite database that Bagels uses. Records you add with `bq` will appear in the Bagels TUI, and vice versa.

## Dependencies

- Python 3.13+
- click
- rich
