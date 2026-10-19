"""
Пользовательские этапы: fish и шелл, вывод при запуске fish, KDE,
шрифты и LibreOffice, видеообои mpvpaper.
"""

import glob
import os
import pwd
import re
import shlex
import shutil
import signal
import subprocess
import time

from arch_core import *

FISH_PACKAGE = "fish"
FISH_PATH = "/usr/bin/fish"
SHELLS_PATH = "/etc/shells"
FISH_CONFIG_REL = os.path.join(".config", "fish", "config.fish")
FETCH_BEGIN = "# >>> arch-setup: вывод при запуске >>>"
FETCH_END = "# <<< arch-setup: вывод при запуске <<<"
FETCH_OPTIONS = {"1": "fastfetch", "2": "uwufetch", "3": None}

KDE_COLOR_PKG = "catppuccin-plasma-colorscheme-mocha"
KDE_CURSOR_PKG = "catppuccin-cursors-mocha"
KDE_ICON_PKG = "papirus-icon-theme"
KDE_ICON_THEME = "Papirus-Dark"
KDE_AUR_PACKAGES = [KDE_COLOR_PKG, KDE_CURSOR_PKG]
SYSTEM_SCHEME_DIR = "/usr/share/color-schemes"
SYSTEM_ICON_DIR = "/usr/share/icons"

OFFICE_FONT_PACKAGES = [
    "libreoffice-fresh", "ttf-liberation", "noto-fonts",
    "noto-fonts-cjk", "noto-fonts-emoji",
]

WALLPAPER_DIR_REL = os.path.join("Видео", "Обои")
WALLPAPER_DEFAULT_NAME = "moonside-lake-bloodborne-moewalls-com.mp4"
VIDEO_EXT = (".mp4", ".mkv", ".webm", ".mov")
WALLPAPER_DEFAULT_OUTPUTS = "DP-3,DP-1"
WALLPAPER_MPV_OPTS = "no-audio --loop --panscan=1.0"
WALLPAPER_SCRIPT_REL = os.path.join(".local", "bin", "arch-setup-wallpaper.sh")
WALLPAPER_LOG_REL = os.path.join(".cache", "arch-setup", "wallpaper.log")
AUTOSTART_REL = os.path.join(".config", "autostart", "arch-setup-wallpaper.desktop")
DRM_SYSFS = "/sys/class/drm"


# ---------- fish ----------

def ensure_shell_listed(shell_path):
    if not os.path.isfile(SHELLS_PATH):
        raise StageError(f"файл {SHELLS_PATH} не найден")
    with open(SHELLS_PATH, encoding="utf-8") as f:
        lines = f.readlines()
    if any(line.strip() == shell_path for line in lines):
        log.info("   %s уже есть в %s", shell_path, SHELLS_PATH)
        return
    backup = make_backup(SHELLS_PATH)
    log.info("   Резервная копия: %s", backup)
    new_lines = list(lines)
    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"
    new_lines.append(shell_path + "\n")
    write_file_atomic(SHELLS_PATH, new_lines)
    log.info("   Добавлена строка %s в %s", shell_path, SHELLS_PATH)


def stage_fish():
    if is_installed(FISH_PACKAGE):
        log.info("   fish уже установлен")
    else:
        if not ask_yes_no("\nУстановить fish (pacman -S --needed fish)? [y/N]: "):
            SKIPPED.append(("fish", "пропущено пользователем"))
            return
        run_interactive(["pacman", "-S", "--needed", FISH_PACKAGE], "Установка fish (pacman -S --needed fish)")

    run_command(["pacman", "-Q", FISH_PACKAGE], "Проверка установки fish")
    if not os.path.isfile(FISH_PATH):
        raise StageError(f"fish установлен, но {FISH_PATH} не найден")

    target = get_target_user()
    if target is None:
        log.warning("   Не определён обычный пользователь. Шелл не изменён.")
        SKIPPED.append(("fish как шелл по умолчанию", "нет обычного пользователя"))
        return
    name, pw = target
    if pw.pw_shell == FISH_PATH:
        log.info("   fish уже шелл по умолчанию для %s", name)
        return
    log.info("   Текущий шелл %s: %s", name, pw.pw_shell)
    if not ask_yes_no(f"\nСделать fish шеллом по умолчанию для {name}? [y/N]: "):
        SKIPPED.append(("fish как шелл по умолчанию", "пропущено пользователем"))
        return
    ensure_shell_listed(FISH_PATH)
    run_command(["chsh", "-s", FISH_PATH, name], f"Смена шелла для {name} на fish (chsh)")
    if pwd.getpwnam(name).pw_shell != FISH_PATH:
        raise StageError("шелл не изменился")
    log.info("   OK: шелл %s теперь fish. Вступит в силу после нового входа.", name)


