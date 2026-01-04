"""Quick CLI companion for Bagels expense tracker."""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

# Fix Windows terminal encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Default paths
DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "bagels" / "db.db"
CONFIG_PATH = Path.home() / ".config" / "bagels-quick" / "config.json"

console = Console()


# =============================================================================
# Config Management
# =============================================================================

def get_config() -> dict:
    """Load config from file, or return defaults."""
    defaults = {
        "default_account": None,      # Account name to use by default
        "default_category": None,     # Category name to use by default
        "confirm_undo": True,         # Ask before deleting
        "show_balance_after_add": False,  # Show account balance after adding
    }
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                saved = json.load(f)
                defaults.update(saved)
        except (json.JSONDecodeError, IOError):
            pass
    return defaults


def save_config(config: dict) -> None:
    """Save config to file."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


# =============================================================================
# Database Helpers
# =============================================================================

def get_db_path() -> Path:
    """Get the Bagels database path."""
    if DEFAULT_DB_PATH.exists():
        return DEFAULT_DB_PATH
    win_path = Path.home() / "AppData" / "Local" / "bagels" / "db.db"
    if win_path.exists():
        return win_path
    raise click.ClickException(
        f"Bagels database not found. Checked:\n  {DEFAULT_DB_PATH}\n  {win_path}\n"
        "Run 'bagels locate database' to find your database."
    )


def get_connection() -> sqlite3.Connection:
    """Get a database connection."""
    db_path = get_db_path()
    return sqlite3.connect(str(db_path))


def find_category(conn: sqlite3.Connection, search: str) -> tuple[int, str] | None:
    """Find a category by name (case-insensitive, partial match)."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name FROM category WHERE LOWER(name) = LOWER(?) AND deletedAt IS NULL",
        (search,),
    )
    result = cursor.fetchone()
    if result:
        return result

    cursor.execute(
        "SELECT id, name FROM category WHERE LOWER(name) LIKE LOWER(?) AND deletedAt IS NULL",
        (f"%{search}%",),
    )
    results = cursor.fetchall()
    if len(results) == 1:
        return results[0]
    if len(results) > 1:
        names = ", ".join(r[1] for r in results)
        raise click.ClickException(
            f"Multiple categories match '{search}': {names}\nBe more specific."
        )
    return None


