"""
Системные этапы: проверки, локали, репозитории, обновление, vim,
сборка yay из AUR, команды uwu и www.
"""

import glob
import os
import re
import shutil
import stat
import tempfile
import time

from arch_core import *

LOCALE_GEN_PATH = "/etc/locale.gen"
LOCALES_TO_ENABLE = ["en_US.UTF-8 UTF-8", "ru_RU.UTF-8 UTF-8"]
PACMAN_CONF_PATH = "/etc/pacman.conf"
MIRRORLIST_PATH = "/etc/pacman.d/mirrorlist"
REPOS_TO_ENABLE = ["core", "extra", "multilib"]
BUILD_DEPENDENCIES = ["base-devel", "git"]
YAY_REPO_URL = "https://aur.archlinux.org/yay.git"
ALIAS_BIN_DIR = "/usr/local/bin"
ALIAS_NAMES = ["uwu", "www"]
ALIAS_CONTENT = (
    "#!/bin/sh\n"
    "# Создано Arch Setup: альтернативное имя для sudo\n"
    'exec /usr/bin/sudo "$@"\n'
)
SECTION_RE = re.compile(r"^\s*(#?)\s*\[([^\]]+)\]\s*$")
INCLUDE_RE = re.compile(r"^\s*(#?)\s*Include\s*=\s*(\S+)\s*$")


# ---------- Проверки ----------

def read_os_release():
    data = {}
    with open(OS_RELEASE_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key] = value.strip('"')
    return data


def stage_checks():
    """Проверка системы и прав root."""
    try:
        info = read_os_release()
    except OSError as e:
        raise StageError(f"не удалось прочитать {OS_RELEASE_PATH}: {e}")
    if info.get("ID") != "arch":
        raise StageError("система не Arch Linux")
    log.info("   OK: система — Arch Linux")
    if os.geteuid() != 0:
        raise StageError("нужны права root. Запустите: sudo python3 Arch.py")
    log.info("   OK: скрипт запущен с правами root")


def stage_check_tools():
    """Только чтение: версии инструментов."""
    run_command(["pacman", "-V"], "Версия pacman")
    run_command(["uname", "-r"], "Версия ядра")


# ---------- Локали ----------

def _norm(text):
    return " ".join(text.split())


def enable_locale_lines(lines, targets):
    new_lines = list(lines)
    changes = []
    for target in targets:
        wanted = _norm(target)
        active = False
        commented_index = None
        for i, raw in enumerate(new_lines):
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                if commented_index is None and _norm(stripped[1:]) == wanted:
                    commented_index = i
            elif _norm(stripped) == wanted:
                active = True
                break
        if active:
            continue
        if commented_index is not None:
            new_lines[commented_index] = target + "\n"
            changes.append(f"раскомментирована строка: {target}")
        else:
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines[-1] += "\n"
            new_lines.append(target + "\n")
            changes.append(f"добавлена строка: {target}")
    return new_lines, changes


def locale_name_for_check(target):
    name = target.split()[0]
    return name.replace("UTF-8", "utf8").replace("utf-8", "utf8")


def stage_locales():
    path = LOCALE_GEN_PATH
    if not os.path.isfile(path):
        raise StageError(f"файл {path} не найден (установлен ли пакет glibc?)")
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        raise StageError(f"не удалось прочитать {path}: {e}")

    new_lines, changes = enable_locale_lines(lines, LOCALES_TO_ENABLE)
    if changes:
        backup_path = make_backup(path)
        log.info("   Резервная копия: %s", backup_path)
        write_file_atomic(path, new_lines)
        for change in changes:
            log.info("   %s", change)
    else:
        log.info("   Нужные локали уже включены, файл не меняется")

    run_command(["locale-gen"], "Генерация локалей (locale-gen)")
    result = run_command(["locale", "-a"], "Проверка установленных локалей")
    available = {line.strip().lower() for line in result.stdout.splitlines()}
    for target in LOCALES_TO_ENABLE:
        name = locale_name_for_check(target).lower()
        if name not in available:
            raise StageError(f"локаль {name} не появилась после locale-gen")
        log.info("   OK: локаль %s доступна", name)


# ---------- Репозитории ----------

