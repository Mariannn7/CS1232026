#!/usr/bin/env python3
"""Перевірка ЛР 11: модуль ядра і програма eBPF, що рахують openat().

    python3 tools/lab11-test.py КАТАЛОГ [--output O] [--buildroot BR] [--bench]

КАТАЛОГ  — ваш каталог submissions/ГРУПА_Прізвище (у ньому br2-external/).
--output — каталог збирання Buildroot (той, що передавали як O=...):
           без нього перевіряється лише дерево, без образу.
--buildroot — дерево Buildroot: тоді ще й utils/check-package.
--accel  — auto (типово), kvm або tcg.
--bench  — наприкінці поміряти ціну openat() без спостерігача, з модулем
           і з програмою eBPF (кілька хвилин у TCG).

Образ запускається з -snapshot: файл rootfs.ext2 не змінюється, тож
навмисний Oops у t_oops не зачепить ваш образ.
Кожен тест друкує OK, FAIL з поясненням або SKIP; наприкінці — N/M.
"""
import argparse
import os
import re
import select
import shutil
import subprocess
import sys
import time

ap = argparse.ArgumentParser()
ap.add_argument("dir")
ap.add_argument("--output")
ap.add_argument("--buildroot")
ap.add_argument("--accel", choices=("auto", "kvm", "tcg"), default="auto",
                help="auto: KVM, якщо /dev/kvm доступний; tcg — примусово без KVM")
ap.add_argument("--timeout", type=int, default=600,
                help="скільки секунд чекати на login: (TCG без KVM повільний)")
ap.add_argument("--bench", action="store_true",
                help="поміряти ціну openat() без спостерігача, з модулем і з eBPF")
A = ap.parse_args()

D = os.path.abspath(A.dir)
EXT = os.path.join(D, "br2-external")
O = os.path.abspath(A.output) if A.output else None
results = []
INFO = {}

KERNEL_OPTS = ("CONFIG_BPF_SYSCALL", "CONFIG_BPF_JIT", "CONFIG_FTRACE_SYSCALLS",
               "CONFIG_KPROBES", "CONFIG_BPF_EVENTS", "CONFIG_DYNAMIC_DEBUG")
VERIFIER = {   # файл → що має сказати верифікатор
    "bad_null": r"invalid mem access 'map_value_or_null'",
    "bad_loop": r"BPF program is too large|infinite loop detected",
    "bad_userptr": r"invalid mem access 'scalar'",
}


class Skip(Exception):
    pass


