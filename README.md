# VectorPie games

The game store of the VectorPie menu: `games.json` lists the open-source
games a cabinet can install from Settings → GAMES → INSTALL GAMES, with their
marquees in `marquees/`. The menu reads them from this repository; each
game's package is downloaded from its own repository's release, and checked
against its size and SHA-256 here before it is installed.

## Adding or updating a game

1. Build the game's package (`cmake --build --preset pi --target vpk`) and
   publish it as a release of its repository, the `.vpk` attached.
2. List it in `games.list`: the package, the repository, the release tag,
   the license.
3. `python3 tools/make-index.py`: rewrites `games.json` and `marquees/` from
   the packages.
4. Commit and push.
