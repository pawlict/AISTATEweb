"""Global merchant database for transaction auto-categorization.

This module is designed to be shared across parsers, projects, and users.
It provides:
- Comprehensive regex patterns for Polish & international merchants
- Category → risk_level mapping
- Gas station location detection from transaction descriptions
- City name extraction from counterparty strings

Categories defined here complement the risk categories in rules.yaml.
Everyday categories (grocery, fuel, etc.) do NOT increase risk score.
Digital stores and payment operators may carry elevated risk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# CATEGORY METADATA
# ============================================================

@dataclass(frozen=True)
class CategoryMeta:
    """Metadata for a merchant category."""
    display_name: str          # Polish UI label
    display_name_en: str       # English label
    risk_level: str            # none | monitoring | elevated | high
    icon: str = ""             # optional emoji/icon hint for UI


CATEGORY_META: Dict[str, CategoryMeta] = {
    # --- Everyday (no risk) ---
    "grocery":      CategoryMeta("Spożywcze",    "Grocery",        "none",       "🛒"),
    "drugstore":    CategoryMeta("Drogeria",      "Drugstore",      "none",       "🧴"),
    "fuel":         CategoryMeta("Paliwo",        "Fuel",           "none",       "⛽"),
    "hardware":     CategoryMeta("Budowlane",     "Hardware/DIY",   "none",       "🔨"),
    "gastronomy":   CategoryMeta("Gastronomia",   "Gastronomy",     "none",       "🍽️"),
    "clothing":     CategoryMeta("Odzież",        "Clothing",       "none",       "👕"),
    "health":       CategoryMeta("Zdrowie",       "Health",         "none",       "💊"),
    "transport":    CategoryMeta("Transport",     "Transport",      "none",       "🚌"),
    "education":    CategoryMeta("Edukacja",      "Education",      "none",       "📚"),
    "electronics":  CategoryMeta("Elektronika",   "Electronics",    "none",       "📱"),
    "home_garden":  CategoryMeta("Dom i ogród",   "Home & Garden",  "none",       "🏠"),
    "pets":         CategoryMeta("Zwierzęta",     "Pets",           "none",       "🐾"),
    "children":     CategoryMeta("Dzieci",        "Children",       "none",       "🧒"),
    # --- Elevated risk ---
    "digital_store":    CategoryMeta("Sklep cyfrowy",      "Digital Store",      "elevated", "📲"),
    "payment_operator": CategoryMeta("Operator płatności", "Payment Operator",   "monitoring", "💳"),
    # --- P2P ---
    "p2p_transfer": CategoryMeta("Przelew P2P",  "P2P Transfer",   "none",       "📱"),
}


# ============================================================
# MERCHANT PATTERNS (regex, case-insensitive)
# Each list entry is a regex pattern matched against:
#   counterparty + title + raw_text (lowercased)
# ============================================================

MERCHANT_PATTERNS: Dict[str, List[str]] = {

    # ----------------------------------------------------------
    # GROCERY — sklepy spożywcze, supermarkety, delikatesy
    # ----------------------------------------------------------
    "grocery": [
        # === Dyskonty / Supermarkety ===
        r"\bbiedronka\b",
        r"\blidl\b",
        r"\bkaufland\b",
        r"\baldi\b",
        r"\bnetto\b",
        r"\bdino\b",
        r"\bpolomarket\b",
        r"\bstokrotka\b",
        # === Hipermarkety ===
        r"\bauchan\b",
        r"\bcarrefour\b",
        r"\btesco\b",
        r"\be[.\s-]*leclerc\b",
        r"\bintermarche\b",
        r"\bintermarché\b",
        r"\bmakro\b",
        r"\bselgros\b",
        # === Convenience ===
        r"\bżabka\b",
        r"\bzabka\b",
        r"\bfreshmarket\b",
        r"\b1[\s-]*minute\b",
        r"\bspar\b",
        # === Sieci franczyzowe ===
        r"\blewiatan\b",
        r"\bgroszek\b",
        r"\btopaz\b",
        r"\bchata\s*polska\b",
        r"\beuro\s*sklep\b",
        r"\babc\s*(nad?\.?\s*rog|sklep|market)\b",
        r"\bdelikatesy\s*centrum\b",
        r"\bmila\b(?=.*sklep|market)",
        # === Online grocery ===
        r"\bfrisco\b",
        r"\bfrisco\.pl\b",
        r"\blistonic\b",
        r"\bglovo\b.*(?:spo[żz]|market|sklep)",
        # === Keyword patterns (delikatesy + food context) ===
        r"\bdelikates[y]?\b(?=.*(?:rybn|mi[eę]s|spo[żz]|nabia[łl]|warzyw|owoc))",
        r"\bsklep\s*spo[żz]ywcz",
        r"\bmarket\s*spo[żz]ywcz",
        r"\bsupermarket\b",
        r"\bhipermarket\b",
        r"\bsam\s*spo[żz]ywcz",
        r"\bwarzywniak\b",
        r"\bpiekarni[ae]\b",
        r"\bcukierni[ae]\b",
        r"\bmi[eę]sny\b",
        r"\bmi[eę]sarni[ae]\b",
    ],

    # ----------------------------------------------------------
    # DRUGSTORE — drogerie, kosmetyki, perfumerie
    # ----------------------------------------------------------
    "drugstore": [
        r"\brossmann\b",
        r"\bhebe\b",
        r"\bdouglas\b",
        r"\bsuper[\s-]*pharm\b",
        r"\bsuperpharm\b",
        r"\bdrogeria\s*natura\b",
        r"\bnatura\b(?=.*drogeri)",
        r"\bdrogerie\s*polskie\b",
        r"\b[dD][mM]\s*drogerie\b",
        r"\bsephora\b",
        r"\binglot\b",
        r"\bziaja\b",
        r"\bmarionnaud\b",
        r"\bdrogeri[ae]\b",
        r"\bperfumeri[ae]\b",
        r"\bkosmetyki\b",
    ],

    # ----------------------------------------------------------
    # FUEL — stacje benzynowe, paliwo
    # ----------------------------------------------------------
    "fuel": [
        # === Główne sieci ===
        r"\borlen\b",
        r"\bpkn\s*orlen\b",
        r"\blotos\b",
        r"\bbp\b(?=.*stacj|fuel|paliw|benz)",
        r"\bshell\b",
        r"\bcircle\s*k\b",
        r"\bstatoil\b",
        r"\bamic\b(?=.*energ|stacj|fuel|paliw)",
        r"\bamic\s*energy\b",
        # === Inne sieci ===
        r"\bmol\b(?=.*stacj|fuel|paliw|benz)",
        r"\btotal\s*energies\b",
        r"\btotalenergies\b",
        r"\bmoya\b",
        r"\bavia\b(?=.*stacj|fuel|paliw|benz)",
        r"\banwim\b",
        r"\bhuzar\b",
        r"\bintermarche\s*stacj",
        # === Keywords ===
        r"\bstacja\s*(benzy|pali)",
        r"\btankowanie\b",
        r"\bpaliw[oa]\b",
    ],

    # ----------------------------------------------------------
    # HARDWARE — sklepy budowlane, remontowe, narzędzia
    # ----------------------------------------------------------
    "hardware": [
        r"\bcastorama\b",
        r"\bleroy\s*merlin\b",
        r"\bobi\b(?=.*market|sklep|budow|majst)",
        r"\bbricomarche\b",
        r"\bbricoman\b",
        r"\bmerkury\s*market\b",
        r"\bpsb\s*mr[oó]wka\b",
        r"\bmr[oó]wka\b",
        r"\bnomi\b(?=.*market|sklep|budow)",
        r"\bjula\b",
        r"\btop\s*market\b(?=.*budow)",
        # === Keywords ===
        r"\bsklep\s*budowlan",
        r"\bmarket\s*budowlan",
        r"\bmateria[łl]y\s*budowlan",
        r"\bhurtownia\s*budowlan",
    ],

    # ----------------------------------------------------------
    # GASTRONOMY — restauracje, fast-food, stołówki, catering
    # ----------------------------------------------------------
    "gastronomy": [
        # === Fast food ===
        r"\bmcdonald'?s?\b",
        r"\bmcdonalds?\b",
        r"\bkfc\b",
        r"\bburger\s*king\b",
        r"\bsubway\b",
        r"\bpizza\s*hut\b",
        r"\bdomino'?s?\b",
        r"\bnorth\s*fish\b",
        r"\bbobby\s*burger\b",
        r"\bmax\s*burgers?\b",
        r"\bmax\s*premium\s*burgers?\b",
        # === Kawiarnie / bakery ===
        r"\bstarbucks\b",
        r"\bcosta\s*coffee\b",
        r"\bgreen\s*caff[eé]\b",
        r"\bcoffee\s*heaven\b",
        r"\btim\s*hortons\b",
        r"\bżabka\s*caff?[eé]\b",
        # === Sieci restauracyjne (PL) ===
        r"\bsfinks\b",
        r"\bsphinx\b",
        r"\bda\s*grasso\b",
        r"\bpizza\s*dominium\b",
        r"\bpizza\s*portal\b",
        r"\bpyszne\.pl\b",
        r"\bpyszne\b",
        r"\bwolt\b",
        r"\buber\s*eats?\b",
        r"\bglovo\b",
        r"\bbolt\s*food\b",
        # === Keywords ===
        r"\brestauracj[aei]\b",
        r"\bgastronomi[ae]\b",
        r"\bsto[łl][oó]wk[aei]\b",
        r"\bcatering\b",
        r"\bbar\s*mleczny\b",
        r"\bpizzeri[ae]\b",
        r"\bkebab\b",
        r"\bbistro\b",
        r"\bfast\s*food\b",
        r"\bfood\s*court\b",
        r"\bobiad[y]?\b",
        r"\bkawiarni[ae]\b",
    ],

    # ----------------------------------------------------------
    # CLOTHING — odzież, obuwie
    # ----------------------------------------------------------
    "clothing": [
        # === Dyskonty odzieżowe ===
        r"\bpepco\b",
        r"\bccc\b(?=.*obuwie|sklep|but[y]?)",
        r"\bdeichmann\b",
        r"\btk\s*maxx\b",
        r"\bnew\s*yorker\b",
        r"\bprimark\b",
        # === Sieci LPP ===
        r"\breserved\b",
        r"\bhouse\b(?=.*brand|moda|odziez|odzież)",
        r"\bcropp\b",
        r"\bsinsay\b",
        r"\bmohito\b",
        # === Międzynarodowe ===
        r"\bh\s*[&+]\s*m\b",
        r"\bzara\b",
        r"\bpull\s*[&+]\s*bear\b",
        r"\bbershka\b",
        r"\bstradivarius\b",
        r"\bmassimo\s*dutti\b",
        r"\bc\s*[&+]\s*a\b",
        r"\buniqlo\b",
        r"\b4f\b(?=.*sport|sklep|odziez|odzież)",
        # === Obuwie ===
        r"\becco\b(?=.*obuwie|but)",
        r"\bnike\b(?=.*sklep|store)",
        r"\badidas\b(?=.*sklep|store)",
    ],

    # ----------------------------------------------------------
    # HEALTH — apteki, lekarze, przychodnie
    # ----------------------------------------------------------
    "health": [
        # === Apteki ===
        r"\bapteka\b",
        r"\bdoz\b(?=.*aptek|pharma|zdrowi)",
        r"\bdr[\.\s]*max\b",
        r"\bgemini\b(?=.*aptek)",
        r"\bcefarm\b",
        r"\bmelissa\b(?=.*aptek)",
        r"\bsuper[\s-]*pharm\b(?=.*aptek)",
        r"\bpharmac",
        # === Przychodnie / lekarze ===
        r"\bprzychodnia\b",
        r"\bgabinet\s*lekarsk",
        r"\bstomatolog",
        r"\bdentysta\b",
        r"\bokulista\b",
        r"\bortopeda\b",
        r"\bginekolog",
        r"\bdermatolog",
        r"\blaboratorium\b(?=.*medycz|diagno|analiz)",
        r"\bdiagnostyk[ai]\b",
        r"\brehabilitac",
        r"\bfizjoterap",
        r"\boptyk\b",
        r"\bsalwa\s*optyk",
        # === Platformy telemedyczne ===
        r"\bhalodoktor\b",
        r"\bteleporada\b",
        r"\btelekonsultacj",
    ],

    # ----------------------------------------------------------
    # TRANSPORT — komunikacja, parkowanie, taksówki
    # ----------------------------------------------------------
    "transport": [
        # === Ride-hailing ===
        r"\bbolt\b(?!.*food)",
        r"\buber\b(?!.*eats?)",
        r"\bfree\s*now\b",
        r"\btaksi\b",
        r"\btaks[oó]wk[aei]\b",
        # === Kolej ===
        r"\bpkp\b",
        r"\bpolregio\b",
        r"\bintercity\b",
        r"\bkoleo\b",
        r"\bleo\s*express\b",
        # === Autobusy ===
        r"\bflixbus\b",
        r"\bpolski\s*bus\b",
        r"\bsindbad\b",
        # === Komunikacja miejska ===
        r"\bmpk\b",
        r"\bztm\b",
        r"\bskm\b",
        r"\bkzk\s*gop\b",
        r"\bjakdojade\b",
        r"\bbilet\s*komunikac",
        r"\bkomunikacj[aei]\s*miejsk",
        # === Parking ===
        r"\bparking\b",
        r"\bskycash\b(?=.*park)",
        r"\bmobiparking\b",
        r"\b4wheels\b",
        # === Lotnicze ===
        r"\bwizzair\b",
        r"\bwizz\s*air\b",
        r"\bryanair\b",
        r"\blot\b(?=.*bilet|samolot|airlines)",
        r"\beasyjet\b",
    ],

    # ----------------------------------------------------------
    # ELECTRONICS — elektronika, RTV/AGD
    # ----------------------------------------------------------
    "electronics": [
        r"\bmedia\s*expert\b",
        r"\bmediaexpert\b",
        r"\bmedia\s*markt\b",
        r"\bmediamarkt\b",
        r"\brtv\s*euro\s*agd\b",
        r"\beuroagd\b",
        r"\bkomputronik\b",
        r"\bx[\s-]*kom\b",
        r"\bmorele\.net\b",
        r"\bmorele\b(?=.*sklep|elektro)",
        r"\bneonet\b",
        r"\bsamsung\b(?=.*sklep|store|brand)",
        r"\bapple\s*store\b",
        r"\bhuawei\b(?=.*store|sklep)",
        r"\bmi[\s-]*store\b",
        r"\bal\.to\b",
        r"\balto\b(?=.*sklep|elektro)",
        r"\beuro\s*com\b",
    ],

    # ----------------------------------------------------------
    # HOME & GARDEN — dom, ogród, wyposażenie
    # ----------------------------------------------------------
    "home_garden": [
        r"\bikea\b",
        r"\bjysk\b",
        r"\bagata\s*meble\b",
        r"\bblack\s*red\s*white\b",
        r"\bbrw\b(?=.*meble|sklep)",
        r"\bkomfort\b(?=.*sklep|meble|wyposaz|wystroj)",
        r"\bdecathlon\b",
        r"\baction\b(?=.*sklep|market|dom)",
        r"\btedi\b(?=.*sklep|dom)",
        r"\bpepco\s*home\b",
        r"\bkik\b(?=.*sklep|dom|tekstyl)",
        r"\bhomla\b",
        r"\bempiria\b(?=.*mebl)",
    ],

    # ----------------------------------------------------------
    # PETS — zwierzęta
    # ----------------------------------------------------------
    "pets": [
        r"\bmaxi\s*zoo\b",
        r"\bkakadu\b(?=.*sklep|zoo|zwierz)",
        r"\bzoo\s*market\b",
        r"\bzoolove\b",
        r"\bzoologiczn",
        r"\bsklep\s*zoolog",
        r"\bweterynar",
        r"\bweterynarz\b",
        r"\bklinika\s*zwierz",
    ],

    # ----------------------------------------------------------
    # CHILDREN — dzieci, zabawki
    # ----------------------------------------------------------
    "children": [
        r"\bsmyk\b",
        r"\bempik\b",
        r"\btoysrus\b",
        r"\btoys[\s\"]*r[\s\"]*us\b",
        r"\bsklep\s*z\s*zabawk",
        r"\bzabawki\b",
        r"\bprzedszko[lł][eę]\b",
        r"\b[żz][łl]ob[eę]k\b",
    ],

    # ----------------------------------------------------------
    # EDUCATION — szkoły, kursy
    # ----------------------------------------------------------
    "education": [
        r"\buczelni[ae]\b",
        r"\buniwersytet\b",
        r"\bpolitechnika\b",
        r"\bszko[łl][aey]\b",
        r"\bkurs\b(?=.*j[eę]zyk|online|programo)",
        r"\budemy\b",
        r"\bcoursera\b",
        r"\bszkol?eni[ae]\b",
        r"\bwyk[łl]ad\b",
    ],

    # ----------------------------------------------------------
    # DIGITAL STORES — sklepy cyfrowe (elevated risk in AML)
    # Google Play, Apple Store, Steam, etc.
    # ----------------------------------------------------------
    "digital_store": [
        # === App stores ===
        r"\bgoogle\s*play\b",
        r"\bgoogle\s*\*",  # Google *SERVICE transactions
        r"\bplay\s*store\b",
        r"google\s*(cloud|one|storage|workspace|ads)",
        r"\bapple\.com\b",
        r"\bitunes\b",
        r"\bapp\s*store\b",
        r"\bapple\s*(music|tv|arcade|icloud)",
        # === Gaming platforms ===
        r"\bsteam\b(?=.*game|store|wallet|purchase|powered)",
        r"\bsteampowered\b",
        r"\bepic\s*games?\b",
        r"\bplaystation\s*(store|network|plus|ps\s*plus)",
        r"\bpsn\b",
        r"\bxbox\b(?=.*store|game\s*pass|live|microsoft)",
        r"\bnintendo\s*(eshop|switch\s*online|store)",
        r"\bgog\.com\b",
        r"\bhumble\s*bundle\b",
        r"\bea\b(?=.*games?|sports?|origin)",
        r"\belectronic\s*arts\b",
        r"\broblox\b",
        r"\bmojang\b",
        # === In-app purchases / game credits ===
        r"\bsupercell\b",
        r"\bgarena\b",
        r"\bmihoyo\b",
        r"\bhoyoverse\b",
        r"\btencent\b",
    ],

    # ----------------------------------------------------------
    # PAYMENT OPERATORS — operatorzy płatności (monitoring)
    # Zen, PayU, etc. — same w sobie nie są podejrzane,
    # ale w kontekście AML mogą być wykorzystywane do ukrywania
    # ----------------------------------------------------------
    "payment_operator": [
        r"\bzen\.com\b",
        r"\bzen\b(?=.*pay|card|kart|p[łl]at)",
        r"\bpayu\b",
        r"\bprzelewy\s*24\b",
        r"\bp24\b(?=.*p[łl]at|przele|pay)",
        r"\btpay\b",
        r"\bdotpay\b",
        r"\bpaypal\b",
        r"\bstripe\b(?=.*pay|p[łl]at|charge)",
        r"\badyen\b",
        r"\bklarna\b",
        r"\bpaysafe\b(?=.*card|kart|pay)",
        r"\bpaysafecard\b",
        r"\bmangopay\b",
        r"\bimoje\b",
        r"\bbluemedia\b",
        r"\bblue\s*media\b",
    ],

    # ----------------------------------------------------------
    # P2P TRANSFERS — przelewy na telefon, BLIK P2P
    # ----------------------------------------------------------
    "p2p_transfer": [
        r"\bprzelew\s*na\s*telefon\b",
        r"\bblik\s*p2p\b",
        r"\bp\.blik\b",
        r"\bblik\b.*(?:na\s*telefon|p2p|prywat)",
        r"\btransfer.*(?:na\s*numer|na\s*tel)",
    ],
}


# ============================================================
# GAS STATION LOCATION DETECTION
# ============================================================

# Common Polish fuel station brands with known naming patterns
# Transaction descriptions often include city: "ORLEN LODZ" or "BP KRAKOW"
_FUEL_BRANDS = [
    "orlen", "lotos", "bp", "shell", "circle k", "statoil",
    "amic", "mol", "total", "moya", "avia", "anwim", "huzar",
]

# Top 100+ Polish cities for location extraction
POLISH_CITIES = {
    # Województwo mazowieckie
    "warszawa", "radom", "płock", "siedlce", "ostrołęka", "pruszków",
    "legionowo", "otwock", "piaseczno", "wołomin", "mińsk mazowiecki",
    # Województwo małopolskie
    "kraków", "krakow", "tarnów", "tarnow", "nowy sącz", "nowy sacz",
    "chrzanów", "chrzanow", "oświęcim", "oswiecim", "olkusz", "bochnia",
    "wadowice", "myślenice", "myslenice", "zakopane",
    # Województwo śląskie
    "katowice", "częstochowa", "czestochowa", "sosnowiec", "gliwice",
    "zabrze", "bytom", "ruda śląska", "ruda slaska", "rybnik", "tychy",
    "dąbrowa górnicza", "dabrowa gornicza", "bielsko-biała", "bielsko biala",
    "jaworzno", "mysłowice", "myslowice", "siemianowice", "chorzów",
    "chorzow", "mikołów", "mikolow", "żory", "zory", "cieszyn",
    # Województwo dolnośląskie
    "wrocław", "wroclaw", "wałbrzych", "walbrzych", "legnica", "jelenia góra",
    "jelenia gora", "lubin", "głogów", "glogow", "świdnica", "swidnica",
    "bolesławiec", "boleslawiec", "oleśnica", "olesnica",
    # Województwo wielkopolskie
    "poznań", "poznan", "kalisz", "konin", "piła", "pila", "ostrów wielkopolski",
    "ostrow wielkopolski", "gniezno", "leszno", "turek", "śrem", "srem",
    "swarzędz", "swarzedz", "luboń", "lubon",
    # Województwo łódzkie
    "łódź", "lodz", "piotrków trybunalski", "piotrkow trybunalski",
    "pabianice", "zgierz", "tomaszów mazowiecki", "tomaszow mazowiecki",
    "bełchatów", "belchatow", "skierniewice", "kutno", "radomsko",
    "sieradz", "zduńska wola", "zdunska wola", "łowicz", "lowicz",
    # Województwo pomorskie
    "gdańsk", "gdansk", "gdynia", "sopot", "słupsk", "slupsk",
    "tczew", "starogard gdański", "starogard gdanski", "wejherowo",
    "rumia", "reda", "pruszcz gdański", "pruszcz gdanski",
    # Województwo lubelskie
    "lublin", "chełm", "chelm", "zamość", "zamosc", "biała podlaska",
    "biala podlaska", "puławy", "pulawy", "kraśnik", "krasnik",
    "świdnik", "swidnik", "łuków", "lukow",
    # Województwo podkarpackie
    "rzeszów", "rzeszow", "przemyśl", "przemysl", "stalowa wola",
    "mielec", "tarnobrzeg", "krosno", "dębica", "debica",
    "sanok", "jasło", "jaslo", "łańcut", "lancut",
    # Województwo warmińsko-mazurskie
    "olsztyn", "elbląg", "elblag", "ełk", "elk", "ostróda", "ostroda",
    "iława", "ilawa", "giżycko", "gizycko", "kętrzyn", "ketrzyn",
    # Województwo zachodniopomorskie
    "szczecin", "koszalin", "stargard", "kołobrzeg", "kolobrzeg",
    "świnoujście", "swinoujscie", "police",
    # Województwo podlaskie
    "białystok", "bialystok", "suwałki", "suwalki", "łomża", "lomza",
    "augustów", "augustow",
    # Województwo świętokrzyskie
    "kielce", "ostrowiec świętokrzyski", "ostrowiec swietokrzyski",
    "starachowice", "skarżysko-kamienna", "skarzysko kamienna",
    "sandomierz", "busko-zdrój", "busko zdroj",
    # Województwo lubuskie
    "zielona góra", "zielona gora", "gorzów wielkopolski",
    "gorzow wielkopolski", "nowa sól", "nowa sol",
    "żary", "zary", "żagań", "zagan",
    # Województwo opolskie
    "opole", "kędzierzyn-koźle", "kedzierzyn kozle",
    "nysa", "brzeg", "kluczbork",
    # Województwo kujawsko-pomorskie
    "bydgoszcz", "toruń", "torun", "włocławek", "wloclawek",
    "grudziądz", "grudziadz", "inowrocław", "inowroclaw",
    # Trójmiasto alias
    "trójmiasto", "trojmiasto",
}


def detect_fuel_location(counterparty: str, title: str = "") -> Optional[str]:
    """Try to extract city name from a fuel station transaction.

    Returns city name if found, None otherwise.
    Works best with transaction descriptions like "ORLEN LODZ", "BP 1234 KRAKOW".
    """
    text = f"{counterparty} {title}".lower()

    # Check if it's a fuel station transaction
    is_fuel = False
    for brand in _FUEL_BRANDS:
        if brand in text:
            is_fuel = True
            break
    if not is_fuel:
        return None

    # Try to find a city name in the text
    for city in POLISH_CITIES:
        # Use word boundary matching for city names
        pattern = r"\b" + re.escape(city) + r"\b"
        if re.search(pattern, text, re.I):
            # Return the canonical (first) form of the city
            return city.title()

    return None


def detect_merchant_location(counterparty: str, title: str = "") -> Optional[str]:
    """Try to extract city name from any merchant transaction.

    Returns city name if found, None otherwise.
    """
    text = f"{counterparty} {title}".lower()

    for city in sorted(POLISH_CITIES, key=len, reverse=True):
        pattern = r"\b" + re.escape(city) + r"\b"
        if re.search(pattern, text, re.I):
            return city.title()

    return None


# ============================================================
# CLASSIFICATION API
# ============================================================

# Compiled patterns cache
_compiled_merchant_rules: Optional[List[Tuple[str, re.Pattern]]] = None


def _ensure_compiled():
    global _compiled_merchant_rules
    if _compiled_merchant_rules is not None:
        return
    _compiled_merchant_rules = []
    for category, patterns in MERCHANT_PATTERNS.items():
        for pat in patterns:
            try:
                _compiled_merchant_rules.append((category, re.compile(pat, re.I)))
            except re.error:
                pass


def classify_merchant(counterparty: str, title: str = "", raw_text: str = "") -> Optional[str]:
    """Classify a transaction by matching merchant patterns.

    Returns category name (e.g. "grocery", "fuel") or None if no match.
    First match wins — patterns are ordered by specificity.
    """
    _ensure_compiled()
    search = f"{counterparty} {title} {raw_text}".lower()

    for category, pattern in _compiled_merchant_rules:
        if pattern.search(search):
            return category
    return None


def classify_merchant_detailed(
    counterparty: str, title: str = "", raw_text: str = ""
) -> Optional[Dict[str, Any]]:
    """Classify a merchant and return detailed info.

    Returns dict with category, display_name, risk_level, location, etc.
    """
    category = classify_merchant(counterparty, title, raw_text)
    if category is None:
        return None

    meta = CATEGORY_META.get(category)
    location = None
    if category == "fuel":
        location = detect_fuel_location(counterparty, title)
    elif location is None:
        location = detect_merchant_location(counterparty, title)

    return {
        "category": category,
        "subcategory": f"everyday:{category}" if meta and meta.risk_level == "none" else category,
        "display_name": meta.display_name if meta else category,
        "display_name_en": meta.display_name_en if meta else category,
        "risk_level": meta.risk_level if meta else "none",
        "icon": meta.icon if meta else "",
        "location": location,
    }


def get_all_categories() -> Dict[str, Dict[str, str]]:
    """Return all category metadata for UI display."""
    return {
        k: {
            "display_name": v.display_name,
            "display_name_en": v.display_name_en,
            "risk_level": v.risk_level,
            "icon": v.icon,
        }
        for k, v in CATEGORY_META.items()
    }