def find_account(conn: sqlite3.Connection, search: str) -> tuple[int, str] | None:
    """Find an account by name (case-insensitive, partial match)."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name FROM account WHERE LOWER(name) = LOWER(?) AND deletedAt IS NULL",
        (search,),
    )
    result = cursor.fetchone()
    if result:
        return result

    cursor.execute(
        "SELECT id, name FROM account WHERE LOWER(name) LIKE LOWER(?) AND deletedAt IS NULL",
        (f"%{search}%",),
    )
    results = cursor.fetchall()
    if len(results) == 1:
        return results[0]
    if len(results) > 1:
        names = ", ".join(r[1] for r in results)
        raise click.ClickException(
            f"Multiple accounts match '{search}': {names}\nBe more specific."
        )
    return None


def get_default_account(conn: sqlite3.Connection) -> tuple[int, str]:
    """Get the default account (from config, or first non-outside account)."""
    config = get_config()
    if config["default_account"]:
        result = find_account(conn, config["default_account"])
        if result:
            return result

    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name FROM account WHERE deletedAt IS NULL AND name != 'Outside source' ORDER BY id LIMIT 1"
    )
    result = cursor.fetchone()
    if result:
        return result
    cursor.execute(
        "SELECT id, name FROM account WHERE deletedAt IS NULL ORDER BY id LIMIT 1"
    )
    result = cursor.fetchone()
    if result:
        return result
    raise click.ClickException("No accounts found. Create one in Bagels first.")


def get_default_category(conn: sqlite3.Connection) -> tuple[int, str] | None:
    """Get the default category from config."""
    config = get_config()
    if config["default_category"]:
        return find_category(conn, config["default_category"])
    return None


# =============================================================================
# CLI Commands
# =============================================================================

@click.group()
@click.version_option()
def cli():
    """Quick CLI companion for Bagels expense tracker.

    Add expenses and income without opening the TUI.
    """
    pass


@cli.command()
@click.argument("amount", type=float)
@click.argument("label")
@click.option("-c", "--cat", "--category", "category", help="Category name (partial match OK)")
@click.option("-a", "--acc", "--account", "account", help="Account name (partial match OK)")
@click.option("-i", "--income", is_flag=True, help="Mark as income instead of expense")
@click.option("-d", "--date", "date_str", help="Date (YYYY-MM-DD), defaults to today")
def add(amount: float, label: str, category: str | None, account: str | None, income: bool, date_str: str | None):
    """Add an expense or income.

    \b
    FIELDS:
      AMOUNT    (required)  Transaction amount, must be > 0
      LABEL     (required)  Description of the transaction

    \b
    OPTIONS:
      -c, --category  (optional)  Category name; uses default if configured
      -a, --account   (optional)  Account name; uses default if not specified
      -d, --date      (optional)  Date as YYYY-MM-DD; defaults to today
      -i, --income    (optional)  Flag to mark as income; default is expense

    \b
    EXAMPLES:
      bq add 50 "Coffee and snacks" -c food
      bq add 1500 "Monthly salary" -c salary --income
      bq add 25.50 "Grab ride" -c taxi -d 2025-01-03
    """
    if amount <= 0:
        raise click.ClickException("Amount must be positive.")

    conn = get_connection()
    try:
        # Resolve account
        if account:
            acc_result = find_account(conn, account)
            if not acc_result:
                raise click.ClickException(f"Account '{account}' not found. Run 'bq accs' to see available accounts.")
            account_id, account_name = acc_result
        else:
            account_id, account_name = get_default_account(conn)

        # Resolve category
        category_id = None
        category_name = None
        if category:
            cat_result = find_category(conn, category)
            if not cat_result:
                raise click.ClickException(f"Category '{category}' not found. Run 'bq cats' to see available categories.")
            category_id, category_name = cat_result
        else:
            # Try default category
            default_cat = get_default_category(conn)
            if default_cat:
                category_id, category_name = default_cat

        # Parse date
        if date_str:
            try:
                record_date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                raise click.ClickException("Invalid date format. Use YYYY-MM-DD.")
        else:
            record_date = datetime.now()

        now = datetime.now()

        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO record (
                createdAt, updatedAt, label, amount, date,
                accountId, categoryId, isInProgress, isIncome, isTransfer
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (now, now, label, amount, record_date, account_id, category_id, False, income, False),
        )
        conn.commit()

        record_type = "[green]Income[/green]" if income else "[red]Expense[/red]"
        cat_display = f" [{category_name}]" if category_name else ""
        console.print(
            f"{record_type}: [bold]{amount:,.2f}[/bold] - {label}{cat_display} "
            f"([dim]{account_name}[/dim])"
        )

    finally:
        conn.close()


@cli.command()
@click.argument("amount", type=float)
@click.argument("label")
@click.option("--from", "-f", "from_account", required=True, help="Source account (required)")
@click.option("--to", "-t", "to_account", required=True, help="Destination account (required)")
@click.option("-d", "--date", "date_str", help="Date (YYYY-MM-DD), defaults to today")
def transfer(amount: float, label: str, from_account: str, to_account: str, date_str: str | None):
    """Transfer money between accounts.

    \b
    FIELDS:
      AMOUNT          (required)  Amount to transfer, must be > 0
      LABEL           (required)  Description of the transfer

    \b
    OPTIONS:
      -f, --from      (required)  Source account name
      -t, --to        (required)  Destination account name
      -d, --date      (optional)  Date as YYYY-MM-DD; defaults to today

    \b
    EXAMPLES:
      bq transfer 500 "Move to savings" --from debit --to savings
      bq transfer 1000 "Credit card payment" -f debit -t credit
    """
    if amount <= 0:
        raise click.ClickException("Amount must be positive.")

    conn = get_connection()
    try:
        # Resolve from account
        from_result = find_account(conn, from_account)
        if not from_result:
            raise click.ClickException(f"Source account '{from_account}' not found. Run 'bq accs' to see available accounts.")
        from_id, from_name = from_result

        # Resolve to account
        to_result = find_account(conn, to_account)
        if not to_result:
            raise click.ClickException(f"Destination account '{to_account}' not found. Run 'bq accs' to see available accounts.")
        to_id, to_name = to_result

        if from_id == to_id:
            raise click.ClickException("Source and destination accounts must be different.")

        # Parse date
        if date_str:
            try:
                record_date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                raise click.ClickException("Invalid date format. Use YYYY-MM-DD.")
        else:
            record_date = datetime.now()

        now = datetime.now()

        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO record (
                createdAt, updatedAt, label, amount, date,
                accountId, categoryId, isInProgress, isIncome, isTransfer, transferToAccountId
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (now, now, label, amount, record_date, from_id, None, False, False, True, to_id),
        )
        conn.commit()

        console.print(
            f"[blue]Transfer[/blue]: [bold]{amount:,.2f}[/bold] - {label} "
            f"([dim]{from_name} -> {to_name}[/dim])"
        )

    finally:
        conn.close()


@cli.command()
@click.option("-n", "--num", default=10, help="Number of records to show (default: 10)")
@click.option("-a", "--all", "show_all", is_flag=True, help="Show all records")
def last(num: int, show_all: bool):
    """Show recent records.

    \b
    EXAMPLES:
      bq last           # Last 10 records
      bq last -n 20     # Last 20 records
      bq last --all     # All records
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        query = """
            SELECT r.date, r.label, r.amount, r.isIncome, r.isTransfer, c.name, a.name, ta.name
            FROM record r
            LEFT JOIN category c ON r.categoryId = c.id
            LEFT JOIN account a ON r.accountId = a.id
            LEFT JOIN account ta ON r.transferToAccountId = ta.id
            ORDER BY r.date DESC, r.createdAt DESC
        """
        if not show_all:
            query += f" LIMIT {num}"

        cursor.execute(query)
        records = cursor.fetchall()

        if not records:
            console.print("[dim]No records found.[/dim]")
            return

        table = Table(title=f"Last {len(records)} Records")
        table.add_column("Date", style="dim")
        table.add_column("Label")
        table.add_column("Amount", justify="right")
        table.add_column("Category", style="dim")
        table.add_column("Account", style="dim")

        for date, label, amount, is_income, is_transfer, cat, acc, transfer_acc in records:
            date_str = date[:10] if date else "-"
            if is_transfer:
                amount_str = f"[blue]{amount:,.2f}[/blue]"
                acc_display = f"{acc} -> {transfer_acc}"
            elif is_income:
                amount_str = f"[green]+{amount:,.2f}[/green]"
                acc_display = acc or "-"
            else:
                amount_str = f"[red]-{amount:,.2f}[/red]"
                acc_display = acc or "-"
            table.add_row(date_str, label, amount_str, cat or "-", acc_display)

        console.print(table)

    finally:
        conn.close()


