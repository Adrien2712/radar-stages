"""Decide whether a posting is an internship, whether it matches the target
(M&A / PE / private debt / spring weeks...), and tag cycle + region.

Levels:
  "A" = cible -> instant Telegram notification
  "B" = other internship/programme at a tracked firm -> dashboard + morning digest
  None = not an internship -> ignored
"""
import re

I = re.I

INTERNSHIP = re.compile(
    r"\bintern(ship)?s?\b|(?<!early )(?<!early-)(?<!late )(?<!growth )(?<!later )\bstages?\b|stagiaire"
    r"|summer (analyst|associate|intern|program|programme|placement)"
    r"|spring (week|insights?|intern|internship|program|programme|analyst)|insight (day|days|week|event|program|programme|series|evening)|off[- ]?cycle|\bseasonal\b|(?<!private )placement"
    r"|working student|werkstudent|praktik|c[ée]sure|gap year|discovery (day|week|program)|vacation scheme"
    r"|\bvie\b|v\.i\.e|volontariat international|work experience|early insight|pre-?university", I)

EXCLUDED_TYPE = re.compile(
    r"alternan(ce|t)|apprenti|work[- ]study|contrat pro|high school|lyc[ée]e|\bph\.?d\b|doctora|cifre|th[eè]se"
    r"|\bmba\b|summer associate|^\s*closed\b|\bclosed:|full[- ]time (analyst|associate|program)|interns only|\bnew analyst\b", I)  # Summer Associate = MBA programmes

TARGET = re.compile(
    r"m ?& ?a\b|m&amp;a|mergers|acquisition|fusions|investment bank|banque d.affaires|banque d.investissement|\bibd\b|\bgib\b"
    r"|corporate finance|finance d.entreprise|leveraged finance|lev ?fin|advisory|private equity|capital[- ]investissement"
    r"|buyout|\blbo\b|growth equity|venture|private (credit|debt|markets|capital|investment)|dette priv|direct lending"
    r"|credit (investing|investment|opportunit|fund)|special situations|restructuring|debt advisory|\becm\b|\bdcm\b"
    r"|capital markets|origination|coverage|transaction services|due diligence|valuation|[ée]valuation|infrastructure"
    r"|real estate|immobilier|real assets|investment (team|professional|analyst|banking|associate)|investissement"
    r"|principal investing|merchant banking|structured finance|financements? structur|project finance|acquisition finance"
    r"|corporate development|secondar|co-?invest|investment management|deal", I)

NON_TARGET = re.compile(
    r"software|developer|d[ée]veloppeu|engineer|ing[ée]nieur|technolog|cyber|data scien|data engineer|devops|cloud"
    r"|human resources|\bhr\b|ressources humaines|recruit|talent acquisition|marketing|communication|graphic|design|legal"
    r"|juriste|juridique|compliance|conformit|internal audit|audit interne|operations|op[ée]rations|middle office"
    r"|back office|accounting|comptab|\btax\b|fiscal|facilities|wealth|retail bank|branch|teller|client service"
    r"|customer|call cent|payroll|procurement|achats|supply chain|administrative|assistant|architect|support|project manag"
    r"|projet|product|actuar|audit|risk|risque|contr[ôo]l|esg|fund admin|administration|client|intelligence artificielle"
    r"|\bai\b|data|analytics|quant|structured products|produits structur|sales|trading|research|recherche|repo\b"
    r"|money market|treasury|tr[ée]sorerie|kyc|aml|fraud|insurance|actuariat|consultant|droit|gouvernance|appels? d.offres"
    r"|tender|patrimo|gestion priv|private bank|gestion d.actifs|asset management|g[ée]rant|affaires publiques|public affairs"
    r"|government|fund finance|fund accounting|fund operations|investor services|reporting|finance team|finance department"
    r"|contr[ôo]le de gestion|controlling|office manag|events?\b|sustainab|rse\b|csr\b", I)

TECH = re.compile(r"technolog|engineer|software|developer|d[ée]veloppeu|\bdata\b|cyber|\bIT\b|devops|cloud", I)

