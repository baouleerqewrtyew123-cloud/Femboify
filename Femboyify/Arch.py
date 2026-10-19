#!/usr/bin/env python3
"""
Arch Setup 2.2 — точка входа.

  sudo python3 Arch.py              установка в терминале
  sudo python3 Arch.py --gui        установка с окном и котиком
  python3 Arch.py --check           проверка файлов и плана, система не меняется
  python3 Arch.py --launcher        создать ярлык Arch Setup в меню KDE
  python3 Arch.py --help            эта справка

Файлы arch_*.py лежат в одной папке с Arch.py. Запускать можно из любой папки.
"""

import importlib
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

MODULE_FILES = ["arch_core.py", "arch_system.py", "arch_packages.py", "arch_desktop.py"]
MODULE_NAMES = ["arch_core", "arch_system", "arch_packages", "arch_desktop"]
OPTIONAL_FILES = ["arch_gui.py"]
COMMANDS_REQUIRED = ["pacman", "pacman-conf", "runuser", "locale-gen", "locale",
                     "git", "makepkg", "chsh", "fc-cache"]
COMMANDS_OPTIONAL = ["yay", "fish", "kwriteconfig6", "mpvpaper", "fastfetch", "uwufetch", "konsole"]
LAUNCHER_REL = os.path.join(".local", "share", "applications", "arch-setup.desktop")

HINTS = [
    ("нужны права root", "Запустите через sudo: sudo python3 Arch.py"),
    ("не удалось определить обычного пользователя",
     "Запускайте sudo из своей учётной записи, а не из-под root."),
    ("pacman", "Проверьте интернет и базы пакетов: sudo pacman -Syy, затем повторите. "
               "Точный текст ошибки pacman есть в журнале, строки с «|»."),
    ("yay", "Проверьте yay: yay --version. AUR может быть временно недоступен, повторите позже."),
    ("makepkg", "Сборка AUR-пакета не удалась. В журнале смотрите вывод makepkg, часто не хватает зависимости."),
    ("локал", "Проверьте /etc/locale.gen и выполните locale-gen вручную."),
    ("не является клоном", "Переименуйте или удалите каталог сборки из сообщения и запустите снова."),
    ("не найден", "Проверьте, что нужный файл или программа установлены. Путь указан в тексте ошибки."),
    ("ошибка команды", "Команда завершилась с ошибкой. Код и вывод команды есть в журнале."),
]


def explain(message):
    """Вероятная причина и следующий шаг по тексту ошибки."""
    low = message.lower()
    for key, advice in HINTS:
        if key in low:
            return advice
    return "Откройте журнал и найдите последние строки с [ERROR]: там команда, код возврата и вывод."


# ---------- БЛОК 00 — ЗАГРУЗКА И ПРОВЕРКА ----------

def load_modules():
    """Импортирует модули. При ошибке поднимает RuntimeError с файлом и строкой."""
    try:
        mods = {name: importlib.import_module(name) for name in MODULE_NAMES}
    except Exception as e:
        frames = traceback.extract_tb(e.__traceback__)
        where = f"{frames[-1].filename}, строка {frames[-1].lineno}" if frames else "неизвестно"
        raise RuntimeError(f"{type(e).__name__}: {e} (где: {where})")
    return mods["arch_core"], mods["arch_system"], mods["arch_packages"], mods["arch_desktop"]