@cli.command()
@click.option("--flat", is_flag=True, help="Show flat list instead of tree")
def cats(flat: bool):
    """List available categories."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, name, parentCategoryId, nature
            FROM category
            WHERE deletedAt IS NULL
            ORDER BY parentCategoryId NULLS FIRST, name
            """
        )
        categories = cursor.fetchall()

        if flat:
            table = Table(title="Categories")
            table.add_column("Name")
            table.add_column("Type", style="dim")
            for _, name, parent_id, nature in categories:
                prefix = "    " if parent_id else ""
                table.add_row(f"{prefix}{name}", nature)
            console.print(table)
        else:
            parents = {}
            children = {}
            for cat_id, name, parent_id, nature in categories:
                if parent_id is None:
                    parents[cat_id] = (name, nature)
                    children[cat_id] = []
                else:
                    if parent_id not in children:
                        children[parent_id] = []
                    children[parent_id].append((name, nature))

            for parent_id, (parent_name, parent_nature) in parents.items():
                console.print(f"[bold]{parent_name}[/bold] [dim]({parent_nature})[/dim]")
                for child_name, child_nature in children.get(parent_id, []):
                    console.print(f"  - {child_name} [dim]({child_nature})[/dim]")

    finally:
        conn.close()


@cli.command()
def accs():
    """List available accounts."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT name, description, beginningBalance
            FROM account
            WHERE deletedAt IS NULL
            ORDER BY id
            """
        )
        accounts = cursor.fetchall()

        table = Table(title="Accounts")
        table.add_column("Name")
        table.add_column("Description", style="dim")
        table.add_column("Starting Balance", justify="right")

        for name, desc, balance in accounts:
            table.add_row(name, desc or "-", f"{balance:,.2f}")

        console.print(table)

    finally:
        conn.close()


