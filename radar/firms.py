"""Recognise a tracked firm from any spelling ("JPMorgan Chase & Co.", "Rothschild & Co.", "EY-Parthenon"...)."""
import re
import unicodedata

ALIASES = {
    "J.P. Morgan": ["jpmorgan", "jpmorganchase", "jpmorganchaseco"],
    "Bank of America": ["bankofamerica", "bofa", "bofasecurities", "merrilllynch"],
    "Citi": ["citigroup", "citibank", "citi"],
    "Société Générale": ["societegenerale", "sgcib"],
    "Crédit Agricole CIB": ["creditagricolecib", "creditagricole", "cacib"],
    "BNP Paribas": ["bnpparibas"],
    "Natixis CIB": ["natixis"],
    "Rothschild & Co": ["rothschild"],
    "EY": ["ey", "ernstyoung", "eyparthenon"],
    "PwC": ["pwc", "pricewaterhousecoopers"],
    "Edmond de Rothschild Corporate Finance": ["edmondderothschild"],
    "RBC Capital Markets": ["rbccapitalmarkets", "rbc", "royalbankofcanada"],
    "Macquarie": ["macquarie"],
    "Mizuho": ["mizuho"],
    "MUFG": ["mufg"],
    "UBS": ["ubs"],
    "HSBC": ["hsbc"],
    "Santander CIB": ["santander"],
    "TD Securities": ["tdsecurities", "td"],
    "Deutsche Bank": ["deutschebank"],
}
STOP = r"\b(and|co|the|group|groupe|sa|sas|inc|llc|ltd|limited|plc|lp|llp|ag|gmbh|se|nv|bv|corp|corporation)\b"


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return s


def compact(s):
    s = re.sub(r"\(.*?\)", " ", norm(s)).replace("&", " ")
    return re.sub(r"[^a-z0-9]", "", re.sub(STOP, " ", s))


GENERIC = {"partners", "capital", "group", "advisors", "advisory", "management", "investment", "investments", "bank", "securities",
           "financial", "finance", "global", "international", "holdings", "asset", "equity", "credit"}


def key_of(name):
    """Key used to recognise a firm. "Partners Group" -> "partnersgroup" (a lone generic word is too vague)."""
    words = [w for w in re.split(r"[^a-z0-9]+", re.sub(STOP, " ", re.sub(r"\(.*?\)", " ", norm(name)).replace("&", " "))) if w]
    if not words or all(w in GENERIC for w in words):
        return re.sub(r"[^a-z0-9]", "", re.sub(r"\(.*?\)", " ", norm(name)))
    return "".join(words)


class FirmMatcher:
    def __init__(self, names):
        keys = []
        for name in dict.fromkeys(names):
            for k in ALIASES.get(name, [key_of(name)]):
                if len(k) >= 2:
                    keys.append((k, name))
        self.keys = sorted(keys, key=lambda x: -len(x[0]))  # longest (most specific) first

    def match(self, company):
        """The company must START with the firm's name ("Lazard Frères" -> Lazard, but "Guardian Life" is not Ardian)."""
        comp = compact(company)
        full = re.sub(r"[^a-z0-9]", "", re.sub(r"\(.*?\)", " ", norm(company)))  # without removing "group", "co"...
        words = re.split(r"[^a-z0-9]+", norm(company))
        for k, name in self.keys:
            if len(k) < 5:
                if comp == k or (words and words[0] == k):
                    return name
            elif comp.startswith(k) or full.startswith(k):
                return name
        return ""
