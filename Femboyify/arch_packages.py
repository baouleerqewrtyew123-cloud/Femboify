"""
Пакеты из файла пользователя ~/.config/arch-setup/packages.txt:
установка и удаление для pacman и AUR. Команды пишет скрипт, пользователь пишет только имена.
"""

import os
import re

from arch_core import *

PACKAGE_LIST_REL = os.path.join(".config", "arch-setup", "packages.txt")
SECTIONS = ("pacman", "pacman-remove", "aur", "aur-remove")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9@._+-]*$")

# Эти пакеты не удаляются ни при каких условиях
PROTECTED = {
    "base", "base-devel", "glibc", "bash", "pacman", "sudo", "systemd",
    "linux", "linux-zen", "linux-firmware", "plasma-desktop", "plasma-workspace",
    "sddm", "networkmanager", "yay",
}

DEFAULT_LIST = """# Список пакетов Arch Setup.
# Редактируйте файл и запускайте установщик снова.
# Пишите только название пакета, по одному в строке. Комментарий начинается с #.
# Разделы:
#   [pacman]         ставим из официальных репозиториев
#   [pacman-remove]  удаляем из системы (pacman -Rns), с подтверждением
#   [aur]            ставим из AUR через yay (сборка от вашего пользователя)
#   [aur-remove]     удаляем пакеты из AUR (pacman -Rns), с подтверждением

[pacman]
konsole
kitty
neovim
pluma
util-linux
telegram-desktop
discord
steam
firefox
code
fastfetch
keepassxc
zed
uwufetch

[pacman-remove]
# Пример: раскомментируйте строку, чтобы удалить пакет
# vim

[aur]
femboysay
mpvpaper

[aur-remove]
# Пример: femboysay
"""


def parse_package_list(text):
    """Разбирает текст файла. Возвращает (словарь разделов, список предупреждений)."""
    sections = {s: [] for s in SECTIONS}
    problems = []
    current = None
    for num, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            name = line[1:-1].strip().lower()
            if name in sections:
                current = name
            else:
                current = None
                problems.append(f"строка {num}: неизвестный раздел {line}, пропущен")
            continue
        if current is None:
            problems.append(f"строка {num}: «{line}» вне раздела, пропущено")
            continue
        if not NAME_RE.match(line):
            problems.append(f"строка {num}: некорректное имя «{line}», пропущено")
            continue
        if line not in sections[current]:
            sections[current].append(line)
    return sections, problems


def load_package_lists():
    """Читает файл списков. Если файла нет, создаёт его с примером."""
    home, uid, gid = get_real_user()
    path = os.path.join(home, PACKAGE_LIST_REL)
    if not os.path.isfile(path):
        write_user_file(path, DEFAULT_LIST, uid, gid, 0o644)
        log.info("   Создан файл списка пакетов: %s", path)
        log.info("   Его можно редактировать. Изменения применяются при следующем запуске.")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise StageError(f"не удалось прочитать {path}: {e}")

    lists, problems = parse_package_list(text)
    for p in problems:
        log.warning("   %s", p)
    log.info(
        "   Из %s: установка pacman %d, удаление pacman %d, AUR %d, удаление AUR %d",
        path, len(lists["pacman"]), len(lists["pacman-remove"]),
        len(lists["aur"]), len(lists["aur-remove"]),
    )
    return lists


def verify_installed(names):
    for pkg in names:
        if is_installed(pkg):
            log.info("   OK: установлен %s", pkg)
        else:
            log.warning("   НЕ УСТАНОВЛЕН: %s", pkg)
            SKIPPED.append((pkg, "после установки не найден в системе"))


def install_pacman(names):
    if not names:
        log.info("   Раздел [pacman] пуст")
        return
    to_install = []
    for pkg in names:
        if is_installed(pkg):
            log.info("   уже установлен: %s", pkg)
            continue
        result = run_command(["pacman", "-Si", pkg], f"Поиск {pkg} в репозиториях", check=False)
        if result.returncode != 0:
            log.warning("   НЕ НАЙДЕН в подключённых репозиториях: %s", pkg)
            SKIPPED.append((pkg, "нет в подключённых официальных репозиториях"))
            continue
        to_install.append(pkg)

    if not to_install:
        log.info("   Новых пакетов для установки нет")
        return
    log.info("   К установке: %s", ", ".join(to_install))
    if not ask_yes_no(f"\nУстановить {len(to_install)} пакетов (pacman -S --needed)? [y/N]: "):
        log.info("   Установка пропущена пользователем.")
        for pkg in to_install:
            SKIPPED.append((pkg, "пропущено пользователем"))
        return
    try:
        run_interactive(priv_cmd(["pacman", "-S", "--needed", *to_install]), "Установка пакетов (pacman -S --needed)")
    except StageError as e:
        log.error("   Установка не завершилась: %s", e)
        for pkg in to_install:
            SKIPPED.append((pkg, "установка завершилась ошибкой"))
        return
    verify_installed(to_install)


