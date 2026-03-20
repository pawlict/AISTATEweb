"""
Streaming file encryption / decryption for large files (audio, etc.).

File format:
  [16 bytes] Magic: b"AISTATEENC\\x00\\x01" + 2 reserved bytes
  [4 bytes]  Chunk size (uint32 LE) — default 65536
  [1 byte]   Method code: 0=light, 1=standard, 2=maximum
  [3 bytes]  Reserved (zero)
  [N chunks] Each chunk:
      [12 bytes] Nonce (counter-based: file_nonce XOR chunk_index)
      [variable] Ciphertext + 16-byte auth tag
  [4 bytes]  End marker: 0x00000000
"""
from __future__ import annotations

import io
import os
import struct
from pathlib import Path
from typing import Generator, Optional, BinaryIO, Union

from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305

MAGIC = b"AISTATEENC\x00\x01\x00\x00"  # 14 bytes + 2 reserved = 16
HEADER_SIZE = 16 + 4 + 1 + 3  # magic + chunk_size + method + reserved = 24
DEFAULT_CHUNK_SIZE = 65536  # 64 KiB
NONCE_SIZE = 12
TAG_SIZE = 16
END_MARKER = b"\x00\x00\x00\x00"

_METHOD_CODES = {"light": 0, "standard": 1, "maximum": 2}
_CODE_METHODS = {v: k for k, v in _METHOD_CODES.items()}


def _counter_nonce(base_nonce: bytes, chunk_index: int) -> bytes:
    """Generate a deterministic nonce by XOR-ing base nonce with chunk index."""
    idx_bytes = chunk_index.to_bytes(NONCE_SIZE, "big")
    return bytes(a ^ b for a, b in zip(base_nonce, idx_bytes))


def _encrypt_chunk(key: bytes, nonce: bytes, plaintext: bytes, method: str) -> bytes:
    """Encrypt a single chunk. Returns nonce + ciphertext + tag."""
    if method == "maximum":
        # Layer 1: AES-256-GCM
        aesgcm = AESGCM(key)
        inner = aesgcm.encrypt(nonce, plaintext, None)
        # Layer 2: ChaCha20-Poly1305 with different nonce
        chacha_nonce = bytes(b ^ 0xFF for b in nonce)
        chacha = ChaCha20Poly1305(key)
        ct = chacha.encrypt(chacha_nonce, inner, None)
        return nonce + ct
    else:
        aesgcm = AESGCM(key)
        ct = aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ct


def _decrypt_chunk(key: bytes, blob: bytes, method: str) -> bytes:
    """Decrypt a single chunk (nonce + ciphertext + tag)."""
    nonce = blob[:NONCE_SIZE]
    ct = blob[NONCE_SIZE:]
    if method == "maximum":
        chacha_nonce = bytes(b ^ 0xFF for b in nonce)
        chacha = ChaCha20Poly1305(key)
        inner = chacha.decrypt(chacha_nonce, ct, None)
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, inner, None)
    else:
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ct, None)


class EncryptedFileWriter:
    """Context manager for writing encrypted files in chunks."""

    def __init__(
        self,
        key: bytes,
        output: Union[Path, str, BinaryIO],
        method: str = "standard",
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ):
        self._key = key
        self._method = method
        self._chunk_size = chunk_size
        self._base_nonce = os.urandom(NONCE_SIZE)
        self._chunk_index = 0
        self._owns_file = not hasattr(output, "write")
        if self._owns_file:
            self._path = Path(output)
            self._fp: Optional[BinaryIO] = None
        else:
            self._path = None
            self._fp = output

    def __enter__(self):
        if self._owns_file:
            self._fp = open(self._path, "wb")
        self._write_header()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self._fp.write(END_MARKER)
        if self._owns_file and self._fp:
            self._fp.close()
        return False

    def _write_header(self):
        method_code = _METHOD_CODES.get(self._method, 1)
        header = MAGIC + struct.pack("<I", self._chunk_size) + bytes([method_code, 0, 0, 0])
        self._fp.write(header)

    def write_chunk(self, data: bytes) -> None:
        """Encrypt and write a single chunk."""
        nonce = _counter_nonce(self._base_nonce, self._chunk_index)
        encrypted = _encrypt_chunk(self._key, nonce, data, self._method)
        # Write chunk length prefix so reader knows how much to read
        self._fp.write(struct.pack("<I", len(encrypted)))
        self._fp.write(encrypted)
        self._chunk_index += 1

    def write_from_stream(self, source: BinaryIO) -> int:
        """Read from source stream and write encrypted chunks. Returns total bytes."""
        total = 0
        while True:
            chunk = source.read(self._chunk_size)
            if not chunk:
                break
            self.write_chunk(chunk)
            total += len(chunk)
        return total


class EncryptedFileReader:
    """Context manager for reading encrypted files in chunks."""

    def __init__(self, key: bytes, source: Union[Path, str, BinaryIO]):
        self._key = key
        self._owns_file = not hasattr(source, "read")
        if self._owns_file:
            self._path = Path(source)
            self._fp: Optional[BinaryIO] = None
        else:
            self._path = None
            self._fp = source
        self._method: Optional[str] = None
        self._chunk_size: int = 0

    def __enter__(self):
        if self._owns_file:
            self._fp = open(self._path, "rb")
        self._read_header()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._owns_file and self._fp:
            self._fp.close()
        return False

    def _read_header(self):
        header = self._fp.read(HEADER_SIZE)
        if len(header) < HEADER_SIZE:
            raise ValueError("File too short — not an encrypted AISTATE file")
        if header[:14] != MAGIC[:14]:
            raise ValueError("Invalid magic — not an encrypted AISTATE file")
        self._chunk_size = struct.unpack("<I", header[16:20])[0]
        method_code = header[20]
        self._method = _CODE_METHODS.get(method_code, "standard")

    @property
    def method(self) -> str:
        return self._method

    @property
    def chunk_size(self) -> int:
        return self._chunk_size

    def read_chunks(self) -> Generator[bytes, None, None]:
        """Yield decrypted chunks."""
        while True:
            size_bytes = self._fp.read(4)
            if not size_bytes or len(size_bytes) < 4:
                break
            chunk_len = struct.unpack("<I", size_bytes)[0]
            if chunk_len == 0:  # end marker
                break
            blob = self._fp.read(chunk_len)
            if len(blob) < chunk_len:
                raise ValueError("Truncated chunk — file may be corrupted")
            yield _decrypt_chunk(self._key, blob, self._method)

    def read_all(self) -> bytes:
        """Read and decrypt entire file into memory."""
        parts = []
        for chunk in self.read_chunks():
            parts.append(chunk)
        return b"".join(parts)


# ── Convenience functions ──────────────────────────────────────────────
def encrypt_file(
    key: bytes,
    src_path: Union[Path, str],
    dst_path: Union[Path, str],
    method: str = "standard",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> None:
    """Encrypt a file from src_path to dst_path."""
    with open(src_path, "rb") as src:
        with EncryptedFileWriter(key, dst_path, method, chunk_size) as writer:
            writer.write_from_stream(src)


def decrypt_file(
    key: bytes,
    src_path: Union[Path, str],
    dst_path: Union[Path, str],
) -> None:
    """Decrypt a file from src_path to dst_path."""
    with EncryptedFileReader(key, src_path) as reader:
        with open(dst_path, "wb") as dst:
            for chunk in reader.read_chunks():
                dst.write(chunk)
