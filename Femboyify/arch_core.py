"""
БЛОК 00 — ОБЩИЕ ФУНКЦИИ (arch_core.py)
Журнал, запуск команд, интерактивные программы с записью вывода в лог,
отмена, вопросы, работа с файлами. Этапов установки здесь нет.
"""

import codecs
import fcntl
import logging
import os
import pty
import pwd
import re
import select
import shutil
import signal
import subprocess
import sys
import termios
import threading
import time
import urllib.parse

PROGRAM_NAME = "Arch Setup"
PROGRAM_VERSION = "2.2 (подробный журнал, GUI)"
OS_RELEASE_PATH = "/etc/os-release"
LOG_FILE_NAME = "Arch-setup.log"
COMMAND_TIMEOUT = 900
SECRET_MARKERS = ("password", "passwd", "token", "secret")
SUDO_BIN = "/usr/bin/sudo"
AUR_CACHE_SUBDIR = os.path.join(".cache", "arch-setup", "aur")

log = logging.getLogger("arch_setup")
SKIPPED = []
CANCEL_EVENT = threading.Event()
CURRENT = {"block": "—", "stage": "—"}
CHANGES = {"count": 0}
PROMPTER = None           # функция(вопрос) -> строка или None (None = отмена). Для GUI.
INTERACTIVE_ANSWER = None  # функция(приглашение) -> строка или None. Для GUI.


class StageError(Exception):
    """Ошибка, которая останавливает этап и установку."""


class UserCancelled(Exception):
    """Пользователь отменил установку. Это не ошибка."""


def mark_change():
    """Отмечает, что этап реально изменил систему или файлы."""
    CHANGES["count"] += 1


# ---------- БЛОК 00.1 — ПОЛЬЗОВАТЕЛЬ ----------

def get_real_user():
    """(домашняя папка, uid, gid) пользователя, который запустил скрипт через sudo."""
    name = os.environ.get("SUDO_USER", "")
    if os.geteuid() == 0 and name:
        try:
            pw = pwd.getpwnam(name)
            return pw.pw_dir, pw.pw_uid, pw.pw_gid
        except KeyError:
            pass
    return os.path.expanduser("~"), os.geteuid(), os.getegid()


def get_target_user():
    """(имя, запись pwd) обычного пользователя или None, если запуск не через sudo."""
    name = os.environ.get("SUDO_USER", "")
    if not name or name == "root":
        return None
    try:
        return name, pwd.getpwnam(name)
    except KeyError:
        return None


def require_target_user():
    target = get_target_user()
    if target is None:
        raise StageError(
            "не удалось определить обычного пользователя. "
            "Запускайте: sudo python3 Arch.py из своей учётной записи."
        )
    return target


def get_build_user():
    """(имя, домашняя папка) пользователя для сборки из AUR. Сборка идёт не от root."""
    name, pw = require_target_user()
    return name, pw.pw_dir


def priv_cmd(cmd):
    """Команда с правами root. Если скрипт уже от root, sudo не добавляется."""
    if os.geteuid() == 0:
        return list(cmd)
    return [SUDO_BIN, *cmd]


def user_env_cmd(name, home, uid, cmd):
    """Команда от имени пользователя с доступом к его сессии (DBus, XDG_RUNTIME_DIR)."""
    runtime = f"/run/user/{uid}"
    return [
        "runuser", "-u", name, "--", "env",
        f"HOME={home}", f"USER={name}",
        f"XDG_RUNTIME_DIR={runtime}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/bus",
        *cmd,
    ]


# ---------- БЛОК 00.2 — ЖУРНАЛ ----------

class _BlockFilter(logging.Filter):
    """Добавляет в каждую запись текущий блок и этап, чтобы лог показывал, где это случилось."""

    def filter(self, record):
        record.block = CURRENT["block"]
        record.stage = CURRENT["stage"]
        return True


