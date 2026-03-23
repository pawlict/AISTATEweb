#!/usr/bin/env python3
"""
AISTATEweb License Key Generator
=================================

Developer-only tool for generating signed Ed25519 license keys.
Has both GUI (default) and CLI modes.

Usage:
    # GUI mode (default):
    python scripts/keygen.py

    # CLI mode:
    python scripts/keygen.py --cli \\
        --email "jan@firma.pl" \\
        --name "Jan Kowalski" \\
        --plan pro \\
        --expires perpetual \\
        --updates-until perpetual \\
        --features all

    # Generate a new Ed25519 keypair (do this ONCE):
    python scripts/keygen.py --generate-keypair

The private key is stored in ~/.aistate_private_key.pem
The public key is printed for embedding in backend/licensing/public_key.py
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

PRIVATE_KEY_PATH = Path.home() / ".aistate_private_key.pem"


# ═══════════════════════════════════════════════════════════════
#  Crypto helpers
# ═══════════════════════════════════════════════════════════════

def generate_keypair() -> str:
    """Generate a new Ed25519 keypair and save the private key.

    Returns a status message.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        return "BLAD: Brak biblioteki cryptography. Zainstaluj: pip install cryptography"

    if PRIVATE_KEY_PATH.exists():
        return (
            f"Klucz prywatny juz istnieje: {PRIVATE_KEY_PATH}\n"
            "Uzyj --generate-keypair w CLI z potwierdzeniem nadpisania."
        )

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    # Save private key
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    PRIVATE_KEY_PATH.write_bytes(pem)
    PRIVATE_KEY_PATH.chmod(0o600)

    # Public key
    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pub_b64 = base64.b64encode(pub_bytes).decode()

    return (
        f"Klucz prywatny zapisany: {PRIVATE_KEY_PATH}\n\n"
        f"Klucz publiczny (base64) — wklej do backend/licensing/public_key.py:\n"
        f'PUBLIC_KEY_B64: str = "{pub_b64}"'
    )


def load_private_key():
    """Load the Ed25519 private key from disk."""
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except ImportError:
        raise RuntimeError("Brak biblioteki cryptography. Zainstaluj: pip install cryptography")

    if not PRIVATE_KEY_PATH.exists():
        raise RuntimeError(
            f"Nie znaleziono klucza prywatnego: {PRIVATE_KEY_PATH}\n"
            "Najpierw wygeneruj pare kluczy."
        )

    pem = PRIVATE_KEY_PATH.read_bytes()
    return load_pem_private_key(pem, password=None)


def generate_license_key(
    email: str,
    name: str,
    plan: str,
    expires: str,
    updates_until: str,
    features: str,
) -> str:
    """Generate a signed license key string."""
    private_key = load_private_key()

    lid = f"{plan.upper()}-{uuid.uuid4().hex[:8].upper()}"

    payload = {
        "lid": lid,
        "name": name,
        "email": email,
        "plan": plan,
        "issued": date.today().isoformat(),
        "expires": expires,
        "updates_until": updates_until,
    }

    if features == "all":
        payload["features"] = ["all"]
    else:
        payload["features"] = [f.strip() for f in features.split(",")]

    payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    data_b64 = base64.b64encode(payload_json.encode("utf-8")).decode("utf-8")

    signature = private_key.sign(data_b64.encode("utf-8"))
    sig_b64 = base64.b64encode(signature).decode("utf-8")

    return f"AIST-{data_b64}.{sig_b64}"


# ═══════════════════════════════════════════════════════════════
#  GUI
# ═══════════════════════════════════════════════════════════════