def build_stages(system, packages, desktop):
    """Список этапов: (блок, название этапа, функция). Порядок важен."""
    b1 = "БЛОК 01 — ПРОВЕРКА СИСТЕМЫ"
    b2 = "БЛОК 02 — ЛОКАЛИ И РЕПОЗИТОРИИ"
    b3 = "БЛОК 03 — ПАКЕТЫ PACMAN"
    b4 = "БЛОК 04 — AUR И YAY"
    b5 = "БЛОК 05 — FISH И ТЕРМИНАЛ"
    b6 = "БЛОК 06 — ОФОРМЛЕНИЕ И ПРИЛОЖЕНИЯ"
    return [
        (b1, "Проверка системы", system.stage_checks),
        (b1, "Проверка инструментов", system.stage_check_tools),
        (b2, "Локали", system.stage_locales),
        (b2, "Репозитории", system.stage_repositories),
        (b3, "Обновление системы", system.stage_system_update),
        (b3, "Удаление vim (по согласию)", system.stage_remove_vim),
        (b3, "Pacman: установка из списка", packages.stage_pacman_install),
        (b3, "Pacman: удаление из списка", packages.stage_pacman_remove),
        (b3, "Ручной ввод пакетов pacman и AUR", packages.stage_manual_packages),
        (b4, "Зависимости сборки (base-devel, git)", system.stage_aur_prereqs),
        (b4, "Сборка и установка yay", system.stage_install_yay),
        (b4, "AUR: установка из списка", packages.stage_aur_install),
        (b4, "AUR: удаление из списка", packages.stage_aur_remove),
        (b5, "Fish: установка и шелл по умолчанию", desktop.stage_fish),
        (b5, "Вывод при запуске fish (fastfetch / uwufetch / ничего)", desktop.stage_fish_fetch),
        (b5, "Команды uwu и www", system.stage_sudo_aliases),
        (b6, "Оформление KDE (Catppuccin Mocha Flamingo)", desktop.stage_kde_theme),
        (b6, "LibreOffice и шрифты", desktop.stage_office_fonts),
        (b6, "Видеообои mpvpaper", desktop.stage_wallpaper),
    ]


# ---------- Режим проверки ----------

def find_block_for_line(lines, lineno):
    start = min(max(lineno, 1), len(lines)) - 1
    for i in range(start, -1, -1):
        s = lines[i]
        if s.startswith("def ") or s.startswith("# ----") or s.startswith("STAGES"):
            return s.strip()
    return "начало файла"


def check_syntax():
    """Компилирует каждый файл без запуска. Возвращает число файлов с ошибками."""
    bad = 0
    for fn in MODULE_FILES + ["Arch.py"] + OPTIONAL_FILES:
        path = SCRIPT_DIR / fn
        if not path.is_file():
            if fn in OPTIONAL_FILES:
                print(f"  необязательный файл не найден: {fn} (нужен только для --gui)")
            else:
                print(f"  НЕТ ФАЙЛА: {path}")
                bad += 1
            continue
        src = path.read_text(encoding="utf-8")
        try:
            compile(src, str(path), "exec")
            print(f"  OK: {fn}")
        except SyntaxError as e:
            bad += 1
            lines = src.splitlines()
            lineno = e.lineno or 1
            text = lines[lineno - 1].strip() if lineno - 1 < len(lines) else ""
            print(f"  ОШИБКА СИНТАКСИСА: {fn}, строка {lineno}: {e.msg}")
            print(f"     строка: {text}")
            print(f"     предполагаемый блок: {find_block_for_line(lines, lineno)}")
    return bad


def check_commands():
    missing_required = 0
    for cmd in COMMANDS_REQUIRED:
        if shutil.which(cmd):
            print(f"  OK: {cmd}")
        else:
            missing_required += 1
            print(f"  НЕТ (обязательна): {cmd}")
    for cmd in COMMANDS_OPTIONAL:
        status = "OK" if shutil.which(cmd) else "нет (нужна только для своего этапа)"
        print(f"  {cmd}: {status}")
    return missing_required


def print_plan(core, packages, stages):
    home, _, _ = core.get_real_user()
    path = os.path.join(home, packages.PACKAGE_LIST_REL)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            lists, problems = packages.parse_package_list(f.read())
        print(f"  Список пакетов: {path}")
        for key in ("pacman", "pacman-remove", "aur", "aur-remove"):
            print(f"    [{key}]: {', '.join(lists[key]) or '—'}")
        for p in problems:
            print(f"    предупреждение: {p}")
    else:
        print(f"  Файл списка будет создан: {path}")
    print("  Этапы:")
    last_block = None
    for block, title, _ in stages:
        if block != last_block:
            print(f"  {block}")
            last_block = block
        print(f"     - {title}")