def setup_logging():
    """Журнал в ~/Desktop/Arch-setup.log (полный) и вывод в терминал (кратко)."""
    home, uid, gid = get_real_user()
    desktop = os.path.join(home, "Desktop")
    if not os.path.isdir(desktop):
        os.makedirs(desktop)
        os.chown(desktop, uid, gid)

    log_path = os.path.join(desktop, LOG_FILE_NAME)
    is_new = not os.path.exists(log_path)

    log.setLevel(logging.DEBUG)
    log.propagate = False
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(block)s] %(message)s", "%Y-%m-%d %H:%M:%S"
    ))
    fh.addFilter(_BlockFilter())
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(fh)
    log.addHandler(ch)

    if is_new:
        os.chown(log_path, uid, gid)
    log.debug("Запуск: %s %s, пользователь sudo: %s",
              PROGRAM_NAME, PROGRAM_VERSION, os.environ.get("SUDO_USER", "нет"))
    return log_path


# ---------- БЛОК 00.3 — ЗАПУСК КОМАНД ----------

def mask_command(cmd):
    """Скрывает значения аргументов, похожих на пароли и токены."""
    masked = []
    hide_next = False
    for arg in cmd:
        if hide_next:
            masked.append("***")
            hide_next = False
            continue
        low = arg.lower()
        if any(marker in low for marker in SECRET_MARKERS):
            if "=" in arg:
                masked.append(arg.split("=", 1)[0] + "=***")
            else:
                masked.append(arg)
                hide_next = True
        else:
            masked.append(arg)
    return masked


def build_cmd(cmd, run_as):
    """Если run_as=(имя, домашняя папка), оборачивает команду в runuser."""
    if run_as is None:
        return list(cmd), None
    name, home = run_as
    return ["runuser", "-u", name, "--", "env", f"HOME={home}", f"USER={name}", *cmd], home


