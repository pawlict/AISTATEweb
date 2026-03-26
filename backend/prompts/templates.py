"""System (built-in) prompt templates.

These templates are always available and cannot be deleted by the user.
They are intended to be combinable into a single composite instruction.
"""

from __future__ import annotations

from typing import Dict, Any


PROMPT_LIBRARY: Dict[str, Dict[str, Any]] = {
    "protokol": {
        "id": "protokol",
        # NOTE: keep emoji in `icon`, not in `name`.
        # Frontend renders: {icon} {name}. This avoids duplicated icons.
        "name": "Protokół ze spotkania",
        "icon": "📋",
        "category": "System",
        "prompt": "Stwórz formalny protokół ze spotkania: data, uczestnicy, agenda, decyzje, zadania (action items) z odpowiedzialnymi osobami, terminy, ryzyka i kolejne kroki. Jeśli czegoś brakuje, zaznacz to jako 'brak danych'.",
        "combinable": True,
    },
    "miejsca": {
        "id": "miejsca",
        "name": "Identyfikacja miejsc",
        "icon": "📍",
        "category": "System",
        "prompt": "Wyodrębnij wszystkie lokalizacje (miasta, adresy, obiekty, regiony) wspomniane w materiale. Dla każdej lokalizacji podaj kontekst (w jakim zdaniu/temacie występuje) i ewentualny typ miejsca.",
        "combinable": True,
    },
    "terminy": {
        "id": "terminy",
        "name": "Ekstrakcja terminów",
        "icon": "📅",
        "category": "System",
        "prompt": "Znajdź wszystkie daty, deadline'y, terminy spotkań i odwołania czasowe. Normalizuj daty do ISO (YYYY-MM-DD), a gdy brakuje roku/miesiąca, zaznacz niepewność.",
        "combinable": True,
    },
    "action_items": {
        "id": "action_items",
        "name": "Lista zadań",
        "icon": "✅",
        "category": "System",
        "prompt": "Wyciągnij konkretne zadania (action items) wraz z osobą odpowiedzialną, priorytetem (jeśli wynika) oraz terminem. Jeśli nie ma osoby/terminu, oznacz jako 'nieustalone'.",
        "combinable": True,
    },
    "wydatki": {
        "id": "wydatki",
        "name": "Analiza wydatków",
        "icon": "💰",
        "category": "System",
        "prompt": "Przeanalizuj koszty i wydatki wspomniane w materiale oraz w załączonych dokumentach (rachunki, faktury). Zidentyfikuj kwoty, waluty, kategorie wydatków, beneficjentów i potencjalne niezgodności.",
        "combinable": True,
    },
    "wyciag_bankowy": {
        "id": "wyciag_bankowy",
        "name": "Analiza wyciągu bankowego",
        "icon": "🏦",
        "category": "System",
        "description": "Autonomiczna analiza finansowa wyciągu bankowego (PDF). Automatycznie rozpoznaje bank, parsuje transakcje, klasyfikuje ryzyka (hazard, krypto, pożyczki) i generuje scoring finansowy.",
        "prompt": "Przeprowadź kompleksową analizę finansową wyciągu bankowego. Zbadaj przepływy finansowe, powtarzalność zobowiązań, wykryj pożyczki, raty, koszty obsługi długu, zakupy kryptowalut, transakcje hazardowe i inne podejrzane podmioty. Oceń czy właściciel rachunku żyje w ramach wpływów czy generuje deficyt. Podaj scoring finansowy z uzasadnieniem.",
        "combinable": False,
        "_finance_mode": True,
    },
}
