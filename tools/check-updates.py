#!/usr/bin/env python3
# check-updates.py: is the store up to date with its games' releases?
#
#   tools/check-updates.py                 the report; changes nothing
#   tools/check-updates.py --apply ID...   take the new release of those games
#                                          (or --apply all): download each
#                                          package to ~/store-vpks, point its
#                                          games.list line at it and its tag,
#                                          and run make-index.py
#
# For each line of games.list it finds, on the game's repository, the newest
# published release (not a draft or a pre-release) carrying a package of the
# same id (<id>-<version>.vpk), and reports:
#   UPDATE     a newer release than the store's
#   CHANGED    the store's own release file was replaced since (its SHA-256
#              is not the store's): the index would send a wrong checksum
#   MISSING    the store's release or its file is gone
#   ok         up to date
# Then the packages released lately (60 days) on the same accounts that the
# store does not list: candidates, for information.
#
# GitHub allows 60 requests an hour without a token; with GITHUB_TOKEN set,
# 5000.
import datetime, hashlib, json, os, re, subprocess, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST = os.path.join(ROOT, "games.list")
INDEX = os.path.join(ROOT, "games.json")
STORE_VPKS = os.path.expanduser("~/store-vpks")
RECENT_DAYS = 60


def api(path):
    req = urllib.request.Request("https://api.github.com" + path,
                                 headers={"Accept": "application/vnd.github+json",
                                          "User-Agent": "vectorpie-games-check"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        sys.exit("GitHub: %s %s (%s)" % (e.code, e.reason, path))


def entries():
    """games.list's lines: (line number, path, repo, tag, license, id)."""
    out = []
    for n, line in enumerate(open(LIST)):
        body = line.split("#", 1)[0].strip()
        if not body:
            continue
        path, repo, tag, license_ = body.split()
        m = re.match(r"(.+)-([0-9][^-]*)\.vpk$", os.path.basename(path))
        if not m:
            sys.exit("games.list line %d: %s is not <id>-<version>.vpk" % (n + 1, path))
        out.append({"line": n, "path": path, "repo": repo, "tag": tag, "license": license_,
                    "id": m.group(1), "version": m.group(2)})
    return out


def owner_repo(url):
    m = re.match(r"https://github\.com/([^/]+)/([^/]+?)/?$", url)
    return (m.group(1), m.group(2)) if m else (None, None)


def vpk_of(release, game_id):
    for a in release.get("assets", []):
        if re.match(re.escape(game_id) + r"-[0-9][^-]*\.vpk$", a["name"]):
            return a
    return None


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check():
    index = {g["id"]: g for g in json.load(open(INDEX))["games"]}
    games = entries()
    listed = {g["id"] for g in games}
    results = []
    for g in games:
        owner, name = owner_repo(g["repo"])
        releases = api("/repos/%s/%s/releases?per_page=30" % (owner, name)) or []
        published = [r for r in releases if not r["draft"] and not r["prerelease"]]
        mine = next((r for r in published if r["tag_name"] == g["tag"]), None)
        newest = None
        for r in sorted(published, key=lambda r: r["published_at"], reverse=True):
            a = vpk_of(r, g["id"])
            if a:
                newest = (r, a)
                break
        res = dict(g, status="ok", note="")
        stored = index.get(g["id"], {}).get("vpk", {})
        if newest and (newest[0]["tag_name"] != g["tag"] or newest[1]["name"] != os.path.basename(g["path"])):
            r, a = newest
            res.update(status="UPDATE", new_tag=r["tag_name"], new_asset=a["name"], new_size=a["size"],
                       new_url=a["browser_download_url"], new_date=r["published_at"][:10],
                       new_notes=(r.get("body") or "").strip())
        elif not mine or not vpk_of(mine, g["id"]):
            res.update(status="MISSING", note="release %s or its package is gone" % g["tag"])
        else:
            a = vpk_of(mine, g["id"])
            digest = (a.get("digest") or "").replace("sha256:", "")
            if digest and stored.get("sha256") and digest != stored["sha256"]:
                res.update(status="CHANGED", note="the release file was replaced (%s, %d bytes)" % (
                    a["updated_at"][:10], a["size"]), new_tag=g["tag"], new_asset=a["name"],
                    new_size=a["size"], new_url=a["browser_download_url"], new_date=a["updated_at"][:10],
                    new_notes="")
            elif stored.get("size") and a["size"] != stored["size"]:
                res.update(status="CHANGED", note="the release file's size is %d, the store says %d" % (
                    a["size"], stored["size"]), new_tag=g["tag"], new_asset=a["name"], new_size=a["size"],
                    new_url=a["browser_download_url"], new_date=a["updated_at"][:10], new_notes="")
        results.append(res)

    # candidates: recent packages on the same accounts, not in the store
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=RECENT_DAYS)
    known = {owner_repo(g["repo"]) for g in games}
    candidates = []
    for owner in sorted({owner_repo(g["repo"])[0] for g in games}):
        repos = api("/users/%s/repos?per_page=100&sort=pushed" % owner) or []
        for repo in repos:
            pushed = datetime.datetime.fromisoformat(repo["pushed_at"].replace("Z", "+00:00"))
            if pushed < since or repo["fork"]:
                continue
            r = api("/repos/%s/%s/releases/latest" % (owner, repo["name"]))
            if not r:
                continue
            for a in r.get("assets", []):
                m = re.match(r"(.+)-([0-9][^-]*)\.vpk$", a["name"])
                if m and m.group(1) not in listed:
                    candidates.append({"repo": repo["html_url"], "tag": r["tag_name"], "asset": a["name"],
                                       "date": r["published_at"][:10], "known_repo": (owner, repo["name"]) in known})
    return results, candidates


def report(results, candidates):
    print("Store check, %s\n" % datetime.date.today().isoformat())
    w = max(len(r["id"]) for r in results)
    for r in results:
        line = "%-8s %-*s %-10s %s" % (r["status"], w, r["id"], r["version"], r["tag"])
        if r["status"] == "UPDATE":
            line += "  ->  %s  %s (%.1f MB, %s)" % (r["new_tag"], r["new_asset"], r["new_size"] / 1e6, r["new_date"])
        elif r["note"]:
            line += "  " + r["note"]
        print(line)
        if r["status"] == "UPDATE" and r["new_notes"]:
            for n in r["new_notes"].splitlines()[:6]:
                print("%*s| %s" % (w + 10, "", n.rstrip()))
    print()
    if candidates:
        print("Not in the store (released in the last %d days):" % RECENT_DAYS)
        for c in candidates:
            print("  %s  %s  %s  %s" % (c["date"], c["asset"], c["tag"], c["repo"]))
    else:
        print("No new packages on the store's accounts.")
    todo = [r["id"] for r in results if r["status"] in ("UPDATE", "CHANGED")]
    print("\nTo take them: tools/check-updates.py --apply %s" % (" ".join(todo) if todo else "(nothing to do)"))


def apply(results, ids):
    take = [r for r in results if r["status"] in ("UPDATE", "CHANGED") and ("all" in ids or r["id"] in ids)]
    if not take:
        print("Nothing to apply.")
        return
    os.makedirs(STORE_VPKS, exist_ok=True)
    lines = open(LIST).read().split("\n")
    for r in take:
        dest = os.path.join(STORE_VPKS, r["new_asset"])
        print("downloading %s" % r["new_url"])
        req = urllib.request.Request(r["new_url"], headers={"User-Agent": "vectorpie-games-check"})
        with urllib.request.urlopen(req, timeout=300) as src, open(dest + ".part", "wb") as out:
            while True:
                block = src.read(1 << 20)
                if not block:
                    break
                out.write(block)
        if os.path.getsize(dest + ".part") != r["new_size"]:
            os.remove(dest + ".part")
            sys.exit("%s: incomplete download" % r["new_asset"])
        os.replace(dest + ".part", dest)
        old = lines[r["line"]]
        new = old.replace(r["path"], "~/store-vpks/" + r["new_asset"], 1)
        new = re.sub(r"(\s)%s(\s)" % re.escape(r["tag"]), r"\g<1>%s\g<2>" % r["new_tag"], new, count=1)
        lines[r["line"]] = new
        print("  games.list: %s" % new)
    open(LIST, "w", newline="\n").write("\n".join(lines))
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make-index.py")], check=True)
    subprocess.run(["git", "-C", ROOT, "status", "--short"])


def main():
    args = sys.argv[1:]
    results, candidates = check()
    if args and args[0] == "--apply":
        apply(results, set(args[1:]) or {"all"})
    else:
        report(results, candidates)


main()
