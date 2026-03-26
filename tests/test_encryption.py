"""Unit tests for the backend.encryption module."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from backend.encryption.primitives import (
    derive_key,
    encrypt_block,
    decrypt_block,
    wrap_key,
    unwrap_key,
    generate_key,
    generate_salt,
    has_argon2,
    constant_time_compare,
)
from backend.encryption.stream import (
    encrypt_file,
    decrypt_file,
    EncryptedFileWriter,
    EncryptedFileReader,
)
from backend.encryption.keys import MasterKeyManager, ProjectKeyManager
from backend.encryption.recovery import RecoveryTokenManager


# ── Primitives ─────────────────────────────────────────────────────────

class TestKeyDerivation:
    def test_derive_key_light(self):
        salt = generate_salt()
        key = derive_key("password123", salt, "light")
        assert len(key) == 16  # AES-128

    def test_derive_key_standard(self):
        salt = generate_salt()
        key = derive_key("password123", salt, "standard")
        assert len(key) == 32  # AES-256

    def test_derive_key_maximum(self):
        salt = generate_salt()
        key = derive_key("password123", salt, "maximum")
        assert len(key) == 32

    def test_derive_key_deterministic(self):
        salt = generate_salt()
        k1 = derive_key("test", salt, "light")
        k2 = derive_key("test", salt, "light")
        assert k1 == k2

    def test_different_passwords_different_keys(self):
        salt = generate_salt()
        k1 = derive_key("password1", salt, "standard")
        k2 = derive_key("password2", salt, "standard")
        assert k1 != k2

    def test_different_salts_different_keys(self):
        s1 = generate_salt()
        s2 = generate_salt()
        k1 = derive_key("same", s1, "standard")
        k2 = derive_key("same", s2, "standard")
        assert k1 != k2


class TestEncryptDecrypt:
    def test_round_trip_light(self):
        key = generate_key(16)
        plaintext = b"Hello, World!"
        ct = encrypt_block(key, plaintext, method="light")
        result = decrypt_block(key, ct, method="light")
        assert result == plaintext

    def test_round_trip_standard(self):
        key = generate_key(32)
        plaintext = b"Test data for AES-256-GCM"
        ct = encrypt_block(key, plaintext, method="standard")
        result = decrypt_block(key, ct, method="standard")
        assert result == plaintext

    def test_round_trip_maximum(self):
        key = generate_key(32)
        plaintext = b"Double-layer encryption test"
        ct = encrypt_block(key, plaintext, method="maximum")
        result = decrypt_block(key, ct, method="maximum")
        assert result == plaintext

    def test_ciphertext_differs_from_plaintext(self):
        key = generate_key(32)
        plaintext = b"Secret message"
        ct = encrypt_block(key, plaintext)
        assert plaintext not in ct

    def test_wrong_key_fails(self):
        key1 = generate_key(32)
        key2 = generate_key(32)
        ct = encrypt_block(key1, b"data")
        with pytest.raises(Exception):
            decrypt_block(key2, ct)

    def test_tampered_ciphertext_fails(self):
        key = generate_key(32)
        ct = encrypt_block(key, b"data")
        tampered = bytearray(ct)
        tampered[-1] ^= 0xFF
        with pytest.raises(Exception):
            decrypt_block(key, bytes(tampered))

    def test_with_aad(self):
        key = generate_key(32)
        aad = b"additional authenticated data"
        ct = encrypt_block(key, b"payload", aad=aad)
        result = decrypt_block(key, ct, aad=aad)
        assert result == b"payload"

    def test_wrong_aad_fails(self):
        key = generate_key(32)
        ct = encrypt_block(key, b"payload", aad=b"correct")
        with pytest.raises(Exception):
            decrypt_block(key, ct, aad=b"wrong")

    def test_empty_plaintext(self):
        key = generate_key(32)
        ct = encrypt_block(key, b"")
        result = decrypt_block(key, ct)
        assert result == b""

    def test_large_plaintext(self):
        key = generate_key(32)
        plaintext = os.urandom(1_000_000)  # 1MB
        ct = encrypt_block(key, plaintext)
        result = decrypt_block(key, ct)
        assert result == plaintext


class TestKeyWrap:
    def test_wrap_unwrap(self):
        wrapping_key = generate_key(32)
        key_to_wrap = generate_key(32)
        wrapped = wrap_key(wrapping_key, key_to_wrap)
        unwrapped = unwrap_key(wrapping_key, wrapped)
        assert unwrapped == key_to_wrap

    def test_wrong_wrapping_key_fails(self):
        wk1 = generate_key(32)
        wk2 = generate_key(32)
        wrapped = wrap_key(wk1, generate_key(32))
        with pytest.raises(Exception):
            unwrap_key(wk2, wrapped)

    def test_wrap_16_byte_key(self):
        wrapping_key = generate_key(32)
        key_to_wrap = generate_key(16)
        wrapped = wrap_key(wrapping_key, key_to_wrap)
        unwrapped = unwrap_key(wrapping_key, wrapped)
        assert unwrapped == key_to_wrap


class TestUtility:
    def test_generate_key_default(self):
        k = generate_key()
        assert len(k) == 32

    def test_generate_key_custom_length(self):
        k = generate_key(16)
        assert len(k) == 16

    def test_generate_salt(self):
        s = generate_salt()
        assert len(s) == 16

    def test_constant_time_compare(self):
        assert constant_time_compare(b"abc", b"abc")
        assert not constant_time_compare(b"abc", b"abd")


# ── Streaming ──────────────────────────────────────────────────────────

class TestStreamEncryption:
    def test_encrypt_decrypt_file(self, tmp_path):
        key = generate_key(32)
        plaintext = b"Hello streaming encryption! " * 1000
        src = tmp_path / "plain.bin"
        enc = tmp_path / "encrypted.bin"
        dec = tmp_path / "decrypted.bin"
        src.write_bytes(plaintext)

        encrypt_file(key, src, enc)
        assert enc.read_bytes() != plaintext  # encrypted differs

        decrypt_file(key, enc, dec)
        assert dec.read_bytes() == plaintext

    def test_encrypt_decrypt_large_file(self, tmp_path):
        key = generate_key(32)
        plaintext = os.urandom(500_000)  # 500KB, spans multiple chunks
        src = tmp_path / "large.bin"
        enc = tmp_path / "large.enc"
        dec = tmp_path / "large.dec"
        src.write_bytes(plaintext)

        encrypt_file(key, src, enc)
        decrypt_file(key, enc, dec)
        assert dec.read_bytes() == plaintext

    def test_wrong_key_stream_fails(self, tmp_path):
        key1 = generate_key(32)
        key2 = generate_key(32)
        src = tmp_path / "data.bin"
        enc = tmp_path / "data.enc"
        dec = tmp_path / "data.dec"
        src.write_bytes(b"secret data " * 100)

        encrypt_file(key1, src, enc)
        with pytest.raises(Exception):
            decrypt_file(key2, enc, dec)

    def test_maximum_method_stream(self, tmp_path):
        key = generate_key(32)
        plaintext = b"maximum method test " * 500
        src = tmp_path / "max.bin"
        enc = tmp_path / "max.enc"
        dec = tmp_path / "max.dec"
        src.write_bytes(plaintext)

        encrypt_file(key, src, enc, method="maximum")
        decrypt_file(key, enc, dec)
        assert dec.read_bytes() == plaintext

    def test_writer_reader_context(self, tmp_path):
        key = generate_key(32)
        enc = tmp_path / "ctx.enc"
        data = b"chunk1" + b"chunk2" + b"chunk3"

        with EncryptedFileWriter(key, enc) as writer:
            writer.write_chunk(b"chunk1")
            writer.write_chunk(b"chunk2")
            writer.write_chunk(b"chunk3")

        with EncryptedFileReader(key, enc) as reader:
            result = reader.read_all()
        assert result == data

    def test_empty_file(self, tmp_path):
        key = generate_key(32)
        src = tmp_path / "empty.bin"
        enc = tmp_path / "empty.enc"
        dec = tmp_path / "empty.dec"
        src.write_bytes(b"")

        encrypt_file(key, src, enc)
        decrypt_file(key, enc, dec)
        assert dec.read_bytes() == b""


# ── Key Management ─────────────────────────────────────────────────────

class TestMasterKeyManager:
    def test_initialize_and_load(self, tmp_path):
        mkm = MasterKeyManager(tmp_path)
        assert not mkm.is_initialized

        mk = mkm.initialize("admin_pass")
        assert mkm.is_initialized
        assert len(mk) == 32

        # Clear cache and reload
        mkm.clear_cache()
        loaded = mkm.load("admin_pass")
        assert loaded == mk

    def test_wrong_password_fails(self, tmp_path):
        mkm = MasterKeyManager(tmp_path)
        mkm.initialize("correct_password")
        mkm.clear_cache()

        with pytest.raises(ValueError):
            mkm.load("wrong_password")

    def test_double_init_fails(self, tmp_path):
        mkm = MasterKeyManager(tmp_path)
        mkm.initialize("pass")
        with pytest.raises(RuntimeError):
            mkm.initialize("pass")

    def test_verify(self, tmp_path):
        mkm = MasterKeyManager(tmp_path)
        mkm.initialize("secret")
        mkm.clear_cache()
        assert mkm.verify("secret")
        mkm.clear_cache()
        assert not mkm.verify("wrong")

    def test_export_backup(self, tmp_path):
        mkm = MasterKeyManager(tmp_path)
        mk = mkm.initialize("pass")
        backup = mkm.export_backup("pass")
        import base64
        assert base64.b64decode(backup) == mk

    def test_get_metadata(self, tmp_path):
        mkm = MasterKeyManager(tmp_path)
        mkm.initialize("pass", method="standard")
        meta = mkm.get_metadata()
        assert meta is not None
        assert meta["kdf_method"] == "standard"
        assert "key_id" in meta
        assert "created_at" in meta


class TestProjectKeyManager:
    def test_create_and_load_project_key(self, tmp_path):
        mkm = MasterKeyManager(tmp_path)
        mkm.initialize("admin")
        pkm = ProjectKeyManager(mkm)

        pk, enc_meta = pkm.create_project_key("proj1", "standard")
        assert len(pk) == 32
        assert enc_meta["enabled"] is True
        assert enc_meta["method"] == "standard"

        # Clear cache and reload
        pkm.clear_cache()
        loaded = pkm.load_project_key("proj1", enc_meta)
        assert loaded == pk

    def test_light_key_length(self, tmp_path):
        mkm = MasterKeyManager(tmp_path)
        mkm.initialize("admin")
        pkm = ProjectKeyManager(mkm)

        pk, meta = pkm.create_project_key("proj_light", "light")
        assert len(pk) == 16

    def test_rewrap_project_key(self, tmp_path):
        mkm = MasterKeyManager(tmp_path)
        mkm.initialize("admin")
        pkm = ProjectKeyManager(mkm)

        pk, enc_meta = pkm.create_project_key("proj2", "standard")
        updated = pkm.rewrap_project_key("proj2", enc_meta)
        assert "rewrapped_at" in updated
        # AES Key Wrap is deterministic — same key + same wrapping key = same output
        # So we just verify the key can still be loaded
        pkm.clear_cache()
        loaded = pkm.load_project_key("proj2", updated)
        assert loaded == pk


# ── Recovery ───────────────────────────────────────────────────────────

class TestRecoveryTokenManager:
    def test_generate_and_validate(self, tmp_path):
        rtm = RecoveryTokenManager(tmp_path)
        token, record = rtm.generate_token("admin1", "user1")
        assert len(token) > 20
        assert record["target_user_id"] == "user1"

        result = rtm.validate_token(token, "user1")
        assert result is not None
        assert result["target_user_id"] == "user1"

    def test_invalid_token(self, tmp_path):
        rtm = RecoveryTokenManager(tmp_path)
        rtm.generate_token("admin1", "user1")
        assert rtm.validate_token("invalid_token", "user1") is None

    def test_wrong_user_id(self, tmp_path):
        rtm = RecoveryTokenManager(tmp_path)
        token, _ = rtm.generate_token("admin1", "user1")
        assert rtm.validate_token(token, "user2") is None

    def test_invalidate_token(self, tmp_path):
        rtm = RecoveryTokenManager(tmp_path)
        token, _ = rtm.generate_token("admin1", "user1")

        assert rtm.validate_token(token, "user1") is not None
        rtm.invalidate_token(token)
        assert rtm.validate_token(token, "user1") is None

    def test_list_active_tokens(self, tmp_path):
        rtm = RecoveryTokenManager(tmp_path)
        rtm.generate_token("admin1", "user1")
        rtm.generate_token("admin1", "user2")

        active = rtm.list_active_tokens()
        assert len(active) == 2

        active_admin = rtm.list_active_tokens("admin1")
        assert len(active_admin) == 2

    def test_expired_token_purged(self, tmp_path):
        rtm = RecoveryTokenManager(tmp_path)
        token, _ = rtm.generate_token("admin1", "user1", ttl_hours=0)
        # Token with 0h TTL should be expired immediately
        # (the token is created with expires_at = now + 0h = now, so it's borderline)
        # We manually test by checking the purge logic works
        import time
        time.sleep(0.1)
        assert rtm.validate_token(token, "user1") is None