EVENT = re.compile(r"coffee chat|webinar|networking|info(rmation)? session|open (day|house)|intro(duction)? to|workshop|meet (the|us)"
                   r"|reception|happy hour|career fair|university of|\bupenn\b|campus event|virtual event", I)

STRONG_TARGET = re.compile(r"m ?& ?a\b|mergers|private equity|investment bank|leveraged finance|restructuring|private (credit|debt)|corporate finance|\bibd\b", I)

SPRING = re.compile(r"spring (week|insights?( (event|day|days|programme|program|week|series))?|intern|internship|program|programme|analyst)|insight (day|days|week|event|program|programme|series|evening)|early insight|discovery (day|week|program)"
                    r"|work experience|pre-?university", I)

# At these firms almost every internship is deal-related, so any non-support internship counts as target.
TARGET_FIRM_CATEGORIES = {"Boutique M&A", "M&A Mid-Market", "Private Equity", "Dette Privée", "Infra / Real Assets"}

CYCLES = [
    ("Spring / Insight", SPRING),
    ("Off-cycle", re.compile(r"off[- ]?cycle|seasonal|6[- ]?month|six[- ]month|c[ée]sure|gap year|\bstage\b|stagiaire|1[2-9] ?month", I)),
    ("Summer", re.compile(r"summer", I)),
    ("VIE", re.compile(r"\bvie\b|v\.i\.e|volontariat international", I)),
]

REGIONS = [
    ("Paris / France", r"paris|france|lyon|nantes|lille|bordeaux|marseille|toulouse|nice|neuilly|courbevoie|la d[ée]fense|montrouge"),
    ("London / UK", r"london|londres|united kingdom|\buk\b|england|edinburgh|manchester|birmingham|glasgow"),
    ("New York / US", r"new york|nyc|united states|\busa\b|\bus\b|chicago|san francisco|boston|los angeles|houston|dallas|charlotte|menlo park|greenwich|miami|atlanta|washington"),
    ("Suisse", r"gen[eè]v|geneva|zurich|z[üu]rich|lausanne|switzerland|suisse|baar|zug|lugano"),
    ("Corée / Asie", r"seoul|s[ée]oul|korea|cor[ée]e|hong kong|singapore|singapour|tokyo|japan|shanghai|beijing|mumbai|sydney|melbourne"),
    ("Moyen-Orient", r"dubai|abu dhabi|riyadh|doha|qatar|saudi|uae|emirates"),
    ("Europe (autre)", r"frankfurt|francfort|munich|m[üu]nchen|berlin|germany|madrid|barcelona|milan|rome|amsterdam|brussels|bruxelles|luxembourg|stockholm|oslo|copenhagen|dublin|warsaw|lisbon|vienna"),
]
REGIONS = [(name, re.compile(rx, I)) for name, rx in REGIONS]


def classify(title, category, location=""):
    """Return (level, cycle, region)."""
    t = title or ""
    if not INTERNSHIP.search(t) or EXCLUDED_TYPE.search(t):
        return None, None, None
    years = set(re.findall(r"20[2-3]\d", t))
    if years and max(years) < "2026":
        return None, None, None
    core = SPRING.sub(" ", t)  # "Insight Event" is a programme name, not an events job
    off_target = NON_TARGET.search(core) or re.search(r"\bIT\b", core)
    if off_target and (not STRONG_TARGET.search(t) or TECH.search(t)):
        level = "B"
    elif TARGET.search(t) or SPRING.search(t) or category in TARGET_FIRM_CATEGORIES:
        level = "A"
    else:
        level = "B"
    if EVENT.search(t) and not SPRING.search(t):  # recruiting events: dashboard only
        level = "B"
    if years and not years & {"2027", "2028"}:  # e.g. "2026 Summer Analyst" -> past cycle
        level = "B"
    cycle = next((name for name, rx in CYCLES if rx.search(t)), "Stage")
    region = next((name for name, rx in REGIONS if rx.search(location or "")), None) \
        or next((name for name, rx in REGIONS if rx.search(t)), "Autre / NC")
    return level, cycle, region