def fetch_block(command):
    return f"{FETCH_BEGIN}\nif type -q {command}\n    {command}\nend\n{FETCH_END}\n"


def strip_fetch_block(text):
    pattern = re.escape(FETCH_BEGIN) + r".*?" + re.escape(FETCH_END) + r"\n?"
    return re.sub(pattern, "", text, flags=re.S)


def stage_fish_fetch():
    """Выбор: fastfetch, uwufetch или ничего. Настройка пишется в ~/.config/fish/config.fish."""
    target = get_target_user()
    if target is None:
        SKIPPED.append(("вывод при запуске fish", "нет обычного пользователя"))
        return
    name, pw = target
    home, uid, gid = pw.pw_dir, pw.pw_uid, pw.pw_gid
    config = os.path.join(home, FISH_CONFIG_REL)

    if not is_installed(FISH_PACKAGE):
        log.warning("   fish не установлен, настройка вывода пропущена.")
        SKIPPED.append(("вывод при запуске fish", "fish не установлен"))
        return

    log.info("   Что показывать при открытии терминала:")
    log.info("     1) fastfetch: информация о системе")
    log.info("     2) uwufetch: мем-вариант информации о системе")
    log.info("     3) ничего, откажусь")
    answer = ask_text("Ваш выбор [1/2/3, Enter = 3]: ", default="3")
    if answer not in FETCH_OPTIONS:
        log.warning("   Неверный выбор «%s». Ничего не меняю.", answer)
        SKIPPED.append(("вывод при запуске fish", "неверный выбор"))
        return
    command = FETCH_OPTIONS[answer]

    old = ""
    if os.path.isfile(config):
        with open(config, encoding="utf-8", errors="replace") as f:
            old = f.read()
    if command is None and FETCH_BEGIN not in old:
        log.info("   Вывод при запуске не нужен, конфиг fish не меняется.")
        return

    if command and not is_installed(command):
        log.warning("   %s не установлен. Блок добавится, но запускаться будет только после установки.", command)

    stripped = strip_fetch_block(old).rstrip()
    if command:
        new = (stripped + "\n\n" if stripped else "") + fetch_block(command)
    else:
        new = stripped + "\n" if stripped else ""

    if write_user_file(config, new, uid, gid, 0o644):
        log.info("   Записан конфиг fish: %s (%s)", config, command or "без вывода")
    else:
        log.info("   Настройка fish уже актуальна")


# ---------- KDE ----------

def read_ini_value(path, group, key):
    if not os.path.isfile(path):
        return None
    current = None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if line.startswith("[") and line.endswith("]"):
                    current = line[1:-1]
                elif current == group and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() == key:
                        return v.strip()
    except OSError:
        return None
    return None


def find_color_scheme(home):
    candidates = []
    for d in (SYSTEM_SCHEME_DIR, os.path.join(home, ".local", "share", "color-schemes")):
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            low = fn.lower()
            if low.endswith(".colors") and "mocha" in low and "flamingo" in low:
                candidates.append(fn[: -len(".colors")])
    if not candidates:
        return None
    return "CatppuccinMochaFlamingo" if "CatppuccinMochaFlamingo" in candidates else sorted(candidates)[0]


def find_cursor_theme(home):
    for d in (SYSTEM_ICON_DIR, os.path.join(home, ".local", "share", "icons")):
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            low = fn.lower()
            if "mocha" in low and "flamingo" in low and os.path.isdir(os.path.join(d, fn, "cursors")):
                return fn
    return None