def enable_repositories(lines, repos):
    new_lines = list(lines)
    changes = []
    for repo in repos:
        headers = []
        for i, raw in enumerate(new_lines):
            m = SECTION_RE.match(raw)
            if m and m.group(2).strip() == repo:
                headers.append((i, m.group(1) == "#"))
        if not headers:
            raise StageError(f"в {PACMAN_CONF_PATH} нет секции [{repo}]. Проверьте файл вручную.")
        if len(headers) > 1:
            raise StageError(f"секция [{repo}] указана {len(headers)} раза. Файл не менялся.")
        head_index, head_commented = headers[0]

        end = len(new_lines)
        for j in range(head_index + 1, len(new_lines)):
            if SECTION_RE.match(new_lines[j]):
                end = j
                break

        active_other = []
        mirror_active = False
        mirror_commented = []
        for j in range(head_index + 1, end):
            m = INCLUDE_RE.match(new_lines[j])
            if not m:
                continue
            commented = m.group(1) == "#"
            path = m.group(2)
            if path == MIRRORLIST_PATH:
                if commented:
                    mirror_commented.append(j)
                else:
                    mirror_active = True
            elif not commented:
                active_other.append(path)
        if active_other:
            raise StageError(f"в [{repo}] уже есть свой Include: {', '.join(active_other)}. Файл не менялся.")

        if head_commented:
            new_lines[head_index] = f"[{repo}]\n"
            changes.append(f"включена секция [{repo}]")
        if not mirror_active:
            if mirror_commented:
                j = mirror_commented[0]
                new_lines[j] = f"Include = {MIRRORLIST_PATH}\n"
                changes.append(f"раскомментирована строка Include в [{repo}]")
            else:
                if not new_lines[head_index].endswith("\n"):
                    new_lines[head_index] += "\n"
                new_lines.insert(head_index + 1, f"Include = {MIRRORLIST_PATH}\n")
                changes.append(f"добавлена строка Include в [{repo}]")
    return new_lines, changes


def stage_repositories():
    path = PACMAN_CONF_PATH
    if not os.path.isfile(path):
        raise StageError(f"файл {path} не найден")
    if not os.path.isfile(MIRRORLIST_PATH):
        raise StageError(f"файл {MIRRORLIST_PATH} не найден. Установите: sudo pacman -S pacman-mirrorlist")
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        raise StageError(f"не удалось прочитать {path}: {e}")

    new_lines, changes = enable_repositories(lines, REPOS_TO_ENABLE)
    if changes:
        backup_path = make_backup(path)
        log.info("   Резервная копия: %s", backup_path)
        write_file_atomic(path, new_lines)
        for change in changes:
            log.info("   %s", change)
    else:
        log.info("   Нужные репозитории уже включены, файл не меняется")

    result = run_command(
        ["pacman-conf", "--config", path, "--repo-list"],
        "Проверка списка активных репозиториев",
    )
    active = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    for repo in REPOS_TO_ENABLE:
        if repo not in active:
            raise StageError(f"репозиторий {repo} не появился в списке pacman-conf")
        log.info("   OK: репозиторий %s активен", repo)


# ---------- Обновление и vim ----------

def stage_system_update():
    if not ask_yes_no("\nЗапустить полное обновление системы (pacman -Syu)? [y/N]: "):
        log.info("   Обновление пропущено.")
        return
    run_interactive(["pacman", "-Syu"], "Полное обновление системы (pacman -Syu)")


def stage_remove_vim():
    result = run_command(["pacman", "-Q", "vim"], "Проверка: установлен ли vim", check=False)
    if result.returncode != 0:
        log.info("   vim не установлен, ничего делать не нужно")
        return
    if not ask_yes_no("\nvim установлен. Удалить его командой pacman -Rns vim? [y/N]: "):
        log.info("   vim оставлен без изменений")
        return
    run_interactive(["pacman", "-Rns", "vim"], "Удаление vim (pacman -Rns vim)")


# ---------- yay из AUR ----------

def stage_aur_prereqs():
    run_interactive(
        ["pacman", "-S", "--needed", *BUILD_DEPENDENCIES],
        "Установка зависимостей сборки (pacman -S --needed base-devel git)",
    )
    run_command(["pacman", "-Q", "git"], "Проверка установки git")
    result = run_command(["pacman", "-Q", "base-devel"], "Проверка пакета base-devel", check=False)
    if result.returncode != 0:
        result = run_command(["pacman", "-Qg", "base-devel"], "Проверка группы base-devel", check=False)
    if result.returncode != 0:
        raise StageError("base-devel не установлен ни как пакет, ни как группа")


def check_existing_clone(build_dir, run_as):
    origin = run_command(
        ["git", "-C", build_dir, "remote", "get-url", "origin"],
        "Проверка адреса репозитория в каталоге сборки", check=False, run_as=run_as,
    )
    if origin.returncode != 0 or origin.stdout.strip() != YAY_REPO_URL:
        raise StageError(f"каталог {build_dir} не является клоном {YAY_REPO_URL}. Он не изменён.")
    status = run_command(
        ["git", "-C", build_dir, "status", "--porcelain"],
        "Проверка локальных изменений", check=False, run_as=run_as,
    )
    if status.stdout.strip():
        raise StageError(f"в каталоге {build_dir} есть незакоммиченные изменения. Он не изменён.")