def install_aur(names):
    if not names:
        log.info("   Раздел [aur] пуст")
        return
    if not is_installed("yay"):
        log.warning("   yay не установлен: AUR-пакеты пропущены.")
        for pkg in names:
            SKIPPED.append((pkg, "yay не установлен"))
        return

    user, home = get_build_user()
    run_as = (user, home)
    to_install = []
    for pkg in names:
        if is_installed(pkg):
            log.info("   уже установлен: %s", pkg)
            continue
        result = run_command(["yay", "-Si", pkg], f"Поиск {pkg} в AUR", check=False, run_as=run_as)
        if result.returncode != 0:
            log.warning("   НЕ НАЙДЕН в AUR: %s", pkg)
            SKIPPED.append((pkg, "не найден в AUR"))
            continue
        to_install.append(pkg)

    if not to_install:
        log.info("   Новых AUR-пакетов для установки нет")
        return
    log.info("   К установке из AUR: %s", ", ".join(to_install))
    if not ask_yes_no("\nУстановить через yay? Сборка и вопросы будут видны в терминале [y/N]: "):
        log.info("   Установка AUR-пакетов пропущена пользователем.")
        for pkg in to_install:
            SKIPPED.append((pkg, "пропущено пользователем"))
        return
    try:
        run_interactive(["yay", "-S", "--needed", *to_install], "Установка AUR-пакетов (yay -S --needed)", run_as=run_as)
    except StageError as e:
        log.error("   Установка AUR не завершилась: %s", e)
        for pkg in to_install:
            SKIPPED.append((pkg, "установка завершилась ошибкой"))
        return
    verify_installed(to_install)


def remove_packages(names, section):
    """Удаляет пакеты командой pacman -Rns после явного подтверждения. Системные пакеты защищены."""
    if not names:
        log.info("   Раздел [%s] пуст, удалять нечего", section)
        return
    to_remove = []
    for pkg in names:
        if pkg in PROTECTED:
            log.warning("   ЗАЩИЩЁН, не удаляем: %s", pkg)
            SKIPPED.append((pkg, "системный пакет, удаление запрещено"))
            continue
        if not is_installed(pkg):
            log.info("   не установлен, нечего удалять: %s", pkg)
            continue
        to_remove.append(pkg)

    if not to_remove:
        log.info("   Удалять нечего")
        return
    log.warning("   К УДАЛЕНИЮ: %s", ", ".join(to_remove))
    if not ask_yes_no(f"\nУдалить {len(to_remove)} пакетов командой pacman -Rns? [y/N]: "):
        log.info("   Удаление пропущено пользователем.")
        for pkg in to_remove:
            SKIPPED.append((pkg, "удаление пропущено пользователем"))
        return
    try:
        run_interactive(priv_cmd(["pacman", "-Rns", *to_remove]), f"Удаление пакетов из [{section}] (pacman -Rns)")
    except StageError as e:
        log.error("   Удаление не завершилось: %s", e)
        for pkg in to_remove:
            SKIPPED.append((pkg, "удаление завершилось ошибкой"))
        return
    for pkg in to_remove:
        if is_installed(pkg):
            log.warning("   НЕ УДАЛЁН: %s", pkg)
            SKIPPED.append((pkg, "после удаления всё ещё установлен"))
        else:
            log.info("   OK: удалён %s", pkg)


# ---------- Этапы ----------

def stage_pacman_install():
    install_pacman(load_package_lists()["pacman"])


def stage_pacman_remove():
    remove_packages(load_package_lists()["pacman-remove"], "pacman-remove")


def stage_aur_install():
    install_aur(load_package_lists()["aur"])


def stage_aur_remove():
    remove_packages(load_package_lists()["aur-remove"], "aur-remove")


# ---------- Ручной ввод пакетов ----------

def ask_names(prompt):
    """Читает имена пакетов через пробел или запятую. Пустой ввод даёт пустой список."""
    raw = ask_text(prompt, default="")
    if not raw:
        return []

    names = []
    for token in raw.replace(",", " ").split():
        if not NAME_RE.match(token):
            log.warning(
                "   Некорректное имя «%s» пропущено "
                "(допустимы строчные латинские буквы, цифры и -_+.@)",
                token,
            )
            SKIPPED.append((token, "некорректное имя"))
            continue

        if token not in names:
            names.append(token)

    return names


def stage_manual_packages():
    """Ручной ввод: установка или удаление пакетов по имени. Enter — пропустить."""
    log.info("   Ручной ввод (Enter — пропустить этот шаг):")
    log.info("     1) установить пакеты pacman   2) удалить пакеты pacman")
    log.info("     3) установить пакеты AUR      4) удалить пакеты AUR")

    choice = ask_text("Ваш выбор [1-4, Enter = пропуск]: ", default="")

    if not choice:
        log.info("   Ручной ввод пропущен")
        return

    if choice not in ("1", "2", "3", "4"):
        log.warning("   Неверный выбор «%s», пропускаю.", choice)
        return

    names = ask_names("Имена пакетов через пробел: ")
    if not names:
        log.info("   Пустой ввод, ничего не делаю.")
        return

    if choice == "1":
        install_pacman(names)
    elif choice == "2":
        remove_packages(names, "ручной ввод")
    elif choice == "3":
        install_aur(names)
    else:
        remove_packages(names, "ручной ввод AUR")