def test(fn):
    name = fn.__name__
    try:
        msg = fn()
    except Skip as e:
        print(f"SKIP {name}: {e}")
        return fn
    except subprocess.TimeoutExpired:
        msg = "завис (timeout)"
    except FileNotFoundError as e:
        msg = f"немає файла {e.filename}"
    except Exception as e:  # noqa: BLE001
        msg = f"виняток {type(e).__name__}: {e}"
    ok = msg is None
    results.append(ok)
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + ("" if ok else f": {msg}"))
    sys.stdout.flush()
    return fn


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def code(*parts):
    """Текст C без коментарів: підказки в TODO не мають зараховуватися."""
    text = read(*parts)
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def config_lines(text):
    out = {}
    for line in text.splitlines():
        m = re.match(r"^((?:BR2|CONFIG)_\w+)=(.*)$", line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


# ───────────────────────── дерево br2-external ─────────────────────────

@test
def t_tree():
    desc = read(EXT, "external.desc")
    if not re.search(r"^name:\s*LAB11\s*$", desc, re.M):
        return "external.desc: має бути рядок 'name: LAB11'"
    cfg = read(EXT, "Config.in")
    for p in ("lab11-opencount", "lab11-bpf"):
        if f"package/{p}/Config.in" not in cfg:
            return f"Config.in не підключає package/{p}/Config.in"
    c = config_lines(read(EXT, "configs", "lab11_qemu_x86_64_defconfig"))
    for k in ("BR2_PACKAGE_LAB11_OPENCOUNT", "BR2_PACKAGE_LAB11_BPF", "BR2_PACKAGE_BPFTOOL"):
        if c.get(k) != "y":
            return f"у defconfig немає {k}=y"
    host = c.get("BR2_TARGET_GENERIC_HOSTNAME", "").strip('"')
    if not re.fullmatch(r"lab11-[a-z][a-z0-9-]*", host):
        return "BR2_TARGET_GENERIC_HOSTNAME: lab11-прізвище латиницею"
    INFO["hostname"] = host
    if not os.access(os.path.join(EXT, "board", "lab11", "rootfs-overlay", "etc",
                                  "init.d", "S09lab11"), os.X_OK):
        return "S09lab11 не виконуваний: tracefs не змонтується, libbpf не під'єднає програму"
    return None


@test
def t_fragment():
    c = config_lines(read(EXT, "board", "lab11", "linux.fragment"))
    if c.get("CONFIG_LOCALVERSION") != '"-lab11"':
        return 'у linux.fragment немає CONFIG_LOCALVERSION="-lab11"'
    for k in KERNEL_OPTS:
        if c.get(k) != "y":
            return f"у linux.fragment немає {k}=y (TODO 1)"
    return None


@test
def t_sources():
    src = code(EXT, "package", "lab11-opencount", "src", "lab11_opencount.c")
    if not re.search(r"module_param(_string)?\s*\(\s*target\b", src):
        return "lab11_opencount.c: немає параметра target (TODO 2)"
    if not re.search(r"module_param\s*\(\s*verbose\s*,\s*bool\s*,\s*0644\s*\)", src):
        return "lab11_opencount.c: verbose має бути bool з правами 0644 (TODO 2)"
    if len(re.findall(r"MODULE_PARM_DESC", src)) < 2:
        return "lab11_opencount.c: опишіть параметри MODULE_PARM_DESC (modinfo)"
    if "tracepoint_synchronize_unregister" not in src:
        return ("lab11_opencount.c: після tracepoint_probe_unregister треба дочекатися "
                "пробників, що вже виконуються (TODO 4)")
    bpf = code(EXT, "package", "lab11-bpf", "src", "opencount.bpf.c")
    if "bpf_probe_read_user_str" not in bpf:
        return "opencount.bpf.c: ім'я файла читають через bpf_probe_read_user_str (TODO 6)"
    mk = re.sub(r"#[^\n]*", " ", read(EXT, "package", "lab11-bpf", "src", "Makefile"))
    if "fixed_null.bpf.o" not in mk:
        return "Makefile: додайте verifier/fixed_null.bpf.o до BPF_OBJS (TODO 8)"
    return None


@test
def t_check_package():
    if not A.buildroot:
        raise Skip("не вказано --buildroot")
    cp = os.path.join(A.buildroot, "utils", "check-package")
    files = []
    for root, _, names in os.walk(EXT):
        for n in names:
            if n.endswith((".mk", ".in", ".desc")) or n.startswith("S") and "init.d" in root:
                files.append(os.path.join(root, n))
    r = subprocess.run([cp, "-b"] + files, capture_output=True, text=True, timeout=120)
    warn = re.search(r"(\d+) warnings generated", r.stdout + r.stderr)
    if r.returncode != 0 or not warn or warn.group(1) != "0":
        tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
        return "check-package: " + " | ".join(tail)
    return None


# ───────────────────────── результат збирання ─────────────────────────

def need_output():
    if not O:
        raise Skip("не вказано --output")


def elf_machine(path):
    with open(path, "rb") as fh:
        head = fh.read(20)
    if head[:4] != b"\x7fELF":
        return None
    return int.from_bytes(head[18:20], "little")


def kernel_build_dir():
    for d in sorted(os.listdir(os.path.join(O, "build"))):
        p = os.path.join(O, "build", d)
        if d.startswith("linux-") and not d.startswith("linux-headers") \
                and os.path.isfile(os.path.join(p, ".config")):
            return p
    return None


@test
def t_output_kernel():
    need_output()
    kd = kernel_build_dir()
    if not kd:
        return "немає build/linux-*/.config: ядро не зібрано"
    c = config_lines(read(kd, ".config"))
    for k in KERNEL_OPTS:
        if c.get(k) != "y":
            return f"у .config ядра {k} не y: фрагмент не застосовано (make linux-reconfigure)"
    rel = read(kd, "include", "config", "kernel.release").strip()
    INFO["release"] = rel
    if not rel.endswith("-lab11"):
        return f"версія ядра {rel}, а має закінчуватися на -lab11"
    for f in ("bzImage", "rootfs.ext2", "start-qemu.sh"):
        if not os.path.isfile(os.path.join(O, "images", f)):
            return f"немає images/{f}"
    INFO["bzImage"] = os.path.getsize(os.path.join(O, "images", "bzImage"))
    return None


@test
def t_output_files():
    need_output()
    rel = INFO.get("release")
    if not rel:
        raise Skip("невідома версія ядра (див. t_output_kernel)")
    t = os.path.join(O, "target")
    for name in ("lab11_opencount", "lab11_oops"):
        if not os.path.isfile(os.path.join(t, "lib", "modules", rel, "updates", name + ".ko")):
            return f"немає /lib/modules/{rel}/updates/{name}.ko"
    for f in ("usr/bin/opencount", "usr/bin/openbench", "usr/sbin/bpftool"):
        if elf_machine(os.path.join(t, f)) != 62:
            return f"{f} — не ELF x86-64"
    objs = ["opencount"] + [f"verifier/{v}" for v in list(VERIFIER) + ["fixed_null"]]
    for o in objs:
        p = os.path.join(t, "usr", "lib", "lab11", o + ".bpf.o")
        if elf_machine(p) != 247:
            return f"/usr/lib/lab11/{o}.bpf.o — не об'єкт BPF (EM_BPF = 247)"
    ko = os.path.join(t, "lib", "modules", rel, "updates", "lab11_opencount.ko")
    if shutil.which("modinfo"):
        r = subprocess.run(["modinfo", ko], capture_output=True, text=True)
        for p in ("target", "verbose"):
            if not re.search(rf"^parm:\s+{p}:\S", r.stdout, re.M):
                return f"modinfo: параметр {p} без опису (MODULE_PARM_DESC)"
    return None


@test
def t_output_cross():
    need_output()
    exe = os.path.join(O, "target", "usr", "bin", "opencount")
    r = subprocess.run(["readelf", "-p", ".comment", exe], capture_output=True, text=True)
    if "Buildroot" not in r.stdout:
        return ("у .comment opencount немає 'Buildroot': програму зібрано не тулчейном "
                "Buildroot (чи не скопіювали хостовий бінарник в overlay?)")
    return None


# ───────────────────────── запуск у QEMU ─────────────────────────

class Console:
    def __init__(self, images):
        self.buf = b""
        self.log = open(os.path.join(TMPLOG, "console.log"), "wb")
        cmd = ["qemu-system-x86_64", "-M", "pc", "-m", "256", "-smp", "2",
               "-kernel", os.path.join(images, "bzImage"),
               "-drive", f"file={os.path.join(images, 'rootfs.ext2')},if=virtio,format=raw",
               "-snapshot",
               "-append", "rootwait root=/dev/vda console=ttyS0",
               "-display", "none", "-serial", "stdio", "-monitor", "none",
               "-no-reboot",
               "-nic", "user,model=virtio-net-pci"]
        self.kvm = A.accel == "kvm" or (A.accel == "auto" and os.access("/dev/kvm", os.W_OK))
        if self.kvm:
            cmd[1:1] = ["-enable-kvm", "-cpu", "host"]
        self.t0 = time.monotonic()
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT)
        os.set_blocking(self.p.stdout.fileno(), False)

    def _pump(self, timeout):
        r, _, _ = select.select([self.p.stdout], [], [], timeout)
        if r:
            data = os.read(self.p.stdout.fileno(), 65536)
            if not data:
                raise EOFError("QEMU завершився")
            self.buf += data
            self.log.write(data)
            self.log.flush()

    def expect(self, pattern, timeout):
        rx = re.compile(pattern)
        end = time.monotonic() + timeout
        while True:
            m = rx.search(self.buf)
            if m:
                self.buf = self.buf[m.end():]
                return m
            left = end - time.monotonic()
            if left <= 0:
                raise subprocess.TimeoutExpired("expect", timeout)
            self._pump(min(left, 0.5))

    def send(self, text):
        self.p.stdin.write(text.encode())
        self.p.stdin.flush()

    def sh(self, cmd, timeout=120):
        """Виконати команду в оболонці гостя; повертає (код, вивід)."""
        self.send(f'echo "__B""EGIN__"; {cmd}; echo "__E""ND__$?"\n')
        self.expect(rb"__BEGIN__\r?\n", timeout)
        m = self.expect(rb"(?s)(.*?)__END__(\d+)", timeout)
        out = m.group(1).decode(errors="replace").replace("\r", "")
        return int(m.group(2)), out.strip()

    def close(self):
        if self.p.poll() is None:
            self.p.kill()
        self.p.wait()
        self.log.close()