def run_gui() -> None:
    """Launch the tkinter GUI for license key generation."""
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox
    except ImportError:
        print("BLAD: tkinter niedostepny. Uzyj trybu CLI: python scripts/keygen.py --cli ...")
        sys.exit(1)

    root = tk.Tk()
    root.title("AISTATEweb — Generator Kluczy Licencyjnych")
    root.geometry("720x780")
    root.resizable(True, True)
    root.configure(bg="#f8fafc")

    # ── Styles ──
    FONT = ("Segoe UI", 11)
    FONT_BOLD = ("Segoe UI", 11, "bold")
    FONT_TITLE = ("Segoe UI", 16, "bold")
    FONT_MONO = ("Consolas", 10)
    BG = "#f8fafc"
    CARD_BG = "#ffffff"
    ACCENT = "#2563eb"
    BORDER = "#e2e8f0"
    TEXT = "#1a1a2e"
    MUTED = "#64748b"

    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Accent.TButton", font=FONT_BOLD, padding=10)

    # ── Main frame ──
    main_frame = tk.Frame(root, bg=BG, padx=24, pady=16)
    main_frame.pack(fill="both", expand=True)

    # Title
    tk.Label(main_frame, text="Generator Kluczy Licencyjnych", font=FONT_TITLE,
             bg=BG, fg=TEXT).pack(anchor="w", pady=(0, 4))
    tk.Label(main_frame, text="AISTATEweb — narzedzie deweloperskie", font=("Segoe UI", 10),
             bg=BG, fg=MUTED).pack(anchor="w", pady=(0, 16))

    # ── Form card ──
    form_card = tk.Frame(main_frame, bg=CARD_BG, bd=1, relief="solid",
                         highlightbackground=BORDER, highlightthickness=1)
    form_card.pack(fill="x", pady=(0, 12))

    form_inner = tk.Frame(form_card, bg=CARD_BG, padx=20, pady=16)
    form_inner.pack(fill="x")

    row = 0

    def add_label(text: str, r: int) -> None:
        tk.Label(form_inner, text=text, font=FONT_BOLD, bg=CARD_BG, fg=TEXT,
                 anchor="w").grid(row=r, column=0, sticky="w", pady=(8, 2), padx=(0, 16))

    def add_entry(r: int, width: int = 40) -> tk.Entry:
        e = tk.Entry(form_inner, font=FONT, width=width, relief="solid", bd=1,
                     highlightcolor=ACCENT, highlightthickness=1)
        e.grid(row=r, column=1, sticky="ew", pady=(8, 2))
        return e

    # Name
    add_label("Nazwa (firma / osoba):", row)
    entry_name = add_entry(row)
    row += 1

    # Email
    add_label("E-mail:", row)
    entry_email = add_entry(row)
    row += 1

    # Plan
    add_label("Plan:", row)
    plan_var = tk.StringVar(value="pro")
    plan_frame = tk.Frame(form_inner, bg=CARD_BG)
    plan_frame.grid(row=row, column=1, sticky="w", pady=(8, 2))
    for plan_val, plan_label in [("community", "Community"), ("pro", "Pro"), ("enterprise", "Enterprise")]:
        tk.Radiobutton(plan_frame, text=plan_label, variable=plan_var, value=plan_val,
                       font=FONT, bg=CARD_BG, fg=TEXT, activebackground=CARD_BG,
                       selectcolor=CARD_BG).pack(side="left", padx=(0, 16))
    row += 1

    # Expires
    add_label("Wygasa:", row)
    expires_frame = tk.Frame(form_inner, bg=CARD_BG)
    expires_frame.grid(row=row, column=1, sticky="w", pady=(8, 2))
    expires_perpetual = tk.BooleanVar(value=True)
    tk.Checkbutton(expires_frame, text="Bezterminowa", variable=expires_perpetual,
                   font=FONT, bg=CARD_BG, fg=TEXT, activebackground=CARD_BG,
                   selectcolor=CARD_BG).pack(side="left")
    entry_expires = tk.Entry(expires_frame, font=FONT, width=14, relief="solid", bd=1,
                             state="disabled")
    entry_expires.pack(side="left", padx=(12, 0))
    tk.Label(expires_frame, text="(RRRR-MM-DD)", font=("Segoe UI", 9), bg=CARD_BG,
             fg=MUTED).pack(side="left", padx=(4, 0))

    def toggle_expires():
        entry_expires.config(state="disabled" if expires_perpetual.get() else "normal")
    expires_perpetual.trace_add("write", lambda *_: toggle_expires())
    row += 1

    # Updates until
    add_label("Aktualizacje do:", row)
    updates_frame = tk.Frame(form_inner, bg=CARD_BG)
    updates_frame.grid(row=row, column=1, sticky="w", pady=(8, 2))
    updates_perpetual = tk.BooleanVar(value=True)
    tk.Checkbutton(updates_frame, text="Bezterminowa", variable=updates_perpetual,
                   font=FONT, bg=CARD_BG, fg=TEXT, activebackground=CARD_BG,
                   selectcolor=CARD_BG).pack(side="left")
    entry_updates = tk.Entry(updates_frame, font=FONT, width=14, relief="solid", bd=1,
                             state="disabled")
    entry_updates.pack(side="left", padx=(12, 0))
    tk.Label(updates_frame, text="(RRRR-MM-DD)", font=("Segoe UI", 9), bg=CARD_BG,
             fg=MUTED).pack(side="left", padx=(4, 0))

    def toggle_updates():
        entry_updates.config(state="disabled" if updates_perpetual.get() else "normal")
    updates_perpetual.trace_add("write", lambda *_: toggle_updates())
    row += 1

    # Features
    add_label("Funkcje:", row)
    features_var = tk.StringVar(value="all")
    feat_frame = tk.Frame(form_inner, bg=CARD_BG)
    feat_frame.grid(row=row, column=1, sticky="w", pady=(8, 2))
    tk.Radiobutton(feat_frame, text="Wszystkie", variable=features_var, value="all",
                   font=FONT, bg=CARD_BG, fg=TEXT, activebackground=CARD_BG,
                   selectcolor=CARD_BG).pack(side="left", padx=(0, 12))
    tk.Radiobutton(feat_frame, text="Wybrane:", variable=features_var, value="custom",
                   font=FONT, bg=CARD_BG, fg=TEXT, activebackground=CARD_BG,
                   selectcolor=CARD_BG).pack(side="left")
    entry_features = tk.Entry(feat_frame, font=FONT, width=30, relief="solid", bd=1)
    entry_features.pack(side="left", padx=(4, 0))
    entry_features.insert(0, "transcription,diarization,translation,analysis,chat,tts")
    row += 1

    form_inner.columnconfigure(1, weight=1)

    # ── Buttons ──
    btn_frame = tk.Frame(main_frame, bg=BG)
    btn_frame.pack(fill="x", pady=(8, 12))

    def on_generate():
        name = entry_name.get().strip()
        email = entry_email.get().strip()

        if not name:
            messagebox.showwarning("Brak nazwy", "Wpisz nazwe firmy lub imie i nazwisko.")
            entry_name.focus_set()
            return
        if not email:
            messagebox.showwarning("Brak e-maila", "Wpisz adres e-mail klienta.")
            entry_email.focus_set()
            return

        expires = "perpetual" if expires_perpetual.get() else entry_expires.get().strip()
        updates = "perpetual" if updates_perpetual.get() else entry_updates.get().strip()

        if not expires_perpetual.get() and not expires:
            messagebox.showwarning("Brak daty", "Wpisz date wygasniecia (RRRR-MM-DD).")
            return
        if not updates_perpetual.get() and not updates:
            messagebox.showwarning("Brak daty", "Wpisz date wygasniecia aktualizacji (RRRR-MM-DD).")
            return

        features = "all" if features_var.get() == "all" else entry_features.get().strip()
        if features_var.get() == "custom" and not features:
            messagebox.showwarning("Brak funkcji", "Wpisz liste funkcji oddzielonych przecinkami.")
            return

        try:
            key = generate_license_key(
                email=email,
                name=name,
                plan=plan_var.get(),
                expires=expires,
                updates_until=updates,
                features=features,
            )
        except RuntimeError as e:
            messagebox.showerror("Blad", str(e))
            return

        # Show result
        result_text.config(state="normal")
        result_text.delete("1.0", "end")
        result_text.insert("1.0", key)
        result_text.config(state="normal")

        # Details
        details = (
            f"Nazwa:          {name}\n"
            f"E-mail:         {email}\n"
            f"Plan:           {plan_var.get()}\n"
            f"Wygasa:         {expires}\n"
            f"Aktualizacje:   {updates}\n"
            f"Funkcje:        {features}\n"
            f"Data wydania:   {date.today().isoformat()}"
        )
        details_text.config(state="normal")
        details_text.delete("1.0", "end")
        details_text.insert("1.0", details)
        details_text.config(state="disabled")

    def on_copy():
        content = result_text.get("1.0", "end").strip()
        if content:
            root.clipboard_clear()
            root.clipboard_append(content)
            messagebox.showinfo("Skopiowano", "Klucz licencyjny skopiowany do schowka.")

    def on_generate_keypair():
        msg = generate_keypair()
        messagebox.showinfo("Generowanie pary kluczy", msg)

    gen_btn = tk.Button(btn_frame, text="Generuj klucz licencyjny", font=FONT_BOLD,
                        bg=ACCENT, fg="white", activebackground="#1d4ed8", activeforeground="white",
                        relief="flat", padx=20, pady=8, cursor="hand2", command=on_generate)
    gen_btn.pack(side="left")

    copy_btn = tk.Button(btn_frame, text="Kopiuj do schowka", font=FONT,
                         bg="#e2e8f0", fg=TEXT, relief="flat", padx=16, pady=8,
                         cursor="hand2", command=on_copy)
    copy_btn.pack(side="left", padx=(12, 0))

    keypair_btn = tk.Button(btn_frame, text="Generuj pare kluczy Ed25519", font=("Segoe UI", 10),
                            bg="#fef3c7", fg="#92400e", relief="flat", padx=12, pady=8,
                            cursor="hand2", command=on_generate_keypair)
    keypair_btn.pack(side="right")

    # ── Result area ──
    tk.Label(main_frame, text="Wygenerowany klucz:", font=FONT_BOLD, bg=BG, fg=TEXT
             ).pack(anchor="w", pady=(8, 4))

    result_text = tk.Text(main_frame, height=4, font=FONT_MONO, wrap="char",
                          relief="solid", bd=1, bg="#f1f5f9", fg="#7c3aed",
                          selectbackground=ACCENT, selectforeground="white")
    result_text.pack(fill="x", pady=(0, 12))

    tk.Label(main_frame, text="Szczegoly:", font=FONT_BOLD, bg=BG, fg=TEXT
             ).pack(anchor="w", pady=(4, 4))

    details_text = tk.Text(main_frame, height=7, font=FONT_MONO, wrap="word",
                           relief="solid", bd=1, bg="#f1f5f9", fg=TEXT, state="disabled")
    details_text.pack(fill="x")

    # ── Status bar ──
    has_key = PRIVATE_KEY_PATH.exists()
    status_color = "#16a34a" if has_key else "#dc2626"
    status_msg = f"Klucz prywatny: {PRIVATE_KEY_PATH}" if has_key else "BRAK klucza prywatnego — najpierw wygeneruj pare kluczy"
    status_bar = tk.Label(main_frame, text=status_msg, font=("Segoe UI", 9),
                          bg=BG, fg=status_color, anchor="w")
    status_bar.pack(fill="x", pady=(12, 0))

    root.mainloop()