def stage_kde_theme():
    if shutil.which("kwriteconfig6") is None:
        log.warning("   kwriteconfig6 не найден: Plasma 6 не установлена. Оформление пропущено.")
        SKIPPED.append(("оформление KDE", "нет kwriteconfig6"))
        return
    target = get_target_user()
    if target is None:
        SKIPPED.append(("оформление KDE", "нет обычного пользователя"))
        return
    name, pw = target
    home, uid, gid = pw.pw_dir, pw.pw_uid, pw.pw_gid

    missing = [p for p in [KDE_COLOR_PKG, KDE_CURSOR_PKG, KDE_ICON_PKG] if not is_installed(p)]
    official, aur = [], []
    if KDE_ICON_PKG in missing:
        r = run_command(["pacman", "-Si", KDE_ICON_PKG], f"Поиск {KDE_ICON_PKG}", check=False)
        if r.returncode == 0:
            official.append(KDE_ICON_PKG)
        else:
            SKIPPED.append((KDE_ICON_PKG, "нет в официальных репозиториях"))
    aur_missing = [p for p in KDE_AUR_PACKAGES if p in missing]
    if aur_missing:
        if not is_installed("yay"):
            for p in aur_missing:
                SKIPPED.append((p, "yay не установлен"))
        else:
            for p in aur_missing:
                r = run_command(user_env_cmd(name, home, uid, ["yay", "-Si", p]), f"Поиск {p} в AUR", check=False)
                if r.returncode == 0:
                    aur.append(p)
                else:
                    SKIPPED.append((p, "не найден в AUR"))

    wanted = official + aur
    if wanted and ask_yes_no(f"\nУстановить тему KDE ({', '.join(wanted)})? [y/N]: "):
        if official:
            run_interactive(["pacman", "-S", "--needed", *official], "Установка значков")
        if aur:
            try:
                run_interactive(user_env_cmd(name, home, uid, ["yay", "-S", "--needed", *aur]),
                                "Установка тем Catppuccin из AUR")
            except StageError as e:
                log.warning("   Темы из AUR не установлены: %s", e)

    scheme = find_color_scheme(home)
    cursor = find_cursor_theme(home)
    has_icons = os.path.isdir(os.path.join(SYSTEM_ICON_DIR, KDE_ICON_THEME))
    if not scheme:
        SKIPPED.append(("цветовая схема Mocha Flamingo", "не найдена в системе"))
    if not cursor:
        SKIPPED.append(("курсор Mocha Flamingo", "не найден в системе"))

    backed_up = set()

    def set_value(file_name, group, key, value, label):
        path = os.path.join(home, ".config", file_name)
        if read_ini_value(path, group, key) == value:
            log.info("   %s уже выбрано: %s", label, value)
            return
        if path not in backed_up and os.path.isfile(path):
            log.info("   Резервная копия: %s", backup_user_file(path, uid, gid))
            backed_up.add(path)
        run_command(
            user_env_cmd(name, home, uid, ["kwriteconfig6", "--file", file_name,
                                           "--group", group, "--key", key, value]),
            f"Запись: {label} = {value}",
        )
        if read_ini_value(path, group, key) != value:
            raise StageError(f"не удалось записать {label} в {path}")

    if scheme:
        set_value("kdeglobals", "General", "ColorScheme", scheme, "цветовая схема")
        if shutil.which("plasma-apply-colorscheme"):
            run_command(user_env_cmd(name, home, uid, ["plasma-apply-colorscheme", scheme]),
                        "Применение схемы в сессии", check=False)
    if cursor:
        set_value("kcminputrc", "Mouse", "cursorTheme", cursor, "курсор")
        if shutil.which("plasma-apply-cursortheme"):
            run_command(user_env_cmd(name, home, uid, ["plasma-apply-cursortheme", cursor]),
                        "Применение курсора в сессии", check=False)
    if has_icons:
        set_value("kdeglobals", "Icons", "Theme", KDE_ICON_THEME, "значки")

    log.info("   Вручную: декорации окон (Aurorae) и панель, курсор X11 — после перезапуска приложений.")


# ---------- Шрифты и LibreOffice ----------

def stage_office_fonts():
    missing = []
    for pkg in OFFICE_FONT_PACKAGES:
        if is_installed(pkg):
            log.info("   уже установлен: %s", pkg)
            continue
        r = run_command(["pacman", "-Si", pkg], f"Поиск {pkg}", check=False)
        if r.returncode != 0:
            SKIPPED.append((pkg, "нет в подключённых репозиториях"))
            continue
        missing.append(pkg)

    installed_now = []
    if missing:
        log.info("   К установке: %s", ", ".join(missing))
        if ask_yes_no(f"\nУстановить {len(missing)} пакетов (pacman -S --needed)? [y/N]: "):
            try:
                run_interactive(priv_cmd(["pacman", "-S", "--needed", *missing]), "Установка LibreOffice и шрифтов")
            except StageError as e:
                log.error("   Установка не завершилась: %s", e)
                for pkg in missing:
                    SKIPPED.append((pkg, "установка завершилась ошибкой"))
                return
            for pkg in missing:
                if is_installed(pkg):
                    installed_now.append(pkg)
                else:
                    SKIPPED.append((pkg, "после установки не найден"))
        else:
            for pkg in missing:
                SKIPPED.append((pkg, "пропущено пользователем"))

    if installed_now:
        target = get_target_user()
        if target is None:
            SKIPPED.append(("кеш шрифтов", "выполните fc-cache -f вручную"))
        else:
            name, pw = target
            run_command(["fc-cache", "-f"], f"Обновление кеша шрифтов (от {name})",
                        check=False, run_as=(name, pw.pw_dir))