TMPLOG = os.path.abspath(".")
VM = {}


def vm():
    need_output()
    if "con" in VM:
        return VM["con"]
    if "error" in VM:
        raise Skip("система не завантажилась (див. t_boot)")
    raise Skip("t_boot не запускався")


@test
def t_boot():
    need_output()
    if not shutil.which("qemu-system-x86_64"):
        return "немає qemu-system-x86_64: sudo apt install qemu-system-x86"
    con = Console(os.path.join(O, "images"))
    try:
        con.expect(rb"login: ", A.timeout)
    except Exception as e:  # noqa: BLE001
        VM["error"] = str(e)
        con.close()
        return f"не дочекалися login: ({type(e).__name__}); журнал консолі — console.log"
    INFO["accel"] = "KVM" if con.kvm else "TCG"
    try:
        con.send("root\n")
        m = con.expect(rb"Password: |# ", 60)
        if m.group(0).startswith(b"Password"):
            con.send("\n")
            con.expect(rb"# ", 60)
        con.send("stty -echo; dmesg -n 1; PS1='# '\n")
        con.expect(rb"# ", 30)
    except Exception as e:  # noqa: BLE001
        VM["error"] = str(e)
        con.close()
        return "login: є, але оболонки root немає; див. console.log"
    VM["con"] = con
    return None