def calculate_account_balance(conn: sqlite3.Connection, account_id: int, beginning_balance: float) -> float:
    """Calculate current balance for an account."""
    cursor = conn.cursor()

    # Income (money in)
    cursor.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM record WHERE accountId = ? AND isIncome = 1 AND isTransfer = 0",
        (account_id,)
    )
    income = cursor.fetchone()[0]

    # Expenses (money out)
    cursor.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM record WHERE accountId = ? AND isIncome = 0 AND isTransfer = 0",
        (account_id,)
    )
    expenses = cursor.fetchone()[0]

    # Transfers out (money leaving this account)
    cursor.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM record WHERE accountId = ? AND isTransfer = 1",
        (account_id,)
    )
    transfers_out = cursor.fetchone()[0]

    # Transfers in (money coming to this account)
    cursor.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM record WHERE transferToAccountId = ?",
        (account_id,)
    )
    transfers_in = cursor.fetchone()[0]

    return beginning_balance + income - expenses - transfers_out + transfers_in


@cli.group(invoke_without_command=True)
@click.pass_context
def balance(ctx):
    """Show and manage account balances.

    \b
    EXAMPLES:
      bq balance                              # Show all account balances
      bq balance set debit 5000               # Set debit account balance to 5000
      bq balance adjust debit 100             # Add 100 to debit balance
      bq balance adjust debit -50             # Subtract 50 from debit balance
    """
    if ctx.invoked_subcommand is None:
        # Default behavior: show balances
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, name, beginningBalance
                FROM account
                WHERE deletedAt IS NULL
                ORDER BY id
                """
            )
            accounts = cursor.fetchall()

            table = Table(title="Account Balances")
            table.add_column("Account")
            table.add_column("Current Balance", justify="right")
            table.add_column("Starting Balance", justify="right", style="dim")

            total = 0.0
            for acc_id, name, beginning in accounts:
                current = calculate_account_balance(conn, acc_id, beginning)
                total += current

                if current >= 0:
                    bal_str = f"[green]{current:,.2f}[/green]"
                else:
                    bal_str = f"[red]{current:,.2f}[/red]"

                table.add_row(name, bal_str, f"{beginning:,.2f}")

            table.add_section()
            if total >= 0:
                total_str = f"[bold green]{total:,.2f}[/bold green]"
            else:
                total_str = f"[bold red]{total:,.2f}[/bold red]"
            table.add_row("[bold]Total[/bold]", total_str, "")

            console.print(table)

        finally:
            conn.close()


@balance.command("set")
@click.argument("account")
@click.argument("amount", type=float)
def balance_set(account: str, amount: float):
    """Set an account's balance to a specific amount.

    This adjusts the starting balance so current balance equals the target.

    \b
    EXAMPLES:
      bq balance set debit 5000       # Set debit balance to exactly 5000
      bq balance set savings 10000    # Set savings balance to 10000
    """
    conn = get_connection()
    try:
        acc_result = find_account(conn, account)
        if not acc_result:
            raise click.ClickException(f"Account '{account}' not found. Run 'bq accs' to see available accounts.")
        acc_id, acc_name = acc_result

        cursor = conn.cursor()
        cursor.execute(
            "SELECT beginningBalance FROM account WHERE id = ?",
            (acc_id,)
        )
        old_beginning = cursor.fetchone()[0]

        # Calculate current balance with old beginning
        current = calculate_account_balance(conn, acc_id, old_beginning)

        # New beginning = target - (current - old_beginning)
        # Which simplifies to: new_beginning = old_beginning + (target - current)
        new_beginning = old_beginning + (amount - current)

        cursor.execute(
            "UPDATE account SET beginningBalance = ?, updatedAt = ? WHERE id = ?",
            (new_beginning, datetime.now(), acc_id)
        )
        conn.commit()

        console.print(f"[bold]{acc_name}[/bold] balance set to [green]{amount:,.2f}[/green]")
        console.print(f"[dim](Starting balance adjusted: {old_beginning:,.2f} -> {new_beginning:,.2f})[/dim]")

    finally:
        conn.close()


@balance.command("adjust")
@click.argument("account")
@click.argument("amount", type=float)
def balance_adjust(account: str, amount: float):
    """Adjust an account's balance by a relative amount.

    Use positive to add, negative to subtract.

    \b
    EXAMPLES:
      bq balance adjust debit 100     # Add 100 to debit balance
      bq balance adjust debit -50     # Subtract 50 from debit balance
    """
    conn = get_connection()
    try:
        acc_result = find_account(conn, account)
        if not acc_result:
            raise click.ClickException(f"Account '{account}' not found. Run 'bq accs' to see available accounts.")
        acc_id, acc_name = acc_result

        cursor = conn.cursor()
        cursor.execute(
            "SELECT beginningBalance FROM account WHERE id = ?",
            (acc_id,)
        )
        old_beginning = cursor.fetchone()[0]
        new_beginning = old_beginning + amount

        cursor.execute(
            "UPDATE account SET beginningBalance = ?, updatedAt = ? WHERE id = ?",
            (new_beginning, datetime.now(), acc_id)
        )
        conn.commit()

        # Calculate new current balance
        new_current = calculate_account_balance(conn, acc_id, new_beginning)

        if amount >= 0:
            adj_str = f"[green]+{amount:,.2f}[/green]"
        else:
            adj_str = f"[red]{amount:,.2f}[/red]"

        console.print(f"[bold]{acc_name}[/bold] adjusted by {adj_str}")
        console.print(f"New balance: [bold]{new_current:,.2f}[/bold]")

    finally:
        conn.close()


@cli.command()
def where():
    """Show where the Bagels database is located."""
    try:
        db_path = get_db_path()
        console.print(f"Database: [bold]{db_path}[/bold]")
        console.print(f"Config:   [bold]{CONFIG_PATH}[/bold]")
    except click.ClickException as e:
        console.print(f"[red]{e.message}[/red]")


@cli.command()
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation")
def undo(yes: bool):
    """Delete the last entry.

    Shows the entry before deleting and asks for confirmation.

    \b
    EXAMPLES:
      bq undo         # Delete last entry (with confirmation)
      bq undo -y      # Delete without asking
    """
    config = get_config()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT r.id, r.label, r.amount, r.date, r.isIncome, r.isTransfer, c.name, a.name, ta.name
            FROM record r
            LEFT JOIN category c ON r.categoryId = c.id
            LEFT JOIN account a ON r.accountId = a.id
            LEFT JOIN account ta ON r.transferToAccountId = ta.id
            ORDER BY r.createdAt DESC
            LIMIT 1
            """
        )
        record = cursor.fetchone()

        if not record:
            console.print("[dim]No records to delete.[/dim]")
            return

        record_id, label, amount, date, is_income, is_transfer, cat, acc, transfer_acc = record
        date_str = date[:10] if date else "-"

        if is_transfer:
            record_type = "[blue]Transfer[/blue]"
            amount_str = f"{amount:,.2f}"
            cat_display = f" ({acc} -> {transfer_acc})"
        elif is_income:
            record_type = "[green]Income[/green]"
            amount_str = f"+{amount:,.2f}"
            cat_display = f" [{cat}]" if cat else ""
        else:
            record_type = "[red]Expense[/red]"
            amount_str = f"-{amount:,.2f}"
            cat_display = f" [{cat}]" if cat else ""

        console.print(f"Last entry: {record_type} {amount_str} - {label}{cat_display} ({date_str})")

        if not yes and config["confirm_undo"]:
            if not click.confirm("Delete this entry?"):
                console.print("[dim]Cancelled.[/dim]")
                return

        cursor.execute("DELETE FROM record WHERE id = ?", (record_id,))
        conn.commit()
        console.print("[green]Deleted.[/green]")

    finally:
        conn.close()