# ---------- Видеообои ----------

def monitor_connected(output):
    for status in glob.glob(os.path.join(DRM_SYSFS, f"card*-{output}", "status")):
        try:
            with open(status, encoding="utf-8") as f:
                if f.read().strip() == "connected":
                    return True
        except OSError:
            continue
    return False


def valid_output_name(text):
    return re.fullmatch(r"[A-Za-z0-9-]+", text) is not None


def wayland_socket(uid):
    for path in sorted(glob.glob(f"/run/user/{uid}/wayland-*")):
        if not path.endswith(".lock"):
            return os.path.basename(path)
    return None


def find_wallpaper_pids(uid, output):
    pids = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            if os.stat(f"/proc/{entry}").st_uid != uid:
                continue
            with open(f"/proc/{entry}/cmdline", "rb") as f:
                argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if argv and os.path.basename(argv[0]) == "mpvpaper" and output in argv:
            pids.append(int(entry))
    return pids


def list_wallpapers(home):
    folder = os.path.join(home, WALLPAPER_DIR_REL)
    if not os.path.isdir(folder):
        return []
    return [
        os.path.join(folder, fn) for fn in sorted(os.listdir(folder))
        if os.path.splitext(fn)[1].lower() in VIDEO_EXT and os.path.isfile(os.path.join(folder, fn))
    ]


def choose_wallpaper(home):
    """Выбор видео: номер из списка, путь к файлу или Enter (для файла по умолчанию)."""
    candidates = list_wallpapers(home)
    default = os.path.join(home, WALLPAPER_DIR_REL, WALLPAPER_DEFAULT_NAME)
    log.info("   Видео в папке %s:", os.path.join(home, WALLPAPER_DIR_REL))
    if not candidates:
        log.info("     (видео не найдено)")
    for i, p in enumerate(candidates, start=1):
        log.info("     %d) %s", i, os.path.basename(p))
    log.info("   Введите номер, полный путь к видео (можно перетащить файл в терминал),")
    log.info("   Enter — файл по умолчанию (если есть), 0 — отказаться.")

    for _ in range(3):
        answer = ask_text("Видео: ", default="")
        if answer == "":
            if os.path.isfile(default):
                return default
            log.info("   Файл по умолчанию не найден, видеообои не выбраны.")
            return None
        if answer == "0":
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(candidates):
            return candidates[int(answer) - 1]
        path = clean_path_input(answer)
        if os.path.isfile(path) and os.path.splitext(path)[1].lower() in VIDEO_EXT:
            return os.path.abspath(path)
        log.warning("   Не подходит: %s (нужен существующий файл: %s)", path, ", ".join(VIDEO_EXT))
    log.warning("   Слишком много неудачных попыток, видеообои пропущены.")
    return None


def wallpaper_script_content(video, outputs):
    lines = [
        "#!/bin/sh",
        "# Создано Arch Setup. Повторный запуск не создаёт дубликаты.",
        f"VIDEO={shlex.quote(video)}",
        f'LOG="$HOME/{WALLPAPER_LOG_REL}"',
        'mkdir -p "$(dirname "$LOG")"',
        'if [ ! -f "$VIDEO" ]; then echo "Видео не найдено: $VIDEO" >> "$LOG"; exit 1; fi',
        'if ! command -v mpvpaper >/dev/null 2>&1; then echo "mpvpaper не установлен" >> "$LOG"; exit 1; fi',
    ]
    for out in outputs:
        lines += [
            f'if pgrep -u "$(id -u)" -f "mpvpaper .* {out} " >/dev/null 2>&1; then',
            f'  echo "mpvpaper на {out} уже запущен, пропуск" >> "$LOG"',
            f'elif grep -q "^connected$" /sys/class/drm/card*-{out}/status 2>/dev/null; then',
            f'  mpvpaper --auto-pause -o "{WALLPAPER_MPV_OPTS}" {out} "$VIDEO" >> "$LOG" 2>&1 &',
            "else",
            f'  echo "ПРЕДУПРЕЖДЕНИЕ: монитор {out} не подключён." >> "$LOG"',
            "fi",
        ]
    return "\n".join(lines) + "\n"


