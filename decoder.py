"""
decoder.py — iMessage attributedBody decoder

Apple's iMessage database (chat.db) stores message text in two places:

  - text column: plain UTF-8. Present for most older and simple messages.
  - attributedBody column: binary blob in Apple's NSKeyedArchiver /
    NSAttributedString "streamtyped" format. Used for rich messages (links,
    mentions, formatting) and increasingly on newer iOS/macOS versions.

Always check `text` first. Only call decode_attributed_body() if `text` is
NULL or empty.

Two bugs silently destroy data in naive decoders — both are handled here:

  1. End-marker strip: Apple appends \\x86\\x84 to every attributedBody blob.
     These bytes pass the extraction loop (both >= 0x20) but break UTF-8
     decoding, triggering a latin-1 fallback that corrupts smart quotes and
     accented characters. Fix: strip trailing marker bytes before decoding.

  2. Multi-byte length encoding: For strings > 127 bytes, Apple uses a 3-byte
     length header (0x81 + 2-byte big-endian uint16). A naive decoder reads
     0x81 as length=129, extracts one byte of content, and stops. Every long
     message becomes a single character and gets silently dropped. Fix: check
     for 0x81 prefix and skip all 3 bytes.

Do not add a printable-ratio filter. It causes false negatives on emoji and
messages that went through the latin-1 fallback path before the fix is applied.
"""


def decode_attributed_body(blob):
    """
    Decode an iMessage attributedBody binary blob to plain text.

    Returns the decoded string, or None if decoding fails or content is empty.

    Parameters
    ----------
    blob : bytes or memoryview
        The raw attributedBody value from the iMessage SQLite database.

    Returns
    -------
    str or None
        Decoded plain text, or None if the blob contains no recoverable text.
    """
    if not blob:
        return None
    try:
        # The marker b'\\x84\\x01\\x2b' identifies the start of the NSString
        # content within the binary NSKeyedArchiver archive.
        marker = b'\x84\x01\x2b'
        idx = blob.find(marker)
        if idx == -1:
            return None

        pos = idx + 3  # skip past the 3-byte marker

        # Read the length encoding. Apple uses variable-length encoding:
        #   - Single byte (0x00-0x80): that byte IS the length
        #   - 0x81: next 2 bytes are a big-endian uint16 length (skip all 3)
        #   - 0x82+: next 4 bytes are length (rare); skip indicator + 4 bytes
        length_byte = blob[pos]
        if length_byte == 0x81:
            pos += 3    # skip 0x81 + 2 length bytes
        elif length_byte >= 0x82:
            pos += 5    # skip indicator + 4 length bytes
        else:
            pos += 1    # skip single length byte

        if pos >= len(blob):
            return None

        # Extract text bytes. Stop at control characters (< 0x20) except
        # tab (0x09), newline (0x0a), and carriage return (0x0d).
        text_bytes = []
        while pos < len(blob) and len(text_bytes) < 4000:
            b = blob[pos]
            if b < 0x20 and b not in (0x09, 0x0a, 0x0d):
                break
            text_bytes.append(b)
            pos += 1

        if not text_bytes:
            return None

        raw = bytes(text_bytes)

        # CRITICAL: Strip Apple's end-marker bytes before decoding.
        # Apple appends \x86\x84 (and occasionally \x85\x87\x96\x97) to the
        # text content as NSAttributedString format markers. Because these bytes
        # are >= 0x20 they pass the extraction loop above. If left in, they
        # cause UTF-8 decode to fail, triggering latin-1 fallback, which
        # produces corrupted smart quotes and other Unicode mangling.
        while raw and raw[-1] in (0x84, 0x85, 0x86, 0x87, 0x96, 0x97):
            raw = raw[:-1]

        if not raw:
            return None

        # Decode as UTF-8. If the trailing strip left an incomplete multi-byte
        # sequence, trim one byte at a time and retry (up to 4 times).
        try:
            return raw.decode('utf-8').strip()
        except UnicodeDecodeError:
            for trim in range(1, 5):
                try:
                    return raw[:-trim].decode('utf-8').strip()
                except UnicodeDecodeError:
                    pass
            return None

    except Exception:
        return None