def kill_group(proc):
    """Останавливает процесс и всех его потомков (вся группа). Сначала мягко, потом жёстко."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.wait()


def _wait_with_checks(proc, shown):
    """Ждёт завершения команды, проверяя отмену и таймаут. Возвращает (stdout, stderr)."""
    started = time.monotonic()
    try:
        while True:
            try:
                return proc.communicate(timeout=0.3)
            except subprocess.TimeoutExpired:
                if CANCEL_EVENT.is_set():
                    kill_group(proc)
                    log.warning("   Команда остановлена пользователем: %s", shown)
                    raise UserCancelled()
                if time.monotonic() - started > COMMAND_TIMEOUT:
                    kill_group(proc)
                    log.error("Превышено время ожидания (%d с): %s", COMMAND_TIMEOUT, shown)
                    raise StageError("команда зависла и была остановлена по таймауту")
    except KeyboardInterrupt:
        kill_group(proc)
        log.warning("   Остановлено по Ctrl+C: %s", shown)
        raise UserCancelled()


def run_command(cmd, description, check=True, run_as=None, cwd=None):
    """
    Запускает команду без вопросов, захватывает вывод и пишет всё в лог:
    команду, код возврата, время, stdout и stderr.
    При check=False ненулевой код возврата не считается ошибкой.
    """
    shown = " ".join(mask_command(cmd))
    full, default_cwd = build_cmd(cmd, run_as)
    log.info("-> %s", description)
    log.debug("Команда: %s", shown)
    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            full, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=cwd or default_cwd, start_new_session=True,
        )
    except FileNotFoundError:
        log.error("Программа не найдена: %s", cmd[0])
        raise StageError(f"программа {cmd[0]} не найдена. Установите её или проверьте PATH.")

    out, err = _wait_with_checks(proc, shown)
    elapsed = time.monotonic() - start
    log.debug("Код возврата: %d (время: %.1f с)", proc.returncode, elapsed)
    if out and out.strip():
        log.debug("Вывод:\n%s", out.rstrip())
    if err and err.strip():
        log.debug("Ошибки (stderr):\n%s", err.rstrip())

    result = subprocess.CompletedProcess(full, proc.returncode, out or "", err or "")
    if proc.returncode != 0:
        if not check:
            log.info("   Результат: код %d (не найдено или не установлено, это ожидаемо)", proc.returncode)
            return result
        log.error("Команда завершилась с ошибкой (код %d): %s", proc.returncode, shown)
        raise StageError(f"ошибка команды (код {proc.returncode}): {shown}")

    log.info("   OK")
    return result


def _new_controlling_tty():
    """Выполняется в дочернем процессе: новая сессия и терминал pty как управляющий."""
    os.setsid()
    try:
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    except OSError:
        pass


def looks_like_prompt(text):
    """Похоже ли, что программа ждёт ответа: [y/N], двоеточие или вопросительный знак в конце."""
    tail = text.replace("\r", "\n").split("\n")[-1].rstrip()
    if re.search(r"\[[yYnN]/[yYnN]\]", tail):
        return True
    return tail.endswith((":", "?")) or tail.lower().endswith("password")


def _log_pty_line(line):
    line = line.replace("\r", "").rstrip()
    if line.strip():
        log.debug("| %s", line)


def _pump(proc, master):
    """
    Передаёт вывод программы на экран и в лог. Ввод с клавиатуры передаёт программе.
    В режиме GUI вопросы задаёт INTERACTIVE_ANSWER, а не терминал.
    """
    interactive = INTERACTIVE_ANSWER is not None
    stdin_fd = None
    if not interactive and sys.stdin is not None and sys.stdin.isatty():
        stdin_fd = sys.stdin.fileno()
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    buf = ""
    last_data = time.monotonic()
    last_prompt = None

    while True:
        if CANCEL_EVENT.is_set():
            kill_group(proc)
            log.warning("   Команда остановлена пользователем.")
            raise UserCancelled()

        watch = [master] + ([stdin_fd] if stdin_fd is not None else [])
        ready, _, _ = select.select(watch, [], [], 0.3)

        if master in ready:
            try:
                data = os.read(master, 4096)
            except OSError:
                data = b""  # программа закрыла терминал
            if not data:
                break
            text = decoder.decode(data)
            sys.stdout.write(text)
            sys.stdout.flush()
            buf += text
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                _log_pty_line(line)
            last_data = time.monotonic()
            continue

        if stdin_fd is not None and stdin_fd in ready:
            data = os.read(stdin_fd, 1024)
            if data:
                os.write(master, data)
            else:
                stdin_fd = None
            continue

        idle = time.monotonic() - last_data
        if proc.poll() is not None and idle > 2:
            break
        if interactive and buf and idle >= 0.6 and buf != last_prompt and looks_like_prompt(buf):
            question = buf.rstrip()
            _log_pty_line(buf)
            last_prompt = buf
            answer = INTERACTIVE_ANSWER(question)
            if answer is None or CANCEL_EVENT.is_set():
                kill_group(proc)
                log.warning("   Отмена во время вопроса программы.")
                raise UserCancelled()
            os.write(master, (answer + "\n").encode("utf-8"))
            buf = ""
            last_data = time.monotonic()

    if buf.strip():
        _log_pty_line(buf)
    return proc.wait()


def run_interactive(cmd, description, run_as=None, cwd=None):
    """
    Команда с вопросами (pacman, makepkg, yay, sudo). Вывод виден на экране и пишется в лог
    построчно со знаком «|». Ответы на вопросы в лог не пишутся.
    """
    shown = " ".join(mask_command(cmd))
    full, default_cwd = build_cmd(cmd, run_as)
    log.info("-> %s", description)
    log.debug("Команда: %s", shown)
    log.info("   Вопросы и вывод программы показаны на экране и записаны в лог (строки с «|»).")

    master, slave = pty.openpty()
    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            full, stdin=slave, stdout=slave, stderr=slave,
            cwd=cwd or default_cwd, close_fds=True, preexec_fn=_new_controlling_tty,
        )
    except FileNotFoundError:
        os.close(master)
        os.close(slave)
        log.error("Программа не найдена: %s", cmd[0])
        raise StageError(f"программа {cmd[0]} не найдена. Установите её или проверьте PATH.")
    os.close(slave)

    try:
        code = _pump(proc, master)
    except KeyboardInterrupt:
        kill_group(proc)
        log.warning("   Остановлено по Ctrl+C: %s", shown)
        raise UserCancelled()
    finally:
        os.close(master)

    elapsed = time.monotonic() - start
    log.debug("Код возврата: %d (время: %.1f с)", code, elapsed)
    if code != 0:
        log.error("Команда завершилась с ошибкой (код %d): %s", code, shown)
        raise StageError(f"ошибка команды (код {code}): {shown}")
    mark_change()
    log.info("   OK")


# ---------- БЛОК 00.4 — ВОПРОСЫ ПОЛЬЗОВАТЕЛЮ ----------

def _read_answer(question):
    """Получает ответ через PROMPTER (GUI) или input() (терминал). None означает отмену."""
    try:
        answer = PROMPTER(question) if PROMPTER is not None else input(question)
    except EOFError:
        return ""
    if answer is None:
        raise UserCancelled()
    return answer


def ask_yes_no(question):
    """True только при явном согласии."""
    return _read_answer(question).strip().lower() in ("y", "yes", "д", "да")


def ask_text(question, default=None):
    """Текст ответа. Пустой ответ даёт default."""
    answer = _read_answer(question).strip()
    return answer or default


def clean_path_input(text):
    """Приводит путь из терминала: убирает кавычки, file:// и экранирование пробелов."""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1]
    if text.startswith("file://"):
        text = urllib.parse.unquote(text[len("file://"):])
    text = text.replace("\\ ", " ")
    return os.path.expanduser(text)


