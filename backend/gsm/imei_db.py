"""IMEI/TAC device identification database.

Maps the TAC (Type Allocation Code — first 8 digits of IMEI) to device
brand, model, and type.  The built-in database is loaded from
``tac_database.json`` alongside this module; users can extend it by
placing a ``tac_custom.json`` file in the same directory.

Additionally provides:
- Reporting Body identification (first 2 digits → country/region of TAC allocation)
- Manufacturer prefix fallback (first 6 digits → brand, when exact 8-digit TAC unknown)
- Luhn check-digit computation and validation
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

_DB_DIR = Path(__file__).resolve().parent
_BUILTIN_DB = _DB_DIR / "tac_database.json"
_CUSTOM_DB = _DB_DIR / "tac_custom.json"

# Singleton cache
_tac_cache: Optional[Dict[str, dict]] = None

# ── TAC Reporting Body Identifiers (first 2 digits of IMEI → allocation region) ──
# Source: GSMA / ITU-T Recommendation E.118
_REPORTING_BODIES: Dict[str, Dict[str, str]] = {
    "01": {"body": "PTCRB", "country": "USA", "region": "Ameryka Północna"},
    "02": {"body": "PTCRB (dawne GHA)", "country": "USA", "region": "Ameryka Północna"},
    "03": {"body": "PTCRB", "country": "USA", "region": "Ameryka Północna"},
    "04": {"body": "PTCRB", "country": "USA", "region": "Ameryka Północna"},
    "05": {"body": "PTCRB", "country": "USA", "region": "Ameryka Północna"},
    "06": {"body": "PTCRB", "country": "USA", "region": "Ameryka Północna"},
    "07": {"body": "PTCRB", "country": "USA", "region": "Ameryka Północna"},
    "08": {"body": "PTCRB", "country": "USA", "region": "Ameryka Północna"},
    "09": {"body": "PTCRB", "country": "USA", "region": "Ameryka Północna"},
    "10": {"body": "PTCRB", "country": "USA", "region": "Ameryka Północna"},
    "30": {"body": "PTCRB", "country": "USA", "region": "Ameryka Północna"},
    "31": {"body": "PTCRB", "country": "USA", "region": "Ameryka Północna"},
    "32": {"body": "PTCRB", "country": "USA", "region": "Ameryka Północna"},
    "33": {"body": "PTCRB", "country": "USA", "region": "Ameryka Północna"},
    "34": {"body": "PTCRB", "country": "USA", "region": "Ameryka Północna"},
    "35": {"body": "BABT", "country": "Wielka Brytania", "region": "Europa"},
    "44": {"body": "BABT", "country": "Wielka Brytania", "region": "Europa"},
    "45": {"body": "TTA/TTC", "country": "Korea Płd. / Japonia", "region": "Azja"},
    "49": {"body": "TTA/TTC", "country": "Korea Płd. / Japonia", "region": "Azja"},
    "50": {"body": "MSAI", "country": "Indie", "region": "Azja"},
    "51": {"body": "MSAI", "country": "Indie", "region": "Azja"},
    "52": {"body": "MSAI", "country": "Indie", "region": "Azja"},
    "53": {"body": "CECT", "country": "Chiny", "region": "Azja"},
    "54": {"body": "CECT", "country": "Chiny", "region": "Azja"},
    "86": {"body": "CECT", "country": "Chiny", "region": "Azja"},
    "91": {"body": "CECT", "country": "Chiny", "region": "Azja"},
    "98": {"body": "CECT", "country": "Chiny", "region": "Azja"},
    "99": {"body": "CECT", "country": "Chiny", "region": "Azja"},
    "67": {"body": "CPqD", "country": "Brazylia", "region": "Ameryka Południowa"},
    "68": {"body": "CPqD", "country": "Brazylia", "region": "Ameryka Południowa"},
    "70": {"body": "IFETEL", "country": "Meksyk", "region": "Ameryka Północna"},
}

# ── Manufacturer prefix database (first 6 digits of TAC → brand) ──
# This allows identifying the manufacturer even when the exact 8-digit TAC is
# not in our model database.  Based on known TAC allocations to manufacturers.
_MANUFACTURER_PREFIXES: Dict[str, str] = {
    # Apple — allocated TAC ranges (BABT, UK)
    "013888": "Apple", "013908": "Apple", "013942": "Apple",
    "352030": "Apple", "352032": "Apple", "352053": "Apple", "352060": "Apple",
    "352065": "Apple", "352088": "Apple", "352091": "Apple", "352099": "Apple",
    "352109": "Apple", "352146": "Apple", "352157": "Apple", "352178": "Apple",
    "352198": "Apple", "352200": "Apple", "352229": "Apple", "352237": "Apple",
    "352260": "Apple", "352277": "Apple", "352296": "Apple", "352309": "Apple",
    "352320": "Apple", "352389": "Apple", "352400": "Apple", "352413": "Apple",
    "352429": "Apple", "352441": "Apple", "353195": "Apple", "353226": "Apple",
    "353259": "Apple", "353267": "Apple", "353300": "Apple", "353307": "Apple",
    "353376": "Apple", "353377": "Apple", "353436": "Apple", "353762": "Apple",
    "353837": "Apple", "353879": "Apple", "354381": "Apple", "354382": "Apple",
    "354383": "Apple", "354430": "Apple", "354431": "Apple", "354439": "Apple",
    "354444": "Apple", "354456": "Apple", "354565": "Apple", "354566": "Apple",
    "354567": "Apple", "354568": "Apple", "354569": "Apple", "354570": "Apple",
    "354571": "Apple",
    # Samsung — large allocation blocks
    "352029": "Samsung", "352045": "Samsung", "352066": "Samsung", "352070": "Samsung",
    "352080": "Samsung", "352094": "Samsung", "352107": "Samsung", "352115": "Samsung",
    "352131": "Samsung", "352136": "Samsung", "352141": "Samsung", "352156": "Samsung",
    "352159": "Samsung", "352172": "Samsung", "352186": "Samsung", "352199": "Samsung",
    "352201": "Samsung", "352211": "Samsung", "352239": "Samsung", "352248": "Samsung",
    "352263": "Samsung", "352274": "Samsung", "352280": "Samsung", "352287": "Samsung",
    "352315": "Samsung", "352317": "Samsung", "352324": "Samsung", "352341": "Samsung",
    "352356": "Samsung", "352362": "Samsung", "352376": "Samsung", "352382": "Samsung",
    "352393": "Samsung", "352398": "Samsung", "352403": "Samsung", "352410": "Samsung",
    "352425": "Samsung", "352432": "Samsung", "352449": "Samsung", "352453": "Samsung",
    "352470": "Samsung", "352475": "Samsung", "352484": "Samsung", "352492": "Samsung",
    "352500": "Samsung", "352503": "Samsung", "352515": "Samsung", "352531": "Samsung",
    "352543": "Samsung", "352551": "Samsung", "352560": "Samsung", "352573": "Samsung",
    "352583": "Samsung", "352597": "Samsung", "354679": "Samsung", "354686": "Samsung",
    "354700": "Samsung", "354707": "Samsung", "354721": "Samsung", "354765": "Samsung",
    "354809": "Samsung", "354812": "Samsung", "354837": "Samsung", "354849": "Samsung",
    "354861": "Samsung", "354877": "Samsung", "354880": "Samsung", "354891": "Samsung",
    "354905": "Samsung", "354913": "Samsung", "354925": "Samsung", "354936": "Samsung",
    "354953": "Samsung", "354973": "Samsung", "354987": "Samsung",
    "356127": "Samsung", "356137": "Samsung", "356149": "Samsung", "356157": "Samsung",
    "356175": "Samsung", "356181": "Samsung", "356196": "Samsung", "356204": "Samsung",
    "356216": "Samsung", "356249": "Samsung", "356268": "Samsung", "356272": "Samsung",
    "356283": "Samsung", "356290": "Samsung", "356301": "Samsung", "356316": "Samsung",
    "356331": "Samsung", "356344": "Samsung", "356365": "Samsung", "356371": "Samsung",
    "356395": "Samsung", "356402": "Samsung", "356424": "Samsung", "356437": "Samsung",
    "356444": "Samsung", "356458": "Samsung", "356463": "Samsung", "356479": "Samsung",
    "356489": "Samsung", "356497": "Samsung", "356507": "Samsung", "356525": "Samsung",
    "356530": "Samsung", "356546": "Samsung", "356553": "Samsung", "356586": "Samsung",
    "356590": "Samsung",
    # Huawei
    "355618": "Huawei", "355645": "Huawei", "355673": "Huawei", "355694": "Huawei",
    "355715": "Huawei", "355739": "Huawei", "355753": "Huawei", "355778": "Huawei",
    "355795": "Huawei", "355810": "Huawei", "355826": "Huawei", "355849": "Huawei",
    "355862": "Huawei", "355876": "Huawei", "355891": "Huawei", "355914": "Huawei",
    "355936": "Huawei", "355948": "Huawei", "355967": "Huawei", "355984": "Huawei",
    "860018": "Huawei", "860033": "Huawei", "860047": "Huawei", "860056": "Huawei",
    "860078": "Huawei", "860091": "Huawei", "860102": "Huawei", "860120": "Huawei",
    "860142": "Huawei", "860155": "Huawei", "860172": "Huawei", "860191": "Huawei",
    "860213": "Huawei", "860228": "Huawei", "860247": "Huawei", "860251": "Huawei",
    "860269": "Huawei", "860283": "Huawei", "860294": "Huawei", "860300": "Huawei",
    "860319": "Huawei", "860325": "Huawei", "860341": "Huawei", "860352": "Huawei",
    "862260": "Huawei", "862275": "Huawei", "862289": "Huawei", "862300": "Huawei",
    "862318": "Huawei", "862324": "Huawei", "862345": "Huawei", "862361": "Huawei",
    "862389": "Huawei", "862396": "Huawei", "862401": "Huawei", "862425": "Huawei",
    "862443": "Huawei", "862468": "Huawei",
    "866179": "Huawei", "866193": "Huawei", "866541": "Huawei", "866570": "Huawei",
    "866587": "Huawei", "866604": "Huawei", "866613": "Huawei", "866658": "Huawei",
    "866679": "Huawei", "866690": "Huawei", "866703": "Huawei", "866735": "Huawei",
    "866760": "Huawei", "866789": "Huawei", "866791": "Huawei", "866814": "Huawei",
    "866837": "Huawei", "866853": "Huawei", "866881": "Huawei", "866892": "Huawei",
    "866907": "Huawei", "866934": "Huawei", "866954": "Huawei", "866978": "Huawei",
    # Xiaomi / Redmi
    "861050": "Xiaomi", "861076": "Xiaomi", "861097": "Xiaomi", "861102": "Xiaomi",
    "861125": "Xiaomi", "861148": "Xiaomi", "861163": "Xiaomi", "861187": "Xiaomi",
    "861190": "Xiaomi", "861205": "Xiaomi", "861228": "Xiaomi", "861246": "Xiaomi",
    "861265": "Xiaomi", "861281": "Xiaomi", "861303": "Xiaomi", "861320": "Xiaomi",
    "861336": "Xiaomi", "861359": "Xiaomi", "861371": "Xiaomi", "861392": "Xiaomi",
    "861408": "Xiaomi", "861425": "Xiaomi", "861443": "Xiaomi", "861467": "Xiaomi",
    "861489": "Xiaomi", "861501": "Xiaomi", "861527": "Xiaomi", "861548": "Xiaomi",
    "861564": "Xiaomi", "861583": "Xiaomi", "861605": "Xiaomi", "861627": "Xiaomi",
    "861641": "Xiaomi", "861668": "Xiaomi", "861682": "Xiaomi", "861709": "Xiaomi",
    "861724": "Xiaomi", "861750": "Xiaomi", "861773": "Xiaomi", "861791": "Xiaomi",
    "860940": "Xiaomi", "860963": "Xiaomi", "860985": "Xiaomi",
    # OPPO
    "861800": "OPPO", "861823": "OPPO", "861845": "OPPO", "861867": "OPPO",
    "861889": "OPPO", "861901": "OPPO", "861925": "OPPO", "861947": "OPPO",
    "861969": "OPPO", "861981": "OPPO", "862003": "OPPO", "862026": "OPPO",
    "862048": "OPPO", "862065": "OPPO", "862089": "OPPO",
    "864007": "OPPO", "864023": "OPPO", "864045": "OPPO", "864068": "OPPO",
    # Vivo
    "862100": "Vivo", "862125": "Vivo", "862143": "Vivo", "862167": "Vivo",
    "862189": "Vivo", "862201": "Vivo", "862225": "Vivo", "862247": "Vivo",
    # Realme
    "868030": "Realme", "868052": "Realme", "868078": "Realme", "868091": "Realme",
    "868112": "Realme", "868135": "Realme", "868157": "Realme", "868179": "Realme",
    # OnePlus
    "868207": "OnePlus", "868225": "OnePlus", "868249": "OnePlus", "868263": "OnePlus",
    "868280": "OnePlus", "868302": "OnePlus",
    # Google (Pixel)
    "353141": "Google", "353157": "Google", "353170": "Google", "353189": "Google",
    "353200": "Google", "358245": "Google", "358260": "Google", "358278": "Google",
    "358295": "Google", "358310": "Google",
    # Motorola
    "353490": "Motorola", "353506": "Motorola", "353519": "Motorola",
    "353537": "Motorola", "353550": "Motorola", "353568": "Motorola",
    "355002": "Motorola", "355019": "Motorola", "355037": "Motorola",
    # Nokia / HMD Global
    "358670": "Nokia", "358685": "Nokia", "358697": "Nokia",
    "358710": "Nokia", "358728": "Nokia", "358743": "Nokia",
    "353851": "Nokia", "353863": "Nokia", "353875": "Nokia",
    # Sony / Sony Ericsson
    "353025": "Sony", "353038": "Sony", "353042": "Sony", "353056": "Sony",
    # LG
    "353075": "LG", "353089": "LG", "353093": "LG", "353106": "LG",
    "353113": "LG", "353128": "LG",
    # Honor
    "867240": "Honor", "867258": "Honor", "867273": "Honor", "867291": "Honor",
    "867307": "Honor", "867323": "Honor", "867341": "Honor", "867358": "Honor",
    # Lenovo
    "860370": "Lenovo", "860386": "Lenovo", "860398": "Lenovo",
    "860410": "Lenovo", "860425": "Lenovo", "860441": "Lenovo",
    # ZTE
    "869001": "ZTE", "869018": "ZTE", "869034": "ZTE", "869053": "ZTE",
    "869071": "ZTE", "869089": "ZTE", "869102": "ZTE", "869120": "ZTE",
    # TCL / Alcatel (owned by TCL)
    "358700": "TCL", "358718": "TCL", "358729": "TCL",
    "359005": "Alcatel", "359006": "Alcatel", "359010": "Alcatel",
    "359016": "Alcatel", "359020": "Alcatel", "359026": "Alcatel",
    # Hammer (mPTech, Poland)
    "357780": "Hammer", "357790": "Hammer", "357800": "Hammer",
    # myPhone (Poland)
    "355770": "myPhone", "355773": "myPhone", "355778": "myPhone",
    "355780": "myPhone", "355784": "myPhone",
    # Maxcom (Poland)
    "357580": "Maxcom", "357585": "Maxcom", "357590": "Maxcom",
    # D-Link
    "014460": "D-Link", "014465": "D-Link", "014470": "D-Link",
    # Netgear
    "014700": "Netgear", "014710": "Netgear",
    # TP-Link
    "868500": "TP-Link", "868515": "TP-Link", "868530": "TP-Link",
}

# ── Brand → country of origin mapping ──
_BRAND_COUNTRY: Dict[str, str] = {
    "Apple": "USA",
    "Samsung": "Korea Płd.",
    "Huawei": "Chiny",
    "Xiaomi": "Chiny",
    "OPPO": "Chiny",
    "Vivo": "Chiny",
    "Realme": "Chiny",
    "OnePlus": "Chiny",
    "Google": "USA",
    "Motorola": "USA/Chiny",
    "Nokia": "Finlandia",
    "Sony": "Japonia",
    "LG": "Korea Płd.",
    "Honor": "Chiny",
    "Lenovo": "Chiny",
    "ZTE": "Chiny",
    "TCL": "Chiny",
    "Alcatel": "Chiny (TCL)",
    "Hammer": "Polska",
    "myPhone": "Polska",
    "Maxcom": "Polska",
    "D-Link": "Tajwan",
    "Netgear": "USA",
    "TP-Link": "Chiny",
    "Nothing": "Wielka Brytania",
    "Asus": "Tajwan",
    "HTC": "Tajwan",
    "BlackBerry": "Kanada",
    "Fairphone": "Holandia",
    "CAT": "USA",
}


@dataclass
class DeviceInfo:
    """Device identification result."""

    brand: str = ""
    model: str = ""
    device_type: str = ""  # smartphone, tablet, modem, feature_phone, smartwatch
    tac: str = ""
    country: str = ""          # country of TAC allocation (Reporting Body)
    region: str = ""           # region of TAC allocation
    reporting_body: str = ""   # BABT, PTCRB, CECT, etc.
    brand_country: str = ""    # country of the manufacturer / brand origin
    luhn_computed: bool = False  # True if check digit was computed (not from original)
    original_length: int = 0   # length of IMEI before normalization (14, 15, 16)

    @property
    def display_name(self) -> str:
        """Human-friendly name, e.g. 'Apple iPhone 14 Pro'."""
        parts = [p for p in (self.brand, self.model) if p]
        return " ".join(parts) if parts else ""

    def to_dict(self) -> dict:
        return {
            "brand": self.brand,
            "model": self.model,
            "type": self.device_type,
            "tac": self.tac,
            "display_name": self.display_name,
            "country": self.country,
            "region": self.region,
            "reporting_body": self.reporting_body,
            "brand_country": self.brand_country,
            "luhn_computed": self.luhn_computed,
            "original_length": self.original_length,
        }


def _load_db() -> Dict[str, dict]:
    """Load and merge TAC databases (cached)."""
    global _tac_cache
    if _tac_cache is not None:
        return _tac_cache

    db: Dict[str, dict] = {}

    # Built-in database
    if _BUILTIN_DB.exists():
        try:
            raw = json.loads(_BUILTIN_DB.read_text(encoding="utf-8"))
            for tac, info in raw.items():
                if tac.startswith("_"):
                    continue  # skip metadata keys
                db[tac] = info
            log.debug("Loaded %d TAC entries from built-in database", len(db))
        except Exception as e:
            log.warning("Failed to load TAC database: %s", e)

    # Custom overrides / additions
    if _CUSTOM_DB.exists():
        try:
            custom = json.loads(_CUSTOM_DB.read_text(encoding="utf-8"))
            count = 0
            for tac, info in custom.items():
                if tac.startswith("_"):
                    continue
                db[tac] = info
                count += 1
            log.debug("Loaded %d TAC entries from custom database", count)
        except Exception as e:
            log.warning("Failed to load custom TAC database: %s", e)

    _tac_cache = db
    return db


def _luhn_check_digit(digits_14: str) -> str:
    """Compute the Luhn check digit for a 14-digit IMEI body.

    The Luhn algorithm doubles every second digit (from the right of the
    final 15-digit number, i.e. even-indexed digits of the 14-digit body),
    sums them up, and the check digit makes the total divisible by 10.
    """
    total = 0
    for i, ch in enumerate(digits_14):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return str((10 - (total % 10)) % 10)


def normalize_imei(imei: str) -> str:
    """Normalize an IMEI string.

    - Strips whitespace, dashes, spaces, slashes
    - 14-digit IMEI → appends Luhn check digit to make 15
    - 16-digit IMEISV → truncates to 15 (drops SV byte)
    - Returns empty string if input is not a valid IMEI-like number
    """
    if not imei:
        return ""
    digits = re.sub(r"[^0-9]", "", str(imei).strip())
    if len(digits) == 14:
        digits = digits + _luhn_check_digit(digits)
    elif len(digits) == 16:
        # IMEISV — drop the 2-digit software version, recompute check
        digits = digits[:14] + _luhn_check_digit(digits[:14])
    elif len(digits) != 15:
        return digits  # return as-is (may be partial/invalid)
    return digits


def normalize_imei_ex(imei: str) -> Dict[str, Any]:
    """Extended normalize: returns dict with normalized IMEI + metadata.

    Returns:
        {
            "imei": "...",           # normalized 15-digit IMEI
            "original_length": 14,   # original digit count (14, 15, 16)
            "luhn_computed": True,    # True if check digit was computed
            "check_digit": "7",      # the check digit (computed or original)
        }
    """
    if not imei:
        return {"imei": "", "original_length": 0, "luhn_computed": False, "check_digit": ""}
    digits = re.sub(r"[^0-9]", "", str(imei).strip())
    original_length = len(digits)
    luhn_computed = False
    check_digit = ""

    if original_length == 14:
        check_digit = _luhn_check_digit(digits)
        digits = digits + check_digit
        luhn_computed = True
    elif original_length == 16:
        check_digit = _luhn_check_digit(digits[:14])
        digits = digits[:14] + check_digit
        luhn_computed = True
    elif original_length == 15:
        check_digit = digits[14]
    else:
        return {"imei": digits, "original_length": original_length, "luhn_computed": False, "check_digit": ""}

    return {
        "imei": digits,
        "original_length": original_length,
        "luhn_computed": luhn_computed,
        "check_digit": check_digit,
    }


# Need Any for normalize_imei_ex return type
from typing import Any  # noqa: E402


def validate_imei(imei: str) -> bool:
    """Validate a 15-digit IMEI using the Luhn algorithm.

    Returns True if valid, False otherwise.  Also returns False for
    non-15-digit strings.
    """
    digits = re.sub(r"[^0-9]", "", str(imei).strip())
    if len(digits) != 15:
        return False
    expected = _luhn_check_digit(digits[:14])
    return digits[14] == expected


def extract_tac(imei: str) -> str:
    """Extract the 8-digit TAC from an IMEI string.

    Handles IMEI (14/15 digits), IMEISV (16 digits), and IMEI with
    separators (dashes, spaces).
    """
    if not imei:
        return ""
    digits = re.sub(r"[^0-9]", "", str(imei).strip())
    if len(digits) >= 8:
        return digits[:8]
    return ""


def _get_reporting_body(imei: str) -> Dict[str, str]:
    """Identify the TAC Reporting Body from the first 2 digits of IMEI.

    Returns dict with 'body', 'country', 'region' keys (empty if unknown).
    """
    digits = re.sub(r"[^0-9]", "", str(imei).strip())
    if len(digits) < 2:
        return {"body": "", "country": "", "region": ""}
    prefix2 = digits[:2]
    return _REPORTING_BODIES.get(prefix2, {"body": "", "country": "", "region": ""})


def _get_brand_from_prefix(imei: str) -> str:
    """Try to identify manufacturer from 6-digit TAC prefix.

    This is a fallback when the exact 8-digit TAC is not in the model database.
    Returns brand name or empty string.
    """
    digits = re.sub(r"[^0-9]", "", str(imei).strip())
    if len(digits) < 6:
        return ""
    prefix6 = digits[:6]
    return _MANUFACTURER_PREFIXES.get(prefix6, "")


def lookup_imei(imei: str) -> Optional[DeviceInfo]:
    """Look up device info by IMEI number.

    First tries the exact 8-digit TAC in the model database.
    If not found, falls back to 6-digit prefix for manufacturer identification.
    Always enriches with Reporting Body (country) info from first 2 digits.

    Args:
        imei: IMEI string (14/15/16 digits, may contain separators).

    Returns:
        DeviceInfo if any identification is possible, None only if IMEI is
        too short to extract even 2 digits.
    """
    tac = extract_tac(imei)
    digits = re.sub(r"[^0-9]", "", str(imei).strip())
    if len(digits) < 2:
        return None

    # Reporting Body info (first 2 digits)
    rb = _get_reporting_body(imei)

    # Extended normalization info
    norm = normalize_imei_ex(imei)

    db = _load_db()
    entry = db.get(tac) if tac else None

    if entry:
        # Full match — exact TAC found in model database
        brand = entry.get("brand", "")
        return DeviceInfo(
            brand=brand,
            model=entry.get("model", ""),
            device_type=entry.get("type", ""),
            tac=tac,
            country=rb.get("country", ""),
            region=rb.get("region", ""),
            reporting_body=rb.get("body", ""),
            brand_country=_BRAND_COUNTRY.get(brand, ""),
            luhn_computed=norm.get("luhn_computed", False),
            original_length=norm.get("original_length", 0),
        )

    # Fallback — try 6-digit prefix for manufacturer
    brand = _get_brand_from_prefix(imei)

    # If we have at least brand or country info, return partial DeviceInfo
    if brand or rb.get("country"):
        return DeviceInfo(
            brand=brand,
            model="",
            device_type="",
            tac=tac,
            country=rb.get("country", ""),
            region=rb.get("region", ""),
            reporting_body=rb.get("body", ""),
            brand_country=_BRAND_COUNTRY.get(brand, "") if brand else "",
            luhn_computed=norm.get("luhn_computed", False),
            original_length=norm.get("original_length", 0),
        )

    return None


def lookup_imeis(imeis: List[str]) -> Dict[str, DeviceInfo]:
    """Batch lookup — returns {imei: DeviceInfo} for found entries only."""
    results: Dict[str, DeviceInfo] = {}

    for imei in imeis:
        info = lookup_imei(imei)
        if info:
            results[imei] = info
    return results


def get_db_stats() -> dict:
    """Return database statistics."""
    db = _load_db()
    brands = set()
    types = set()
    for entry in db.values():
        if entry.get("brand"):
            brands.add(entry["brand"])
        if entry.get("type"):
            types.add(entry["type"])
    return {
        "total_entries": len(db),
        "brands": sorted(brands),
        "types": sorted(types),
        "custom_db_exists": _CUSTOM_DB.exists(),
        "manufacturer_prefixes": len(_MANUFACTURER_PREFIXES),
        "reporting_bodies": len(_REPORTING_BODIES),
    }


def reload_db() -> int:
    """Force-reload the TAC database. Returns entry count."""
    global _tac_cache
    _tac_cache = None
    return len(_load_db())