@test
def t_kernel():
    con = vm()
    _, rel = con.sh("uname -r")
    if not rel.endswith("-lab11"):
        return f"uname -r = {rel}"
    code, out = con.sh("zcat /proc/config.gz | grep -E '^CONFIG_(BPF_SYSCALL|BPF_JIT|FTRACE_SYSCALLS)=y' | wc -l")
    if out != "3":
        return "у /proc/config.gz немає BPF_SYSCALL, BPF_JIT або FTRACE_SYSCALLS"
    code, _ = con.sh("test -r /sys/kernel/tracing/events/syscalls/sys_enter_openat/format")
    if code != 0:
        return "немає /sys/kernel/tracing/events/syscalls/sys_enter_openat (tracefs? S09lab11?)"
    code, out = con.sh("bpftool prog show >/dev/null && echo ok")
    if code != 0:
        return f"bpftool prog show: {out}"
    return None


def counters(con):
    _, out = con.sh("cat /proc/lab11_opencount")
    vals = dict(re.findall(r"^(\w+):\s+(\S+)$", out, re.M))
    return vals


@test
def t_module_load():
    con = vm()
    code, out = con.sh("modprobe lab11_opencount target=openbench")
    if code != 0:
        return f"modprobe lab11_opencount: {out}"
    code, out = con.sh("cat /sys/module/lab11_opencount/parameters/target "
                       "/sys/module/lab11_opencount/parameters/verbose")
    if out.split() != ["openbench", "N"]:
        return f"параметри в /sys/module: {out!r} (очікували openbench і N)"
    vals = counters(con)
    if vals.get("target") != "openbench":
        return f"/proc/lab11_opencount: {vals}"
    _, line = con.sh("dmesg | grep -m1 'lab11_opencount: '")
    if not line:
        return "у dmesg немає повідомлень з префіксом 'lab11_opencount: ' (pr_fmt)"
    _, taint = con.sh("cat /proc/sys/kernel/tainted")
    INFO["tainted_after_load"] = taint
    return None