def autostart_content(script_path, outputs):
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Arch Setup: видеообои\n"
        f"Comment=Запуск mpvpaper на мониторах {', '.join(outputs)}\n"
        f'Exec="{script_path}"\n'
        "Terminal=false\n"
        "X-KDE-autostart-phase=2\n"
        "NoDisplay=true\n"
    )


def stage_wallpaper():
    target = get_target_user()
    if target is None:
        SKIPPED.append(("видеообои", "нет обычного пользователя"))
        return
    name, pw = target
    home, uid, gid = pw.pw_dir, pw.pw_uid, pw.pw_gid

    if not is_installed("mpvpaper"):
        log.warning("   mpvpaper не установлен. Добавьте его в [aur] файла списка и запустите снова.")
        SKIPPED.append(("видеообои", "mpvpaper не установлен"))
        return

    video = choose_wallpaper(home)
    if video is None:
        SKIPPED.append(("видеообои", "видео не выбрано"))
        return
    log.info("   Выбрано видео: %s", video)

    raw = ask_text(f"Мониторы через запятую [{WALLPAPER_DEFAULT_OUTPUTS}]: ", default=WALLPAPER_DEFAULT_OUTPUTS)
    outputs = [o.strip() for o in raw.split(",") if o.strip()]
    if not outputs or not all(valid_output_name(o) for o in outputs):
        log.warning("   Некорректные имена мониторов: %s", raw)
        SKIPPED.append(("видеообои", "некорректные имена мониторов"))
        return

    connected = []
    for out in outputs:
        if monitor_connected(out):
            log.info("   OK: монитор %s подключён", out)
            connected.append(out)
        else:
            log.warning("   ВНИМАНИЕ: монитор %s не найден. Возможно, выходы изменились.", out)
            SKIPPED.append((f"видеообои на {out}", "монитор не подключён"))
    if not connected:
        log.warning("   Ни один монитор не подключён, видеообои не запущены.")
        return

    script_path = os.path.join(home, WALLPAPER_SCRIPT_REL)
    desktop_path = os.path.join(home, AUTOSTART_REL)
    script_changed = write_user_file(script_path, wallpaper_script_content(video, connected), uid, gid, 0o755)
    log.info("   %s: %s", "Записан скрипт" if script_changed else "Скрипт уже актуален", script_path)
    if write_user_file(desktop_path, autostart_content(script_path, connected), uid, gid, 0o644):
        log.info("   Записан автозапуск KDE: %s", desktop_path)
    else:
        log.info("   Автозапуск уже настроен: %s", desktop_path)

    sock = wayland_socket(uid)
    if sock is None:
        log.warning("   Wayland-сессия не найдена. Видеообои запустятся после входа в KDE Plasma Wayland.")
        return

    running = [out for out in connected if find_wallpaper_pids(uid, out)]
    if running and script_changed:
        if ask_yes_no("\nОбои уже работают со старыми настройками. Перезапустить с новыми? [y/N]: "):
            for out in running:
                for pid in find_wallpaper_pids(uid, out):
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except OSError:
                        pass
            running = []
            time.sleep(1)

    to_start = [out for out in connected if not find_wallpaper_pids(uid, out)]
    if not to_start:
        log.info("   Видеообои уже запущены, новые процессы не создаются.")
        return

    log.info("-> Запуск видеообоев от %s: %s", name, ", ".join(to_start))
    cmd = [
        "runuser", "-u", name, "--", "env",
        f"HOME={home}", f"USER={name}",
        f"XDG_RUNTIME_DIR=/run/user/{uid}",
        f"WAYLAND_DISPLAY={sock}",
        "/bin/sh", script_path,
    ]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        log.warning("   Скрипт запуска не завершился вовремя, проверьте лог.")
    except OSError as e:
        raise StageError(f"не удалось запустить видеообои: {e}")

    time.sleep(3)
    for out in connected:
        pids = find_wallpaper_pids(uid, out)
        if not pids:
            log.warning("   НЕ ЗАПУЩЕН на %s. Лог: ~/%s", out, WALLPAPER_LOG_REL)
            SKIPPED.append((f"видеообои на {out}", "mpvpaper не запустился"))
        elif len(pids) > 1:
            log.warning("   ВНИМАНИЕ: на %s запущено %d процессов mpvpaper", out, len(pids))
        else:
            log.info("   OK: mpvpaper работает на %s (PID %d)", out, pids[0])