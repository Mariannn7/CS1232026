# Лабораторна робота № 11

**Модуль ядра і програма eBPF: лічильник openat() двома способами**

Повний текст роботи — у Google Classroom. Тут лише те, що потрібно для здачі.

## Що здається

```
lab11/submissions/ГРУПА_Прізвище/
├── br2-external/                               ← скопіювати з lab11/starter/
│   ├── external.desc, external.mk, Config.in   ← без змін
│   ├── configs/lab11_qemu_x86_64_defconfig     — ваші hostname і banner (make savedefconfig)
│   ├── board/lab11/
│   │   ├── linux.fragment                      — TODO 1
│   │   ├── post-image.sh                       ← без змін
│   │   └── rootfs-overlay/
│   │       ├── etc/init.d/S09lab11             ← без змін, виконуваний
│   │       └── root/.ssh/authorized_keys       — ваш ПУБЛІЧНИЙ ключ
│   └── package/
│       ├── lab11-opencount/src/lab11_opencount.c   — TODO 2, 3, 4
│       └── lab11-bpf/src/
│           ├── opencount.bpf.c                 — TODO 5, 6
│           ├── opencount.c                     — TODO 7
│           ├── Makefile                        — TODO 8
│           └── verifier/fixed_null.bpf.c       — TODO 8
└── REPORT.md
```

Стенд — Buildroot 2026.08.1 з ЛР 10 у новому каталозі збирання `~/br-lab11`. Додатково
до пакетів ЛР 10 потрібен `clang` (ним збирається байт-код BPF). Linux на x86-64 або WSL 2;
macOS і Windows на ARM не підходять. Збирання образу — домашнє завдання до заняття.

Модуль `lab11_oops` навмисно ламає ядро: завантажуйте його лише в QEMU з `-snapshot`.

## Збирання, перевірка й вимірювання

Команди виконуються з вашого каталогу `lab11/submissions/ГРУПА_Прізвище/`.

```bash
cd ~/buildroot
make O=~/br-lab11 BR2_EXTERNAL=$OLDPWD/br2-external lab11_qemu_x86_64_defconfig
make -C ~/br-lab11 menuconfig && make -C ~/br-lab11 savedefconfig
make -C ~/br-lab11
cd -

python3 ../../../tools/lab11-test.py . --output ~/br-lab11 \
    --buildroot ~/buildroot --bench                          # має бути 19/19

make -C ~/br-lab11 lab11-opencount-rebuild lab11-bpf-rebuild all   # після зміни коду
make -C ~/br-lab11 linux-reconfigure lab11-opencount-rebuild all   # після зміни фрагмента
~/br-lab11/images/start-qemu.sh -snapshot                    # вихід: Ctrl-A, X
```

Тест запускає образ із `-snapshot`, заходить через послідовну консоль, перевіряє модуль,
програму eBPF, верифікатор і Oops, а з `--bench` ще й міряє ціну `openat()`. Без `--output`
перевіряються лише вихідні тексти (на каркасі проходить `t_tree`).

## Що має бути в REPORT.md

Середовище (система, процесор, `/dev/kvm`, версії Buildroot і clang) · вивід `lab11-test.py` ·
таблиця вимірювань (без спостерігача, модуль, модуль з `target`, eBPF з JIT і без) ·
`modinfo` і `/proc/lab11_opencount` · ваш Oops і `tainted` · таблиця `opencount` і
`bpftool prog show` · журнали верифікатора · відповіді на десять питань для звіту · висновки ·
розділ «Використання ШІ», якщо користувалися.