def stage_install_yay():
    if is_installed("yay"):
        log.info("   yay уже установлен")
        return
    if not ask_yes_no("\nyay не установлен. Собрать и установить его из AUR? [y/N]: "):
        log.info("   Установка yay пропущена.")
        SKIPPED.append(("yay", "пропущено пользователем"))
        return

    user, home = get_build_user()
    run_as = (user, home)
    log.info("   Сборка выполняется от пользователя %s, не от root", user)

    base_dir = os.path.join(home, AUR_CACHE_SUBDIR)
    build_dir = os.path.join(base_dir, "yay")
    run_command(["mkdir", "-p", base_dir], "Создание каталога для сборки", run_as=run_as)

    clone_needed = True
    if os.path.exists(build_dir):
        check_existing_clone(build_dir, run_as)
        if ask_yes_no(f"\nКаталог {build_dir} уже существует. Переименовать и скачать заново? [y/N]: "):
            old_dir = f"{build_dir}.old-{time.strftime('%Y%m%d-%H%M%S')}"
            os.rename(build_dir, old_dir)
            log.info("   Старый каталог переименован: %s", old_dir)
        else:
            clone_needed = False

    if clone_needed:
        run_command(["git", "clone", YAY_REPO_URL, build_dir], "Загрузка исходников yay", run_as=run_as)

    run_interactive(["makepkg", "-s"], "Сборка yay (makepkg -s)", run_as=run_as, cwd=build_dir)

    packages = [
        p for p in glob.glob(os.path.join(build_dir, "yay-*.pkg.tar*"))
        if not p.endswith(".sig") and "debug" not in os.path.basename(p)
    ]
    if len(packages) != 1:
        raise StageError(f"после сборки ожидался один пакет yay, найдено: {len(packages)}")

    run_interactive(priv_cmd(["pacman", "-U", packages[0]]), "Установка собранного yay (pacman -U)")
    run_command(["pacman", "-Q", "yay"], "Проверка установки yay")


# ---------- uwu и www ----------

def alias_matches(path):
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode):
            return False
        if st.st_uid != 0 or stat.S_IMODE(st.st_mode) != 0o755:
            return False
        with open(path, encoding="utf-8") as f:
            return f.read() == ALIAS_CONTENT
    except (OSError, UnicodeDecodeError):
        return False


def check_bin_dir_in_path():
    dirs = [d.rstrip("/") for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    if ALIAS_BIN_DIR in dirs:
        log.info("   OK: %s есть в PATH", ALIAS_BIN_DIR)
    else:
        log.warning("   ВНИМАНИЕ: %s не найден в PATH этой среды (скрипт его не меняет).", ALIAS_BIN_DIR)


def stage_sudo_aliases():
    if not os.path.isfile(SUDO_BIN) or not os.access(SUDO_BIN, os.X_OK):
        raise StageError(f"{SUDO_BIN} не найден. Ничего не установлено.")
    log.info("   OK: найден %s", SUDO_BIN)

    to_install = []
    for name in ALIAS_NAMES:
        path = os.path.join(ALIAS_BIN_DIR, name)
        if os.path.lexists(path):
            if alias_matches(path):
                log.info("   %s уже установлен и совпадает с эталоном", path)
                continue
            log.warning("   КОНФЛИКТ: %s уже существует и отличается от эталона", path)
            if ask_yes_no(f"\nФайл {path} уже существует. Заменить (старый сохранится как .bak)? [y/N]: "):
                to_install.append((name, path, True))
            else:
                SKIPPED.append((name, f"файл {path} не перезаписан"))
        else:
            to_install.append((name, path, False))

    installed = []
    if not to_install:
        log.info("   Новых файлов для установки нет")
    elif not ask_yes_no(f"\nУстановить {', '.join(n for n, _, _ in to_install)} в {ALIAS_BIN_DIR}? [y/N]: "):
        log.info("   Установка пропущена пользователем.")
        for name, _, _ in to_install:
            SKIPPED.append((name, "пропущено пользователем"))
    else:
        fd, src = tempfile.mkstemp(prefix="arch-setup-alias-", suffix=".sh")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(ALIAS_CONTENT)
            for name, path, replace in to_install:
                if replace:
                    backup = f"{path}.arch-setup-{time.strftime('%Y%m%d-%H%M%S')}.bak"
                    run_interactive(priv_cmd(["mv", path, backup]), f"Сохранение старого {name} как {backup}")
                run_interactive(
                    priv_cmd(["install", "-m", "755", "-o", "root", "-g", "root", src, path]),
                    f"Установка {path} (root:root, 755)",
                )
                installed.append(name)
        finally:
            if os.path.exists(src):
                os.remove(src)

    for name in installed:
        path = os.path.join(ALIAS_BIN_DIR, name)
        if not alias_matches(path):
            raise StageError(f"после установки {path} не совпадает с эталоном")
        log.info("   OK: %s установлен", path)
    check_bin_dir_in_path()