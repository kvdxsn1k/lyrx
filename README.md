# lyrx

Big pixel-art lyrics in your terminal, synced to Spotify.

```
██          ██      ██  ████████    ██      ██
██          ██      ██  ██      ██    ██  ██
██            ██████    ████████        ██
██              ██      ██    ██      ██  ██
██████████      ██      ██      ██  ██      ██
```

## Requirements

- Linux (uses `playerctl` for Spotify integration)
- Spotify desktop app
- `playerctl` installed (`sudo pacman -S playerctl` / `sudo apt install playerctl`)
- A terminal with Unicode support

## Install

### Arch Linux (AUR)

```bash
yay -S lyrx
# or
paru -S lyrx
```

### pipx (any distro)

```bash
pipx install git+https://github.com/kvdxsn1k/lyrx.git
```

### pip

```bash
pip install git+https://github.com/kvdxsn1k/lyrx.git
```

## Usage

```bash
lyrx                          # white text, default settings
lyrx --color spotify          # Spotify green
lyrx --color cover            # auto-extract color from album art
lyrx --color ff4400           # custom hex color
lyrx --idle dance             # dancing stick figure during instrumentals
lyrx --idle cat               # cat animation
lyrx --offset -0.6            # show lyrics 600ms early
```

### Options

| Flag | Description |
|------|-------------|
| `--color`, `-c` | Text color: hex, name (`white`, `red`, `green`, `blue`, `yellow`, `cyan`, `magenta`, `orange`, `pink`, `purple`, `spotify`), or `cover` for album art color |
| `--offset`, `-o` | Audio offset in seconds, negative = lyrics appear earlier (default: `-0.4`) |
| `--idle`, `-i` | Idle animation: `wave`, `dots`, `bounce`, `dance`, `girl`, `cat`, `music` |

### How it works

1. Reads current track + playback position from Spotify via `playerctl`
2. Fetches time-synced LRC lyrics (cached in `~/.cache/lyrx/`)
3. Splits lines into 1-2 word chunks, timed proportionally to syllable count
4. Renders each chunk as big pixel text using a blocky pixel font + Unicode half-blocks
5. Shows idle animations during instrumental breaks

## About

Made this for myself and friends to have fun with lyrics in the terminal. Anyone is welcome to use it, fork it, or do whatever you want with it.

If something is broken or you have ideas — feel free to open an issue: https://github.com/kvdxsn1k/lyrx/issues
