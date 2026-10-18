#!/usr/bin/env python3
# make-index.py [games.list]: the store's index from the built packages.
# For each line of games.list (package, repository, tag, license) it reads
# the package's game.ini, copies its marquee to marquees/<id>.png, and
# writes games.json: the fields the menu's INSTALL GAMES page shows, the
# package's download link on the repository's release, its size and its
# SHA-256 (checked by the menu before it installs).
import datetime, hashlib, json, os, sys, tarfile

FIELDS = ("id", "name", "manufacturer", "author", "description", "version", "sdk")


def manifest(text):
    """game.ini's package lines (before any [section]), comments dropped."""
    out = {}
    for line in text.splitlines():
        for i, c in enumerate(line):
            if c in ";#" and (i == 0 or line[i - 1] in " \t"):
                line = line[:i]
                break
        line = line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            break
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    listing = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "games.list")
    os.makedirs(os.path.join(root, "marquees"), exist_ok=True)
    games = []
    for line in open(listing):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        path, repo, tag, license_ = line.split()
        path = os.path.expanduser(path)
        with tarfile.open(path, "r:gz") as tar:
            top = tar.getnames()[0].split("/")[0]
            ini = manifest(tar.extractfile(top + "/game.ini").read().decode())
            if ini.get("id") != top:
                sys.exit("%s: its folder is not its id" % path)
            marquee = ini.get("marquee", "marquee.png")
            try:
                data = tar.extractfile(top + "/" + marquee).read()
                open(os.path.join(root, "marquees", ini["id"] + ".png"), "wb").write(data)
                marquee = "marquees/%s.png" % ini["id"]
            except KeyError:
                marquee = ""
        blob = open(path, "rb").read()
        game = {k: ini[k] for k in FIELDS if k in ini}
        game.update({
            "license": license_,
            "source": repo,
            "marquee": marquee,
            "vpk": {
                "url": "%s/releases/download/%s/%s" % (repo, tag, os.path.basename(path)),
                "size": len(blob),
                "sha256": hashlib.sha256(blob).hexdigest(),
            },
        })
        games.append(game)
        print("%-12s %-8s %s" % (game["id"], game["version"], game["vpk"]["url"]))
    index = {"format": 1, "updated": datetime.date.today().isoformat(), "games": games}
    with open(os.path.join(root, "games.json"), "w", newline="\n") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
        f.write("\n")


main()