def is_installed(pkg):
    """True, если пакет установлен (pacman -Q). Ничего не меняет."""
    result = run_command(["pacman", "-Q", pkg], f"Проверка: установлен ли {pkg}", check=False)
    return result.returncode == 0


# ---------- БЛОК 00.5 — ФАЙЛЫ ----------

def make_backup(path):
    """Резервная копия рядом с файлом: имя.arch-setup-ДАТА.bak."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = f"{path}.arch-setup-{stamp}.bak"
    if os.path.exists(backup):
        raise StageError(f"резервная копия уже существует: {backup}")
    try:
        shutil.copy2(path, backup)
    except OSError as e:
        raise StageError(f"не удалось создать резервную копию {path}: {e}")
    return backup


def backup_user_file(path, uid, gid):
    """Резервная копия файла пользователя. Владельцем копии становится пользователь."""
    backup = make_backup(path)
    try:
        os.chown(backup, uid, gid)
    except OSError as e:
        raise StageError(f"не удалось передать копию {backup} владельцу: {e}")
    return backup


def write_file_atomic(path, lines):
    """Системный файл: запись через временный файл, права сохраняются."""
    tmp = path + ".arch-setup.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(lines)
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except OSError as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise StageError(f"не удалось записать {path}: {e}")
    mark_change()


def ensure_user_dir(folder, uid, gid):
    """Создаёт каталог и недостающих родителей с владельцем пользователя."""
    created = []
    cur = folder
    while cur and not os.path.isdir(cur):
        created.append(cur)
        cur = os.path.dirname(cur)
    for d in reversed(created):
        os.mkdir(d)
        os.chown(d, uid, gid)


def write_user_file(path, content, uid, gid, mode):
    """
    Пишет файл пользователя. Возвращает False, если содержимое уже такое же.
    Если файл отличается, сначала делает резервную копию.
    """
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                if f.read() == content:
                    return False
        except OSError as e:
            raise StageError(f"не удалось прочитать {path}: {e}")
        backup = backup_user_file(path, uid, gid)
        log.info("   Резервная копия: %s", backup)
    try:
        ensure_user_dir(os.path.dirname(path), uid, gid)
        tmp = path + ".arch-setup.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.chown(tmp, uid, gid)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except OSError as e:
        raise StageError(f"не удалось записать {path}: {e}")
    mark_change()
    return True