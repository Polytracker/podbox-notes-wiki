"""How the run looks in the window: the banner, a heading for each stage,
progress bars, a spinner while waiting on something with no count, and
colour for what went well, what was skipped and what failed.

Colour and moving lines only when the output is a terminal; written to a
file (python notes_wiki.py > log.txt) it's plain lines. NO_COLOR=1 turns
colour off.
"""
import os
import sys
import threading
import time

OUT = sys.stdout
LIVE = OUT.isatty()
COLOUR = LIVE and not os.environ.get("NO_COLOR")

if COLOUR and os.name == "nt":
    try:                                   # let the Windows console read colour codes
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, mode.value | 4)
    except Exception:
        COLOUR = False

try:
    "█░⠋✓".encode(OUT.encoding or "ascii")
    FANCY = True
except (UnicodeEncodeError, LookupError):
    FANCY = False

FULL, EMPTY = ("█", "░") if FANCY else ("#", "-")
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏" if FANCY else "|/-\\"
TICK, CROSS, DOT, ARROW = ("✓", "✗", "·", "▸") if FANCY else ("+", "x", "-", ">")


def paint(text, *codes):
    return f"\033[{';'.join(map(str, codes))}m{text}\033[0m" if COLOUR else text


def green(t): return paint(t, 32)
def yellow(t): return paint(t, 33)
def red(t): return paint(t, 31)
def grey(t): return paint(t, 90)
def bold(t): return paint(t, 1)
def cyan(t): return paint(t, 36)


def width():
    try:
        return os.get_terminal_size(OUT.fileno()).columns
    except (OSError, ValueError):
        return 100


def clock(seconds):
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


_line = threading.Lock()


def _say(text=""):
    with _line:
        if LIVE:
            OUT.write("\r\033[K")
        OUT.write(text + "\n")
        OUT.flush()


# ---------------------------------------------------------------- the banner
IPOD = [
    '██╗██████╗  ██████╗ ██████╗',
    '██║██╔══██╗██╔═══██╗██╔══██╗',
    '██║██████╔╝██║   ██║██║  ██║',
    '██║██╔═══╝ ██║   ██║██║  ██║',
    '██║██║     ╚██████╔╝██████╔╝',
    '╚═╝╚═╝      ╚═════╝ ╚═════╝',
]
LINER_NOTES = [
    '██╗     ██╗███╗   ██╗███████╗██████╗     ███╗   ██╗ ██████╗ ████████╗███████╗███████╗',
    '██║     ██║████╗  ██║██╔════╝██╔══██╗    ████╗  ██║██╔═══██╗╚══██╔══╝██╔════╝██╔════╝',
    '██║     ██║██╔██╗ ██║█████╗  ██████╔╝    ██╔██╗ ██║██║   ██║   ██║   █████╗  ███████╗',
    '██║     ██║██║╚██╗██║██╔══╝  ██╔══██╗    ██║╚██╗██║██║   ██║   ██║   ██╔══╝  ╚════██║',
    '███████╗██║██║ ╚████║███████╗██║  ██║    ██║ ╚████║╚██████╔╝   ██║   ███████╗███████║',
    '╚══════╝╚═╝╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝    ╚═╝  ╚═══╝ ╚═════╝    ╚═╝   ╚══════╝╚══════╝',
]
SMALL = [
    ' ___ ___  ___  ___    _    ___ _  _ ___ ___   _  _  ___ _____ ___ ___',
    '|_ _| _ \\/ _ \\|   \\  | |  |_ _| \\| | __| _ \\ | \\| |/ _ \\_   _| __/ __|',
    ' | ||  _/ (_) | |) | | |__ | || .` | _||   / | .` | (_) || | | _|\\__ \\',
    '|___|_|  \\___/|___/  |____|___|_|\\_|___|_|_\\ |_|\\_|\\___/ |_| |___|___/',
]
SHADES = (51, 45, 39, 33, 27, 63, 99, 135, 171, 207, 213, 219)


def banner(subtitle):
    big = FANCY and width() >= len(LINER_NOTES[0]) + 2
    lines = IPOD + LINER_NOTES if big else SMALL
    print()
    for n, line in enumerate(lines):
        print(paint(line, "38;5;%d" % SHADES[n % len(SHADES)], 1) if COLOUR else line)
    print(grey(subtitle))


# ---------------------------------------------------------------- stages
class Stage:
    """A heading now, and its time when it's done."""
    def __init__(self, title):
        self.title, self.start = title, time.time()
        _say()
        _say(bold(cyan(f"{ARROW} {title}")))

    def done(self, summary=""):
        took = grey(f"({clock(time.time() - self.start)})")
        _say(f"  {green(TICK)} {summary or 'done'} {took}")


def info(text):
    _say(f"  {grey(DOT)} {text}")


def good(text):
    _say(f"  {green(TICK)} {text}")


def warn(text):
    _say(f"  {yellow('!')} {yellow(text)}")


def error(text):
    _say(f"  {red(CROSS)} {red(text)}")


# ---------------------------------------------------------------- progress
class Bar:
    """done/total with a bar and the time left, on one line kept up to date;
    a single line at the end when the output isn't a terminal."""
    def __init__(self, label, total):
        self.label, self.total, self.n = label, max(total, 0), 0
        self.start, self.last, self.note = time.time(), 0.0, ""
        self._draw(force=True)

    def update(self, step=1, note=""):
        self.n += step
        if note:
            self.note = note
        self._draw()

    def _draw(self, force=False):
        if not LIVE or not self.total:
            return
        now = time.time()
        if not force and now - self.last < 0.1 and self.n < self.total:
            return
        self.last = now
        size = max(10, min(30, width() - len(self.label) - 40))
        filled = int(size * self.n / self.total)
        bar = green(FULL * filled) + grey(EMPTY * (size - filled))
        spent = now - self.start
        left = clock(spent / self.n * (self.total - self.n)) + " left" if self.n else ""
        note = grey(self.note[: max(0, width() - size - len(self.label) - 36)])
        with _line:
            OUT.write(f"\r\033[K  {self.label} {bar} {self.n}/{self.total}  {grey(left)}  {note}")
            OUT.flush()

    def close(self, summary=""):
        took = grey(f"({clock(time.time() - self.start)})")
        _say(f"  {green(TICK)} {self.label}: {summary or f'{self.n} of {self.total}'} {took}")


class Spinner:
    """A turning mark and the time spent, while waiting on something that has
    no count. Used as `with show.Spinner("Asking Wikidata"):`."""
    def __init__(self, label):
        self.label = label

    def __enter__(self):
        self.start, self.stop = time.time(), threading.Event()
        if LIVE:
            self.thread = threading.Thread(target=self._turn, daemon=True)
            self.thread.start()
        return self

    def _turn(self):
        n = 0
        while not self.stop.wait(0.1):
            with _line:
                OUT.write(f"\r\033[K  {cyan(SPIN[n % len(SPIN)])} {self.label} "
                          f"{grey(clock(time.time() - self.start))}")
                OUT.flush()
            n += 1

    def __exit__(self, *exc):
        self.stop.set()
        if LIVE:
            self.thread.join()
            with _line:
                OUT.write("\r\033[K")
                OUT.flush()
        return False