@test
def t_module_count():
    con = vm()
    if "lab11_opencount" not in con.sh("cat /proc/modules")[1]:
        raise Skip("модуль не завантажено (t_module_load)")
    before = counters(con)
    code, out = con.sh("openbench -n 1000 -r 1 >/dev/null")
    after = counters(con)
    try:
        dm = int(after["matched"]) - int(before["matched"])
        dt = int(after["total"]) - int(before["total"])
    except (KeyError, ValueError):
        return f"/proc/lab11_opencount без total/matched: {after}"
    INFO["module_matched_1000"] = dm
    if not 1000 <= dm <= 1010:
        return f"openbench відкрив /dev/null 1000 разів, а matched зріс на {dm}"
    if dt < dm:
        return f"total зріс на {dt}, менше ніж matched ({dm})"
    return None


@test
def t_module_verbose():
    con = vm()
    if "lab11_opencount" not in con.sh("cat /proc/modules")[1]:
        raise Skip("модуль не завантажено (t_module_load)")
    con.sh("echo 1 > /sys/module/lab11_opencount/parameters/verbose")
    con.sh("openbench -n 3 -r 1 /etc/hostname >/dev/null")
    con.sh("echo 0 > /sys/module/lab11_opencount/parameters/verbose")
    _, out = con.sh("dmesg | grep -c 'lab11_opencount: openbench\\[[0-9]*\\] openat /etc/hostname'")
    if (out.splitlines() or ["0"])[-1] != "3":
        return f"після verbose=1 у dmesg {out} рядків 'openbench[PID] openat /etc/hostname', а треба 3"
    return None


@test
def t_module_unload():
    con = vm()
    if "lab11_opencount" not in con.sh("cat /proc/modules")[1]:
        raise Skip("модуль не завантажено (t_module_load)")
    # Вивантаження, поки інший процес активно відкриває файли.
    for _ in range(3):
        con.sh("openbench -n 20000 -r 1 >/dev/null & sleep 0.2; rmmod lab11_opencount; "
               "modprobe lab11_opencount target=openbench; wait", timeout=300)
    code, out = con.sh("rmmod lab11_opencount && test ! -e /proc/lab11_opencount && "
                       "dmesg | grep -c 'lab11_opencount: unloaded: total='")
    if code != 0:
        return f"rmmod не спрацював або /proc/lab11_opencount лишився: {out}"
    _, oops = con.sh("dmesg | grep -cE 'Oops|BUG:|general protection'")
    if oops.splitlines()[-1] != "0":
        return "після циклів rmmod/modprobe під навантаженням у dmesg є Oops/BUG"
    return None


def opencount_with(con, args, work, timeout=180):
    """Запустити opencount у фоні, виконати work і дочекатися його виводу."""
    cmd = (f"(opencount {args} > /tmp/oc.out 2> /tmp/oc.err &) ; "
           f"for i in $(seq 100); do grep -q attached /tmp/oc.err 2>/dev/null && break; sleep 0.2; done; "
           f"{work}; "
           f"while pidof opencount >/dev/null; do sleep 0.2; done; cat /tmp/oc.err /tmp/oc.out")
    return con.sh(cmd, timeout)


@test
def t_bpf_count():
    con = vm()
    code, out = con.sh("opencount -c")
    if code != 0:
        return f"верифікатор не прийняв opencount.bpf.o: {out[-300:]}"
    _, out = opencount_with(con, "-t openbench -d 6 -n 5", "openbench -n 1000 -r 1 >/dev/null")
    m = re.search(r"^openbench\s+(\d+)$", out, re.M)
    if not m:
        return f"у таблиці opencount немає рядка openbench: {out[-300:]!r}"
    n = int(m.group(1))
    INFO["bpf_openbench_1000"] = n
    if not 1000 <= n <= 1010:
        return f"openbench відкрив /dev/null 1000 разів, а в таблиці {n}"
    t = re.search(r"^total: (\d+) in (\d+) processes$", out, re.M)
    if not t or int(t.group(1)) < n:
        return "немає підсумку 'total: N in K processes' або він менший за рядок openbench"
    rows = [int(x) for x in re.findall(r"^\S.{0,15}\s+(\d+)$", out, re.M)]
    if rows != sorted(rows, reverse=True):
        return "таблиця не відсортована за спаданням"
    return None