def run_check():
    print("=" * 50)
    print("  Arch Setup — режим проверки (система НЕ меняется)")
    print("=" * 50)

    print("\n[1] Синтаксис файлов")
    if check_syntax():
        print("\nЕсть синтаксические ошибки. Исправьте их и повторите: python3 Arch.py --check")
        return 1

    print("\n[2] Импорт модулей")
    try:
        core, system, packages, desktop = load_modules()
    except RuntimeError as e:
        print(f"  ОШИБКА ИМПОРТА: {e}")
        print(f"  Проверьте, что все файлы лежат в папке: {SCRIPT_DIR}")
        return 1
    print("  OK: все модули импортируются")

    print("\n[3] Команды системы")
    if check_commands():
        print("\nНе хватает обязательных программ. Установите их до запуска установки.")
        return 1

    print("\n[4] План установки")
    stages = build_stages(system, packages, desktop)
    if not all(callable(func) for _, _, func in stages):
        print("  ОШИБКА: в списке этапов есть не функции. Проверьте Arch.py.")
        return 1
    print_plan(core, packages, stages)

    print("\nПроверка завершена. Система не изменена.")
    return 0


# ---------- Ярлык ----------

def install_launcher(core):
    home, uid, gid = core.get_real_user()
    script = SCRIPT_DIR / "Arch.py"
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Arch Setup\n"
        "Comment=Настройка Arch Linux и KDE Plasma\n"
        f'Exec=konsole --hold -e sudo python3 "{script}"\n'
        "Icon=system-software-install\n"
        "Terminal=false\n"
        "Categories=System;\n"
    )
    if not shutil.which("konsole"):
        print("ВНИМАНИЕ: konsole не найден. Измените Exec в ярлыке на свой терминал.")
    path = os.path.join(home, LAUNCHER_REL)
    try:
        core.write_user_file(path, content, uid, gid, 0o644)
    except core.StageError as e:
        print(f"ОШИБКА: {e}")
        return 1
    print(f"Ярлык создан: {path}")
    print("Пароль sudo будет запрошен в открывшемся терминале.")
    return 0


# ---------- Выполнение этапов (общее для терминала и окна) ----------

def write_report(core, log_path, status, code):
    home, uid, gid = core.get_real_user()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(home, "Desktop", f"Arch-setup-report-{stamp}.txt")
    lines = [
        f"{core.PROGRAM_NAME} {core.PROGRAM_VERSION}",
        f"Дата: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Итог: {status} (код {code})",
        "",
    ]
    if core.SKIPPED:
        lines.append("Не установлено или пропущено:")
        lines += [f"  - {name}: {reason}" for name, reason in core.SKIPPED]
    else:
        lines.append("Пропусков и ошибок нет.")
    lines += ["", f"Подробный журнал: {log_path}"]
    core.write_user_file(path, "\n".join(lines) + "\n", uid, gid, 0o644)
    core.log.info("Отчёт записан: %s", path)


def _notify(on_event, kind, index, title):
    if on_event is None:
        return
    try:
        on_event(kind, index, title)
    except Exception:
        pass


