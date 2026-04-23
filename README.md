# iMessage Extractor

A command-line Python tool that exports iMessage conversations from Apple's SQLite database to plain text or Word documents. It correctly handles Apple's NSAttributedString binary format, including two bugs in naive implementations that silently drop thousands of messages.

---

## Before you run this: copy your database first

macOS's privacy system (TCC) blocks Terminal from reading `~/Library/Messages/chat.db` by default. Running `cp` from the command line will return `Operation not permitted` unless you have explicitly granted Full Disk Access to Terminal in System Settings, which most users haven't done. The easiest path for everyone is Finder.

**Copy the file using Finder:**

1. Open Finder
2. Press `Cmd + Shift + G` and enter `~/Library/Messages/`
3. Find `chat.db` and copy it (`Cmd + C`)
4. Paste it somewhere accessible, like your Desktop (`Cmd + V`)

---

## Why this exists: the hard part

Most iMessage exporters silently lose a significant portion of messages. The reason is Apple's `attributedBody` column — a binary blob in NSKeyedArchiver format that stores rich message content. Two specific bugs cause data loss in naive decoders:

### Bug 1: The end-marker strip (most impactful)

Every `attributedBody` blob ends with the bytes `\x86\x84`. These bytes are both `>= 0x20`, so a naive extraction loop includes them in the output. When Python tries `raw.decode('utf-8')`, it fails because `\x86` is not a valid UTF-8 start byte. The fallback `raw.decode('latin-1')` succeeds but silently corrupts smart quotes, curly apostrophes, and accented characters — mapping them into the C1 control character range.

If any garbage filter is then applied (e.g., "skip if printable ratio < 85%"), those corrupted messages are dropped entirely. In a real extraction of ~32,000 messages, this bug caused silent loss or corruption of thousands of messages.

**The fix:** strip trailing bytes in `{0x84, 0x85, 0x86, 0x87, 0x96, 0x97}` before decoding.

### Bug 2: Multi-byte length encoding (0x81 prefix)

For strings longer than 127 bytes, Apple uses a 3-byte length header: `0x81` followed by 2 bytes of big-endian `uint16`. A naive decoder reads `0x81` as the length value (129), extracts one byte of actual content, then hits a control byte and stops. Every long message — exactly the ones most likely to matter — silently becomes a single character.

**The fix:** check `if length_byte == 0x81: pos += 3` to skip the indicator and both length bytes.

This tool handles both correctly. There is no printable-ratio filter.

---

## Requirements

- Python 3.8+
- `python-docx` (only required for `--format docx`)

---

## Installation

```bash
git clone https://github.com/BobbyDigitalDev/imessage-extractor.git
cd imessage-extractor
pip install python-docx   # optional, for Word output
```

---

## Usage

**Step 1: Find your contact's identifier**
```bash
python extract.py --db ~/Desktop/chat.db --list-chats
```

This prints all contacts with message counts, so you can find the right phone number or email to use.

**Step 2: Extract**
```bash
# Plain text output — saved to your Desktop
python extract.py --db ~/Desktop/chat.db --contact +14155550123 --output ~/Desktop/conversation.txt

# Word document output — saved to your Desktop
python extract.py --db ~/Desktop/chat.db --contact +14155550123 --format docx --output ~/Desktop/conversation.docx
```

**Step 3: Clean up**

Drag `chat.db` from your Desktop to the Trash and empty it. It contains your entire message history in plaintext.

---

## What to do with the output

The plain text format is readable on its own, but it also works well as input to an AI assistant like Claude or ChatGPT. You can paste or upload the exported conversation and ask questions about it, get a summary of a long thread, or analyze patterns across months of messages.

---

## Command-line arguments

| Argument | Description |
|---|---|
| `--db PATH` | Path to your copied chat.db (required) |
| `--contact ID` | Phone number or email to extract (e.g. `+14155550123`) |
| `--output PATH` | Output file path (default: `./output.txt`) |
| `--format` | `txt` or `docx` (default: `txt`) |
| `--list-chats` | Print all contacts and message counts, then exit |

---

## Output format

```
[2023-04-15 09:32:11] Them: Hey, are you coming tonight?
[2023-04-15 09:33:47] Me: Yes, leaving in about an hour
[2023-04-15 09:34:02] Them: Perfect, I'll save you a seat
```

At the end of each run, the tool prints a summary:

```
Done.
  Messages written : 4,823
  Image-only       : 312 (skipped, no text)
  Truly empty      : 7 (skipped)
  Special (sticker/touch): 14 (skipped)
  Date range       : 2019-03-01 to 2024-11-20
  Output           : /Users/you/conversation.txt
```

The summary lets you sanity-check completeness. If written + image_only + empty + special does not equal the total rows for that contact in the database, there is a bug.

---

## How it works

The iMessage database stores message text in two columns of the `message` table:

- `text` — plain UTF-8. Present for most older and simple messages.
- `attributedBody` — binary NSAttributedString blob. Used for rich messages and increasingly on newer iOS/macOS. When populated, `text` is usually NULL.

The extractor checks `text` first. If it is NULL or empty, it calls `decode_attributed_body()` from `decoder.py`. The decoder locates the `\x84\x01\x2b` marker that identifies the NSString payload, handles variable-length encoding, strips the trailing format markers, and decodes as UTF-8 with a trim-and-retry fallback for incomplete sequences.

Tapback reactions (heart, thumbs up, etc.) are excluded via `associated_message_type = 0`. Digital Touch and sticker messages (which have no text content) are excluded via `item_type`. Image-only messages (U+FFFC placeholder) are counted but skipped.

Timestamps are stored as nanoseconds since Apple's epoch (January 1, 2001 UTC), not the Unix epoch (January 1, 1970). Using the Unix epoch directly produces dates 31 years in the future. The extractor converts timestamps to your local timezone using Python's `datetime.astimezone()`.

---

## Privacy

This tool reads a local copy of your database. Nothing leaves your machine. The copy of `chat.db` you create contains your complete message history — drag it to the Trash and empty it when you are finished.

---

## License

MIT License. See [LICENSE](LICENSE).