@test
def t_bpf_events():
    con = vm()
    _, out = opencount_with(con, "-t openbench -v -d 5",
                            "openbench -n 3 -r 1 /etc/hostname >/dev/null")
    hits = re.findall(r"^openbench\s+\d+\s+/etc/hostname$", out, re.M)
    if len(hits) != 3:
        return f"подій 'openbench PID /etc/hostname' {len(hits)}, а треба 3"
    return None


@test
def t_verifier():
    con = vm()
    for name, rx in VERIFIER.items():
        # Журнал верифікатора буває мегабайти: на консоль — лише хвіст.
        t0 = time.monotonic()
        code, out = con.sh(f"opencount -c -o /usr/lib/lab11/verifier/{name}.bpf.o "
                           f"> /tmp/v.log 2>&1; rc=$?; tail -n 40 /tmp/v.log; (exit $rc)",
                           timeout=900)
        INFO[f"verify_{name}_s"] = round(time.monotonic() - t0, 1)
        if code == 0:
            return f"верифікатор прийняв {name}.bpf.o, а мав відмовити"
        if not re.search(rx, out):
            return f"{name}: у журналі верифікатора немає /{rx}/"
    code, out = con.sh("opencount -c -o /usr/lib/lab11/verifier/fixed_null.bpf.o 2>&1")
    if code != 0:
        return f"fixed_null.bpf.o верифікатор не прийняв (TODO 8): {out[-200:]}"
    return None


def median_ns(con, n=20000, r=5):
    code, out = con.sh(f"openbench -n {n} -r {r}", timeout=900)
    m = re.search(r"median ([\d.]+) ns", out)
    return float(m.group(1)) if m else None


@test
def t_bench():
    con = vm()
    if not A.bench:
        raise Skip("не вказано --bench")
    res = {}
    res["none"] = median_ns(con)
    con.sh("modprobe lab11_opencount")
    res["module"] = median_ns(con)
    con.sh("rmmod lab11_opencount; modprobe lab11_opencount target=openbench")
    res["module_target"] = median_ns(con)
    con.sh("rmmod lab11_opencount")
    for key, args, pre in (("bpf", "-d 600", ""),
                           ("bpf_nojit", "-d 600", "echo 0 > /proc/sys/net/core/bpf_jit_enable; ")):
        con.sh(f"{pre}(opencount {args} > /dev/null 2> /tmp/oc.err &); "
               "for i in $(seq 100); do grep -q attached /tmp/oc.err && break; sleep 0.2; done")
        res[key] = median_ns(con)
        con.sh("kill $(pidof opencount); while pidof opencount >/dev/null; do sleep 0.2; done; "
               "echo 1 > /proc/sys/net/core/bpf_jit_enable")
    res["none_again"] = median_ns(con)
    INFO["bench_ns"] = res
    if any(v is None for v in res.values()):
        return f"openbench не надрукував медіану: {res}"
    return None


@test
def t_oops():
    con = vm()
    code, out = con.sh("insmod /lib/modules/$(uname -r)/updates/lab11_oops.ko mode=1; echo rc=$?",
                       timeout=120)
    _, dm = con.sh("dmesg | grep -E 'BUG: kernel NULL pointer dereference|Oops' | head -2")
    if "NULL pointer" not in dm:
        return f"після mode=1 у dmesg немає 'BUG: kernel NULL pointer dereference': {dm!r}"
    _, taint = con.sh("cat /proc/sys/kernel/tainted")
    INFO["tainted_after_oops"] = taint
    if not int(taint) & 128:
        return f"tainted = {taint}: прапорця D (128, «був Oops») немає"
    code, _ = con.sh("echo alive")
    if code != 0:
        return "після Oops система не відповідає"
    return None


@test
def t_poweroff():
    con = vm()
    con.send("poweroff -f\n")
    try:
        con.p.wait(timeout=120)
    except subprocess.TimeoutExpired:
        con.close()
        return "після poweroff QEMU не завершився за 120 с"
    con.close()
    VM.pop("con", None)
    return None


if "con" in VM:
    VM["con"].close()

if INFO:
    print("\nВиміряно:")
    for k, v in INFO.items():
        if isinstance(v, dict):
            v = ", ".join(f"{a}={b}" for a, b in v.items())
        print(f"  {k:20} {v}")
print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if results and all(results) else 1)
