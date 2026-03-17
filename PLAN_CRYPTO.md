# Plan: Moduł Analizy Crypto (BTC + ETH)

## Założenia
- **System offline** — brak połączenia z blockchainem/API
- Analiza oparta na **importowanych plikach** (CSV/JSON z giełd, exporty portfeli, ręczne dane)
- **LLM (Ollama)** do generowania narracji i oceny ryzyka
- Architektura analogiczna do modułu AML

## Źródła danych (offline)
1. **Eksporty z giełd**: Binance, Coinbase, Kraken, Bybit, KuCoin (CSV/JSON)
2. **Eksporty portfeli**: Electrum, MetaMask, Ledger Live, Trezor Suite (CSV)
3. **Etherscan/Blockchair offline export**: użytkownik pobiera CSV z transakcjami
4. **Ręczne wklejenie**: adresy portfeli, hash transakcji, dane smart kontraktów
5. **ABI smart kontraktów**: JSON z definicją interfejsu (do dekodowania calldata)

## Struktura modułu

### Backend: `backend/crypto/`
```
backend/crypto/
├── __init__.py
├── pipeline.py          # Główna orkiestracja analizy
├── parsers/
│   ├── __init__.py
│   ├── base.py          # Bazowe dataclassy (CryptoTransaction, WalletInfo)
│   ├── binance.py       # Parser CSV Binance
│   ├── coinbase.py      # Parser CSV Coinbase
│   ├── kraken.py        # Parser CSV Kraken
│   ├── etherscan.py     # Parser CSV Etherscan export
│   ├── blockchair.py    # Parser CSV Blockchair export
│   ├── electrum.py      # Parser CSV Electrum
│   ├── metamask.py      # Parser CSV MetaMask
│   └── generic.py       # Auto-detect + generic CSV parser
├── normalize.py         # Normalizacja transakcji crypto
├── address_analyzer.py  # Analiza adresów (wzorce, klasteryzacja)
├── contract_analyzer.py # Analiza smart kontraktów (ABI decode, wzorce)
├── risk_rules.py        # Reguły ryzyka (mikser, sanctioned, wzorce)
├── charts.py            # Generowanie wykresów (flow, timeline, pie)
├── graph.py             # Graf przepływów (Cytoscape.js)
├── llm_analysis.py      # Budowanie promptu LLM
├── report.py            # Generowanie raportu HTML
└── config/
    ├── rules.yaml       # Reguły klasyfikacji
    ├── sanctioned.json  # Lista znanych adresów sanctioned (OFAC)
    └── known_contracts.json  # Znane smart kontrakty (Uniswap, AAVE, etc.)
```

### Router: `webapp/routers/crypto.py`
Endpointy analogiczne do AML:
- `POST /api/crypto/analyze` — upload + analiza
- `GET /api/crypto/detail/{analysis_id}` — szczegóły
- `GET /api/crypto/history` — historia analiz
- `GET /api/crypto/charts/{analysis_id}` — wykresy
- `GET /api/crypto/graph/{analysis_id}` — graf przepływów
- `POST /api/crypto/llm-analyze/{analysis_id}` — analiza LLM
- `GET /api/crypto/llm-stream/{analysis_id}` — streaming SSE
- `POST /api/crypto/decode-abi` — dekodowanie smart contract ABI
- `GET /api/crypto/address-info/{address}` — info o adresie z lokalnych danych

### Frontend: `webapp/static/crypto.js`
- Manager pattern: `window.CryptoManager`
- Lazy init z tab switching
- Upload CSV/JSON + drag & drop
- Wykresy Chart.js (balance timeline, token distribution, gas fees)
- Graf Cytoscape.js (flow portfeli)
- Panel LLM z streamingiem

### Template: nowa sekcja w `analysis.html`
- Tab "Analiza Crypto" z ikoną ₿
- Empty state z logo
- Upload zone (CSV/JSON/TXT)
- Sekcja wyników: wallet info, transakcje, wykresy, graf, LLM

## Dataclassy

```python
@dataclass
class CryptoTransaction:
    tx_hash: str
    timestamp: str          # ISO 8601
    from_address: str
    to_address: str
    amount: Decimal
    token: str              # BTC, ETH, USDT, etc.
    fee: Decimal
    fee_token: str
    chain: str              # bitcoin, ethereum, polygon, etc.
    tx_type: str            # transfer, swap, contract_call, mint, burn
    status: str             # confirmed, pending, failed
    block_number: Optional[int]
    contract_address: Optional[str]  # for token transfers
    method_name: Optional[str]       # decoded contract method
    raw_input: Optional[str]         # calldata hex
    exchange: Optional[str]          # source exchange name
    category: str           # classified category
    risk_score: float
    risk_tags: List[str]

@dataclass
class WalletInfo:
    address: str
    chain: str
    label: Optional[str]    # known label (exchange, mixer, etc.)
    first_seen: Optional[str]
    last_seen: Optional[str]
    tx_count: int
    total_received: Decimal
    total_sent: Decimal
    tokens: Dict[str, Decimal]  # token balances
    risk_level: str         # low, medium, high, critical
    risk_reasons: List[str]
```

## Reguły ryzyka (offline)

### Wzorce adresów
- **Znane mikserzy**: Tornado Cash, Wasabi, JoinMarket (hardcoded adresy)
- **Sanctioned (OFAC)**: lista adresów z sankcjami (aktualizowana ręcznie)
- **Znane giełdy**: Binance hot wallets, Coinbase, Kraken (do klasyfikacji)
- **DeFi protokoły**: Uniswap, AAVE, Compound, MakerDAO (znane kontrakty)

### Wzorce transakcji
- **Peel chain**: seria transakcji z malejącymi kwotami
- **Dust attack**: wiele małych transakcji przychodzących
- **Round-trip**: środki wychodzą i wracają po cyklu
- **Smurfing**: wiele małych transakcji zamiast jednej dużej
- **Flash loan pattern**: pożyczka + operacja + zwrot w jednym bloku

### Smart kontrakty
- Dekodowanie ABI (offline — użytkownik dostarcza ABI JSON)
- Znane sygnatury metod (transfer, approve, swap, addLiquidity)
- Wzorce proxy patterns
- Analiza event logów (jeśli dostarczone w CSV)

## Etapy implementacji

### Etap 1: Szkielet (current)
- [x] Tab w analysis.html
- [x] Plik crypto.js (skeleton)
- [x] Router crypto.py (skeleton)
- [x] Backend crypto/ directory structure
- [x] Base dataclasses

### Etap 2: Parsery + pipeline
- [ ] Generic CSV parser (auto-detect exchange)
- [ ] Binance CSV parser
- [ ] Etherscan CSV parser
- [ ] Normalizacja transakcji
- [ ] Pipeline orchestration

### Etap 3: Analiza + wizualizacja
- [ ] Risk rules engine
- [ ] Charts (balance timeline, distribution)
- [ ] Flow graph (Cytoscape.js)
- [ ] Sanctioned addresses check

### Etap 4: Smart kontrakty + LLM
- [ ] ABI decoder
- [ ] Known contracts database
- [ ] LLM prompt builder
- [ ] Streaming analysis
- [ ] Report generation