COUNTRIES = [
    ("France", r"paris|france|lyon|nantes|lille|bordeaux|marseille|toulouse|\bnice\b|neuilly|courbevoie|la d[ée]fense|puteaux|levallois|montrouge|rennes|strasbourg|[îi]le-de-france"),
    ("Royaume-Uni", r"london|londres|united kingdom|\buk\b|\bgb\b|england|scotland|edinburgh|manchester|birmingham|glasgow|bournemouth|leeds|bristol|canary wharf"),
    ("États-Unis", r"new york|\bnyc\b|united states|\busa\b|\bus\b|chicago|san francisco|boston|los angeles|houston|dallas|charlotte|menlo park|greenwich|miami|atlanta|washington|jersey city|wilmington|denver|palo alto|seattle|minneapolis|st\.? louis|richmond|philadelphia|austin|baltimore|nashville|tennessee|saratoga|, (ny|ca|tx|il|ma|nc|ga|fl|co|ct|nj|pa|de|va|wa|mn|mo|tn|oh|wi|az|ut)\b"),
    ("Suisse", r"gen[eè]v|geneva|zurich|z[üu]rich|lausanne|switzerland|suisse|\bbaar\b|\bzug\b|lugano|basel|b[âa]le|nyon"),
    ("Allemagne", r"frankfurt|francfort|munich|m[üu]nchen|berlin|germany|deutschland|hamburg|d[üu]sseldorf|cologne|k[öo]ln|stuttgart|taunus"),
    ("Luxembourg", r"luxembourg|luxemburg"),
    ("Belgique", r"brussels|bruxelles|belgium|belgique|antwerp"),
    ("Pays-Bas", r"amsterdam|netherlands|rotterdam|the hague|\bnl\b"),
    ("Espagne", r"madrid|barcelona|spain|espagne"),
    ("Italie", r"milan|milano|rome|roma|italy|italie|medelan"),
    ("Irlande", r"dublin|ireland|irlande"),
    ("Suède", r"stockholm|sweden|su[èe]de"),
    ("Norvège", r"\boslo\b|norway"),
    ("Danemark", r"copenhagen|denmark"),
    ("Pologne", r"warsaw|krak[óo]w|poland|pologne"),
    ("Portugal", r"lisbon|lisboa|porto|portugal"),
    ("Autriche", r"vienna|wien|austria"),
    ("Grèce", r"athens|greece|gr[èe]ce"),
    ("Corée du Sud", r"seoul|s[ée]oul|korea|cor[ée]e"),
    ("Hong Kong", r"hong kong|kowloon"),
    ("Singapour", r"singapore|singapour"),
    ("Japon", r"tokyo|japan|japon|osaka"),
    ("Chine", r"shanghai|beijing|shenzhen|china|chine"),
    ("Inde", r"mumbai|bengaluru|bangalore|india|inde|hyderabad|pune|delhi|gurgaon|gurugram|chennai"),
    ("Australie", r"sydney|melbourne|australia|australie|brisbane|perth"),
    ("Canada", r"toronto|montr[ée]al|vancouver|canada|calgary|ontario|qu[ée]bec"),
    ("Émirats arabes unis", r"dubai|duba[iï]|abu dhabi|\buae\b|emirates"),
    ("Arabie saoudite", r"riyadh|saudi"),
    ("Qatar", r"doha|qatar"),
    ("Brésil", r"s[ãa]o paulo|brazil|br[ée]sil|rio de janeiro"),
    ("Mexique", r"mexico|mexique"),
    ("Philippines", r"manila|philippines"),
    ("Taïwan", r"taipei|taiwan"),
    ("Kazakhstan", r"almaty|kazakhstan"),
]
COUNTRIES = [(name, re.compile(rx, I)) for name, rx in COUNTRIES]


def country(location, title=""):
    """First country mentioned in the location (else in the title)."""
    for text in (location or "", title or ""):
        best = None
        for name, rx in COUNTRIES:
            m = rx.search(text)
            if m and (best is None or m.start() < best[1]):
                best = (name, m.start())
        if best:
            return best[0]
        if re.search(r"\d+ locations|multiple locations|various", text, I):
            return "Plusieurs pays"
    return ""