@cli.command()
@click.option("-n", "--num", default=1, help="Which entry to edit (1=last, 2=second last, etc.)")
@click.option("--amount", type=float, help="New amount")
@click.option("--label", "new_label", help="New label/description")
@click.option("-c", "--cat", "--category", "category", help="New category")
@click.option("-a", "--acc", "--account", "account", help="New account")
@click.option("-d", "--date", "date_str", help="New date (YYYY-MM-DD)")
@click.option("--income/--expense", "is_income", default=None, help="Change to income or expense")
def edit(num: int, amount: float | None, new_label: str | None, category: str | None, account: str | None, date_str: str | None, is_income: bool | None):
    """Edit a recent entry.

    By default edits the last entry. Use -n to edit older entries.

    \b
    FIELDS (all optional, specify at least one):
      --amount      New transaction amount (must be > 0)
      --label       New description text
      -c, --cat     New category name (partial match OK)
      -a, --acc     New account name (partial match OK)
      -d, --date    New date as YYYY-MM-DD
      --income      Change to income type
      --expense     Change to expense type

    \b
    TARGETING:
      -n, --num     Which entry to edit (1=last, 2=second-last, etc.)

    \b
    EXAMPLES:
      bq edit --amount 75                    # Fix amount of last entry
      bq edit --label "Correct description"  # Fix label
      bq edit -c groceries                   # Change category
      bq edit -n 2 --amount 100              # Edit second-to-last entry
      bq edit --income                       # Change expense to income
    """
    if all(v is None for v in [amount, new_label, category, account, date_str, is_income]):
        raise click.ClickException("Specify at least one field to edit: --amount, --label, -c, -a, -d, --income/--expense")

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT r.id, r.label, r.amount, r.date, r.isIncome, r.categoryId, c.name, a.name
            FROM record r
            LEFT JOIN category c ON r.categoryId = c.id
            LEFT JOIN account a ON r.accountId = a.id
            ORDER BY r.createdAt DESC
            LIMIT 1 OFFSET ?
            """,
            (num - 1,)
        )
        record = cursor.fetchone()

        if not record:
            console.print(f"[dim]No record found at position {num}.[/dim]")
            return

        record_id, old_label, old_amount, old_date, old_is_income, old_cat_id, old_cat_name, acc_name = record

        updates = []
        params = []

        if amount is not None:
            if amount <= 0:
                raise click.ClickException("Amount must be positive.")
            updates.append("amount = ?")
            params.append(amount)

        if new_label is not None:
            updates.append("label = ?")
            params.append(new_label)

        if category is not None:
            cat_result = find_category(conn, category)
            if not cat_result:
                raise click.ClickException(f"Category '{category}' not found. Run 'bq cats' to see available categories.")
            updates.append("categoryId = ?")
            params.append(cat_result[0])

        if account is not None:
            acc_result = find_account(conn, account)
            if not acc_result:
                raise click.ClickException(f"Account '{account}' not found. Run 'bq accs' to see available accounts.")
            updates.append("accountId = ?")
            params.append(acc_result[0])

        if date_str is not None:
            try:
                new_date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                raise click.ClickException("Invalid date format. Use YYYY-MM-DD.")
            updates.append("date = ?")
            params.append(new_date)

        if is_income is not None:
            updates.append("isIncome = ?")
            params.append(is_income)

        updates.append("updatedAt = ?")
        params.append(datetime.now())

        params.append(record_id)

        cursor.execute(
            f"UPDATE record SET {', '.join(updates)} WHERE id = ?",
            params
        )
        conn.commit()

        old_date_str = old_date[:10] if old_date else "-"
        console.print(f"[dim]Was:[/dim] {old_amount:,.2f} - {old_label} [{old_cat_name or '-'}] ({old_date_str})")

        cursor.execute(
            """
            SELECT r.label, r.amount, r.date, r.isIncome, c.name
            FROM record r
            LEFT JOIN category c ON r.categoryId = c.id
            WHERE r.id = ?
            """,
            (record_id,)
        )
        new_record = cursor.fetchone()
        new_label_val, new_amount, new_date_val, new_is_income, new_cat_name = new_record
        new_date_str = new_date_val[:10] if new_date_val else "-"
        record_type = "[green]Income[/green]" if new_is_income else "[red]Expense[/red]"

        console.print(f"[green]Now:[/green] {record_type} {new_amount:,.2f} - {new_label_val} [{new_cat_name or '-'}] ({new_date_str})")

    finally:
        conn.close()


# =============================================================================
# Config Command Group
# =============================================================================

@cli.group()
def config():
    """Manage bq configuration.

    \b
    AVAILABLE SETTINGS:
      default_account     Account to use when -a is not specified
      default_category    Category to use when -c is not specified
      confirm_undo        Whether to ask before deleting (true/false)

    \b
    EXAMPLES:
      bq config show                           # Show current config
      bq config set default_account debit      # Set default account
      bq config set default_category food      # Set default category
      bq config set confirm_undo false         # Disable undo confirmation
      bq config reset                          # Reset to defaults
    """
    pass


@config.command("show")
def config_show():
    """Show current configuration."""
    cfg = get_config()

    table = Table(title="Configuration")
    table.add_column("Setting")
    table.add_column("Value")
    table.add_column("Description", style="dim")

    table.add_row(
        "default_account",
        str(cfg["default_account"]) if cfg["default_account"] else "[dim]not set[/dim]",
        "Account used when -a not specified"
    )
    table.add_row(
        "default_category",
        str(cfg["default_category"]) if cfg["default_category"] else "[dim]not set[/dim]",
        "Category used when -c not specified"
    )
    table.add_row(
        "confirm_undo",
        "[green]true[/green]" if cfg["confirm_undo"] else "[red]false[/red]",
        "Ask before deleting entries"
    )
    table.add_row(
        "show_balance_after_add",
        "[green]true[/green]" if cfg["show_balance_after_add"] else "[red]false[/red]",
        "Show account balance after adding"
    )

    console.print(table)
    console.print(f"\n[dim]Config file: {CONFIG_PATH}[/dim]")


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str):
    """Set a configuration value.

    \b
    KEYS:
      default_account     Account name (or 'none' to clear)
      default_category    Category name (or 'none' to clear)
      confirm_undo        'true' or 'false'
    """
    cfg = get_config()

    if key == "default_account":
        if value.lower() == "none":
            cfg["default_account"] = None
            console.print("Cleared default_account")
        else:
            conn = get_connection()
            try:
                result = find_account(conn, value)
                if not result:
                    raise click.ClickException(f"Account '{value}' not found. Run 'bq accs' to see available accounts.")
                cfg["default_account"] = result[1]  # Store the actual name
                console.print(f"Set default_account = [bold]{result[1]}[/bold]")
            finally:
                conn.close()

    elif key == "default_category":
        if value.lower() == "none":
            cfg["default_category"] = None
            console.print("Cleared default_category")
        else:
            conn = get_connection()
            try:
                result = find_category(conn, value)
                if not result:
                    raise click.ClickException(f"Category '{value}' not found. Run 'bq cats' to see available categories.")
                cfg["default_category"] = result[1]
                console.print(f"Set default_category = [bold]{result[1]}[/bold]")
            finally:
                conn.close()

    elif key == "confirm_undo":
        if value.lower() in ("true", "1", "yes", "on"):
            cfg["confirm_undo"] = True
            console.print("Set confirm_undo = [green]true[/green]")
        elif value.lower() in ("false", "0", "no", "off"):
            cfg["confirm_undo"] = False
            console.print("Set confirm_undo = [red]false[/red]")
        else:
            raise click.ClickException("Value must be 'true' or 'false'")

    elif key == "show_balance_after_add":
        if value.lower() in ("true", "1", "yes", "on"):
            cfg["show_balance_after_add"] = True
            console.print("Set show_balance_after_add = [green]true[/green]")
        elif value.lower() in ("false", "0", "no", "off"):
            cfg["show_balance_after_add"] = False
            console.print("Set show_balance_after_add = [red]false[/red]")
        else:
            raise click.ClickException("Value must be 'true' or 'false'")

    else:
        valid_keys = ["default_account", "default_category", "confirm_undo", "show_balance_after_add"]
        raise click.ClickException(f"Unknown config key '{key}'. Valid keys: {', '.join(valid_keys)}")

    save_config(cfg)


@config.command("reset")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation")
def config_reset(yes: bool):
    """Reset configuration to defaults."""
    if not yes:
        if not click.confirm("Reset all settings to defaults?"):
            console.print("[dim]Cancelled.[/dim]")
            return

    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()
    console.print("[green]Configuration reset to defaults.[/green]")


if __name__ == "__main__":
    cli()
