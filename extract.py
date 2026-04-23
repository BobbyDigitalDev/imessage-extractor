#!/usr/bin/env python3
"""
extract.py — iMessage conversation extractor

Extracts messages from a copied Apple iMessage database (chat.db) and writes
them to a plain text or Word document file.

IMPORTANT: Terminal cannot access ~/Library/Messages/chat.db directly due
to macOS privacy restrictions. Use Finder to copy chat.db to your Desktop
or another accessible location first. Pass that copy's path via --db.
Delete the copy when you are done.

Usage examples:
  python extract.py --db ./chat.db --list-chats
  python extract.py --db ./chat.db --contact +14155550123 --output conversation.txt
  python extract.py --db ./chat.db --contact +14155550123 --format docx --output conversation.docx
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from decoder import decode_attributed_body

# Apple's timestamp epoch starts Jan 1 2001 UTC, not Jan 1 1970.
APPLE_EPOCH_UTC = datetime(2001, 1, 1, tzinfo=timezone.utc)

# U+FFFC: Apple uses this as a placeholder for image/video attachments.
OBJECT_REPL = '\ufffc'


def apple_ts_to_datetime(ts):
    """Convert Apple nanosecond timestamp to local time."""
    utc_dt = APPLE_EPOCH_UTC + timedelta(seconds=ts / 1_000_000_000)
    return utc_dt.astimezone()


def connect(db_path):
    """Open a read-only connection to the database."""
    path = Path(db_path).expanduser().resolve()
    if not path.exists():
        print(f"Error: database file not found: {path}", file=sys.stderr)
        sys.exit(1)
    uri = f"file:{path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError as e:
        print(f"Error opening database: {e}", file=sys.stderr)
        sys.exit(1)


def list_chats(conn):
    """Print all chat identifiers found in the database."""
    query = """
        SELECT DISTINCT h.id AS contact, COUNT(m.ROWID) AS message_count
        FROM message m
        JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
        JOIN chat c ON cmj.chat_id = c.ROWID
        JOIN chat_handle_join chj ON c.ROWID = chj.chat_id
        JOIN handle h ON chj.handle_id = h.ROWID
        GROUP BY h.id
        ORDER BY message_count DESC
    """
    rows = conn.execute(query).fetchall()
    if not rows:
        print("No chats found in database.")
        return
    print(f"\n{'Contact':<40} {'Messages':>10}")
    print("-" * 52)
    for row in rows:
        print(f"{row['contact']:<40} {row['message_count']:>10}")
    print()


def fetch_messages(conn, contact):
    """
    Fetch all messages for a given contact identifier.
    Uses parameterized query to prevent SQL injection.
    Excludes tapback reactions (associated_message_type != 0).
    """
    query = """
        SELECT
            m.ROWID,
            m.date,
            m.is_from_me,
            m.text,
            m.attributedBody,
            m.associated_message_type,
            m.item_type
        FROM message m
        JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
        JOIN chat c ON cmj.chat_id = c.ROWID
        JOIN chat_handle_join chj ON c.ROWID = chj.chat_id
        JOIN handle h ON chj.handle_id = h.ROWID
        WHERE h.id = ?
          AND (m.associated_message_type = 0 OR m.associated_message_type IS NULL)
        ORDER BY m.date ASC
    """
    return conn.execute(query, (contact,)).fetchall()


def decode_message(row):
    """
    Extract plain text from a message row.
    Tries text column first, falls back to attributedBody.
    Returns None for image-only or empty messages.
    """
    text = row['text']
    ab = row['attributedBody']

    if text and text.strip():
        t = text.strip()
    elif ab is not None:
        decoded = decode_attributed_body(bytes(ab))
        t = decoded.strip() if decoded else None
    else:
        t = None

    if not t:
        return None

    # Strip image placeholders; skip message if nothing remains.
    clean = t.replace(OBJECT_REPL, '').strip()
    return clean if clean else None


def format_message(dt, is_from_me, text):
    """Format a single message line for text output."""
    sender = "Me" if is_from_me else "Them"
    timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
    return f"[{timestamp}] {sender}: {text}"


def write_txt(messages, output_path):
    """Write extracted messages to a plain text file."""
    with open(output_path, 'w', encoding='utf-8') as f:
        for line in messages:
            f.write(line + '\n')


def write_docx(messages, output_path):
    """Write extracted messages to a Word document."""
    try:
        from docx import Document
        from docx.shared import Pt
    except ImportError:
        print(
            "Error: python-docx is required for --format docx.\n"
            "Install it with: pip install python-docx",
            file=sys.stderr
        )
        sys.exit(1)

    doc = Document()
    style = doc.styles['Normal']
    style.font.name = 'Courier New'
    style.font.size = Pt(10)

    for line in messages:
        doc.add_paragraph(line)

    doc.save(output_path)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Extract iMessage conversations from a copied chat.db file.\n\n"
            "NOTE: Use Finder to copy chat.db from ~/Library/Messages/\n"
            "to an accessible location — Terminal cannot read it directly."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--db',
        required=True,
        metavar='PATH',
        help='Path to your copied chat.db file (required)'
    )
    parser.add_argument(
        '--list-chats',
        action='store_true',
        help='Print all available contacts/chats and exit'
    )
    parser.add_argument(
        '--contact',
        metavar='ID',
        help='Phone number or email to extract (e.g. +14155550123)'
    )
    parser.add_argument(
        '--output',
        metavar='PATH',
        default='./output.txt',
        help='Output file path (default: ./output.txt in current directory)'
    )
    parser.add_argument(
        '--format',
        choices=['txt', 'docx'],
        default='txt',
        help='Output format: txt (default) or docx'
    )

    args = parser.parse_args()

    conn = connect(args.db)

    if args.list_chats:
        list_chats(conn)
        conn.close()
        return

    if not args.contact:
        parser.error("--contact is required unless --list-chats is specified.")

    print(f"Fetching messages for: {args.contact}")
    rows = fetch_messages(conn, args.contact)
    conn.close()

    if not rows:
        print(
            f"No messages found for contact: {args.contact}\n"
            "Tip: run --list-chats to see available contact identifiers."
        )
        sys.exit(0)

    # Decode and format messages, tracking accounting stats.
    formatted = []
    stats = {'written': 0, 'image_only': 0, 'empty': 0, 'special': 0}
    first_dt = None
    last_dt = None

    for row in rows:
        # Skip Digital Touch (item_type=4) and sticker (item_type=5) messages.
        if row['item_type'] in (4, 5):
            stats['special'] += 1
            continue

        text = decode_message(row)
        dt = apple_ts_to_datetime(row['date'])

        if text is None:
            # Distinguish image-only from truly empty.
            raw_text = row['text'] or ''
            ab = row['attributedBody']
            if OBJECT_REPL in raw_text or ab is not None:
                stats['image_only'] += 1
            else:
                stats['empty'] += 1
            continue

        line = format_message(dt, row['is_from_me'], text)
        formatted.append(line)
        stats['written'] += 1

        if first_dt is None:
            first_dt = dt
        last_dt = dt

    if not formatted:
        print("No text messages found for this contact (images or empty only).")
        sys.exit(0)

    # Write output.
    output_path = Path(args.output).expanduser().resolve()
    if args.format == 'docx':
        write_docx(formatted, output_path)
    else:
        write_txt(formatted, output_path)

    # Summary.
    print(f"\nDone.")
    print(f"  Messages written : {stats['written']}")
    print(f"  Image-only       : {stats['image_only']} (skipped, no text)")
    print(f"  Truly empty      : {stats['empty']} (skipped)")
    print(f"  Special (sticker/touch): {stats['special']} (skipped)")
    print(f"  Date range       : {first_dt.strftime('%Y-%m-%d')} to {last_dt.strftime('%Y-%m-%d')}")
    print(f"  Output           : {output_path}")
    print(
        "\nReminder: drag your chat.db copy to the Trash and empty it "
        "when you are done — it contains your entire message history."
    )


if __name__ == '__main__':
    main()
