import sys, re, json, concurrent.futures as cf
from urllib.request import Request, urlopen
HOSTS = ["wd1","wd2","wd3","wd4","wd5","wd6","wd10","wd12","wd101","wd102","wd103","wd105","wd107","wd108","wd501","wd502","wd503"]
def robots(tenant, h):
    try:
        b = urlopen(Request(f"https://{tenant}.{h}.myworkdayjobs.com/robots.txt", headers={"User-Agent":"Mozilla/5.0"}), timeout=12).read().decode()
        return re.findall(r"myworkdayjobs\.com/([^/\s]+)/siteMap", b)
    except Exception:
        return []
tenants = sys.argv[1].split(",")
jobs = [(t,h) for t in tenants for h in HOSTS]
with cf.ThreadPoolExecutor(48) as ex:
    res = list(ex.map(lambda j: (j, robots(*j)), jobs))
out = {}
for (t,h), s in res:
    if s: out[f"{t}.{h}"] = s; print(f"{t}.{h}: {s}")
json.dump(out, open("workday_found.json","a")); open("workday_found.json","a").write("\n")