def execute(core, stages, log_path, on_event=None):
    """
    Выполняет этапы по порядку. Останавливается на первой критической ошибке.
    Возвращает словарь: code, status, block, stage, message, advice, log_path.
    Коды: 0 успех, 2 с пропусками, 1 ошибка, 130 отмена.
    """
    log = core.log
    core.CANCEL_EVENT.clear()
    core.SKIPPED.clear()
    total = len(stages)
    result = {"code": 1, "status": "не завершено", "block": "—", "stage": "—",
              "message": "", "advice": "", "log_path": log_path}
    index = -1
    try:
        for index, (block, title, func) in enumerate(stages):
            core.CURRENT["block"] = block
            core.CURRENT["stage"] = title
            result["block"], result["stage"] = block, title
            log.info("")
            log.info("%s", block)
            log.info("[%d/%d] %s", index + 1, total, title)
            _notify(on_event, "start", index, title)

            before = core.CHANGES["count"]
            func()
            changed = core.CHANGES["count"] > before
            log.info("   Итог этапа: %s",
                     "внесены изменения" if changed else "изменений не понадобилось")
            _notify(on_event, "done" if changed else "skip", index, title)

        log.info("")
        if core.SKIPPED:
            result.update(code=2, status="завершено с пропусками")
            log.warning("Не установлено или пропущено (%d):", len(core.SKIPPED))
            for name, reason in core.SKIPPED:
                log.warning("   - %s: %s", name, reason)
        else:
            result.update(code=0, status="успешно")
            log.info("Все этапы выполнены успешно.")

    except (core.UserCancelled, KeyboardInterrupt):
        result.update(code=130, status="отменено пользователем",
                      message="Установка отменена пользователем.")
        log.warning("Отмена: установка остановлена, дочерние процессы завершены.")
        _notify(on_event, "cancel", index, result["stage"])

    except core.StageError as e:
        msg = str(e)
        result.update(code=1, status="остановлено с ошибкой", message=msg, advice=explain(msg))
        log.error("КРИТИЧЕСКАЯ ОШИБКА в блоке «%s», этап «%s»", result["block"], result["stage"])
        log.error("Причина: %s", msg)
        log.error("Вероятная причина и что делать: %s", result["advice"])
        log.error("Полный журнал с командами и выводом: %s", log_path)
        _notify(on_event, "fail", index, result["stage"])

    except Exception as e:
        result.update(code=1, status="внутренняя ошибка", message=f"внутренняя ошибка: {e}",
                      advice="Это ошибка в коде программы. Пришлите журнал целиком.")
        log.exception("Внутренняя ошибка в блоке «%s», этап «%s»", result["block"], result["stage"])
        _notify(on_event, "fail", index, result["stage"])

    finally:
        try:
            write_report(core, log_path, result["status"], result["code"])
        except Exception as e:
            log.warning("Не удалось записать отчёт: %s", e)
    return result


def run_install(core, stages):
    """Установка в терминале."""
    try:
        log_path = core.setup_logging()
    except OSError as e:
        print(f"ОШИБКА: не удалось создать лог-файл: {e}")
        return 1

    log = core.log
    log.info("=" * 50)
    log.info("  %s — версия %s", core.PROGRAM_NAME, core.PROGRAM_VERSION)
    log.info("=" * 50)
    log.info("Полный журнал: %s", log_path)
    log.info("=== Новый запуск ===")

    if not core.ask_yes_no("\nНачать установку? [y/N]: "):
        log.info("Отмена пользователем до начала. Система не изменена.")
        return 0

    result = execute(core, stages, log_path)
    log.info("Итог: %s (код %d). Журнал: %s", result["status"], result["code"], log_path)
    return result["code"]


# ---------- Точка входа ----------

def main(argv):
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    known = {"--check", "--launcher", "--gui"}
    unknown = [a for a in argv[1:] if a not in known]
    if unknown:
        print(f"Неизвестный параметр: {' '.join(unknown)}. См. --help")
        return 2

    if "--check" in argv:
        return run_check()

    try:
        core, system, packages, desktop = load_modules()
    except RuntimeError as e:
        print(f"ОШИБКА ИМПОРТА: {e}")
        print("Выполните: python3 Arch.py --check (покажет файл и строку).")
        return 3

    if "--launcher" in argv:
        return install_launcher(core)

    stages = build_stages(system, packages, desktop)

    if "--gui" in argv:
        try:
            import arch_gui
        except ImportError as e:
            print(f"ОШИБКА: {e}. Для окна нужен файл arch_gui.py и PySide6 (sudo pacman -S pyside6).")
            return 3
        return arch_gui.run(core, stages, lambda st, lp, cb: execute(core, st, lp, cb))

    return run_install(core, stages)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        print("\nПрервано пользователем.")
        sys.exit(130)