# ═══════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════

def run_cli() -> None:
    """Classic CLI mode."""
    parser = argparse.ArgumentParser(description="AISTATEweb License Key Generator")
    parser.add_argument("--cli", action="store_true", help="Run in CLI mode (no GUI)")
    parser.add_argument("--generate-keypair", action="store_true",
                        help="Generate a new Ed25519 keypair")
    parser.add_argument("--email", default="", help="Customer email")
    parser.add_argument("--name", default="",
                        help="Customer name (person or company)")
    parser.add_argument("--plan", default="pro", choices=["community", "pro", "enterprise"],
                        help="License plan (default: pro)")
    parser.add_argument("--expires", default="perpetual",
                        help="Expiry date (YYYY-MM-DD or 'perpetual')")
    parser.add_argument("--updates-until", default="perpetual",
                        help="Updates valid until (YYYY-MM-DD or 'perpetual')")
    parser.add_argument("--features", default="all",
                        help="Comma-separated features or 'all'")

    args = parser.parse_args()

    if args.generate_keypair:
        if PRIVATE_KEY_PATH.exists():
            resp = input(f"Klucz prywatny juz istnieje: {PRIVATE_KEY_PATH}. Nadpisac? [y/N] ")
            if resp.lower() != "y":
                print("Przerwano.")
                return
            PRIVATE_KEY_PATH.unlink()
        msg = generate_keypair()
        print(msg)
        return

    if not args.email:
        print("BLAD: --email jest wymagany")
        sys.exit(1)

    if not args.name:
        print("BLAD: --name jest wymagany")
        sys.exit(1)

    key = generate_license_key(
        email=args.email,
        name=args.name,
        plan=args.plan,
        expires=args.expires,
        updates_until=args.updates_until,
        features=args.features,
    )

    print(f"\nKlucz licencyjny:")
    print(f"{key}")
    print(f"\nSzczegoly:")
    print(f"  Nazwa:        {args.name}")
    print(f"  E-mail:       {args.email}")
    print(f"  Plan:         {args.plan}")
    print(f"  Wygasa:       {args.expires}")
    print(f"  Aktualizacje: {args.updates_until}")
    print(f"  Funkcje:      {args.features}")
    print(f"\nWyslij ten klucz klientowi.")


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    if "--cli" in sys.argv or "--generate-keypair" in sys.argv:
        run_cli()
    else:
        run_gui()


if __name__ == "__main__":
    main()
