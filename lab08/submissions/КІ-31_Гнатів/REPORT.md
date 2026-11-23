# Лабораторна робота № 8. Час, локалізація і служби: годинники ядра, часові пояси, локаль і systemd

**Робота:** ЛР № 8  
**Студент, група:** Гнатів Мар'ян, КІ-31  
**Гілка репозиторію:** `lab08-hnativ`  

---

## 1. Середовище виконання

* **Система та ядро:** `Linux MSI 6.6.87.2-microsoft-standard-WSL2 #1 SMP PREEMPT_DYNAMIC x86_64 GNU/Linux` (Ubuntu 22.04 LTS у WSL2)
* **Процесор:** `12th Gen Intel(R) Core(TM) i7-12650H`
* **Джерело тактів (`current_clocksource`):** `tsc`
* **Версія компілятора:** `gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0`
* **Версія стандартної бібліотеки C:** `ldd (Ubuntu GLIBC 2.35-0ubuntu3.18) 2.35`
* **Шлях до каталогу роботи:** `~/CS1232026/lab08/submissions/КІ-31_Гнатів`

---

## 2. Таблиці вимірювань

### 2.1. Системні годинники POSIX (розділ 4.4 — `./clocks info`, `./clocks step`, `./clocks cost`)

| Годинник | Заявлена роздільність (`clock_getres`), нс | Фактичний мінімальний крок (`step`), нс | Медіанна вартість vDSO (`cost`), нс | Медіанна вартість syscall (`raw`), нс |
| --- | ---: | ---: | ---: | ---: |
| `REALTIME` | 1 | 15 | 16.1 | 95.4 |
| `REALTIME_COARSE` | 4 000 000 | 4 087 169 | 3.3 | 79.1 |
| `MONOTONIC` | 1 | 14 | 15.3 | 97.2 |
| `MONOTONIC_COARSE` | 4 000 000 | 4 087 169 | 3.4 | 88.2 |
| `MONOTONIC_RAW` | 1 | 14 | 16.0 | 99.3 |
| `BOOTTIME` | 1 | 14 | 15.5 | 100.5 |
| `TAI` | 1 | 14 | 16.4 | 97.5 |
| `PROCESS_CPUTIME` | 1 | 139 | 151.8 | 152.0 |
| `THREAD_CPUTIME` | 1 | 134 | 146.3 | 144.4 |

*Точні годинники (`REALTIME`, `MONOTONIC`, `MONOTONIC_RAW`, `BOOTTIME`, `TAI`) читаються через vDSO без перемикання в режим ядра приблизно за ~15–16 нс (проти ~95–100 нс через системний виклик), грубі `*_COARSE` — за ~3.3–3.4 нс із кроком 4 мс (1 тік планувальника `HZ=250`), а годинники процесорного часу (`PROCESS_CPUTIME`, `THREAD_CPUTIME`) завжди потребують входу в ядро (~145–152 нс).*

### 2.2. Періодичний цикл очікування (розділ 5.3 — `./ticker rel|abs|tfd`)

| Режим | Період, мс | Кількість тіків | Робота (`work_ms`), мс | Фактичний час (`elapsed_ms`), мс | Очікуваний час (`expected_ms`), мс | Дрейф (`drift_ms`), мс | Запізнення med / p99 / max, мкс | Пропущено (`missed`) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `rel` | 10.000 | 200 | 0.000 | 2076.104 | 2000.000 | **76.104** | 367.3 / 610.7 / 1149.9 | 0 |
| `abs` | 10.000 | 200 | 0.000 | 2000.290 | 2000.000 | **0.290** | 406.1 / 667.4 / 670.9 | 0 |
| `tfd` | 10.000 | 200 | 0.000 | 2000.335 | 2000.000 | **0.335** | 357.7 / 700.9 / 743.3 | 0 |
| `abs` (overrun) | 8.000 | 100 | 160.000 | 16800.299 | 16800.000 | **0.299** | 337.7 / 601.6 / 601.6 | 2000 |

*У режимі `rel` похибка кожного пробудження (~380 мкс у середньому) лінійно накопичується, даючи дрейф 76.104 мс за 200 кроків. У режимах `abs` (`clock_nanosleep` із `TIMER_ABSTIME`) та `tfd` (`timerfd` із `TFD_TIMER_ABSTIME`) накопичення дрейфу відсутнє (`drift < 0.35 мс`).*

### 2.3. Зведена таблиця реалізованих компонентів (розділ 9)

| Компонент / файл | Призначення | Ключовий системний механізм | Перевірений результат |
| --- | --- | --- | --- |
| `clocks.c` (`cost_ns`) | Вимірювання вартості читання годинників POSIX | Серії з `N` викликів `clock_gettime` із прогрівом та обчисленням медіани | vDSO ~15.3–16.4 нс, coarse ~3.3 нс, syscall ~95–152 нс (`t_clocks_info`, `t_clocks_cost`) |
| `ticker.c` (`wait_abs`) | Періодичне очікування без накопичення похибки | `clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, ...)` від попереднього дедлайну з обробкою `EINTR` та пропущених тіків | Дрейф 0.290 мс за 2 с проти 76.104 мс у `rel` (`t_ticker_*`) |
| `whenis.c` (`wall_to_utc`) | Перетворення локального часу в `time_t` із урахуванням DST | Перебір `tm_isdst` (0/1), `mktime` та зворотна перевірка полів через `localtime_r` | Виявлення `gap` (весна), 2 значень `ambiguous` з різницею 3600 с (осінь), доба 23/24/25 год у `daily` (`t_whenis_*`) |
| `loc.c` (`parse_number`, `format_number`) | Локально-незалежний розбір і форматування чисел | `newlocale(LC_NUMERIC_MASK, "C", 0)`, `strtod_l` та тимчасовий `uselocale` | Коректний розбір `3.5` (`total 1.125`) у локалі `uk_UA.UTF-8` та відхилення коми (`t_loc_*`) |
| `units/lab08-stamp.timer` | Періодичний календарний запуск служби `systemd` | `OnCalendar=*-*-* *:00/2:00`, `AccuracySec=1s`, `Persistent=true` | Запуск на кожній парній хвилині, самовідновлення `lab08-ticker` після `SIGKILL` (`t_units`) |

---

## 3. Фрагменти журналу служби `systemd` (розділ 8)

### 3.1. Пульс `lab08-ticker.service` (рядки `tick`)
```text
Nov 23 16:06:59 MSI systemd[1]: Started ЛР 8: пульс ticker раз на секунду.
Nov 23 16:06:59 MSI ticker[2126]: ticker started period_ms 1000 pid 2126
Nov 23 16:07:00 MSI ticker[2126]: tick 1 mono_s 1.000 real 2026-11-23T15:07:00.217Z late_us 21273.1 missed 0
Nov 23 16:07:01 MSI ticker[2126]: tick 2 mono_s 2.000 real 2026-11-23T15:07:01.233Z late_us 36772.5 missed 0
Nov 23 16:07:02 MSI ticker[2126]: tick 3 mono_s 3.000 real 2026-11-23T15:07:02.226Z late_us 29588.6 missed 0
Nov 23 16:07:03 MSI ticker[2126]: tick 4 mono_s 4.000 real 2026-11-23T15:07:03.196Z late_us 302.9 missed 0
Nov 23 16:07:04 MSI ticker[2126]: tick 5 mono_s 5.000 real 2026-11-23T15:07:04.196Z late_us 319.3 missed 0
cat << 'EOF' > REPORT.md
# Лабораторна робота № 8. Час, локалізація і служби: годинники ядра, часові пояси, локаль і systemd

**Студент:** Гнатів Мар'ян, КІ-31 | **Гілка:** `lab08-hnativ`

## 1. Середовище виконання
* **ОС та ядро:** `Linux MSI 6.6.87.2-microsoft-standard-WSL2 x86_64 GNU/Linux` (Ubuntu 22.04)
* **CPU / Clocksource:** `12th Gen Intel(R) Core(TM) i7-12650H` / `tsc`
* **Компілятор та glibc:** `gcc 11.4.0`, `Ubuntu GLIBC 2.35`
* **Каталог роботи:** `~/CS1232026/lab08/submissions/КІ-31_Гнатів`

## 2. Таблиці вимірювань

### 2.1. Годинники POSIX (`./clocks info`, `./clocks step`, `./clocks cost`)
| Годинник | `getres`, нс | `step`, нс | vDSO `cost`, нс | syscall `raw`, нс |
| --- | ---: | ---: | ---: | ---: |
| `REALTIME` | 1 | 15 | 16.1 | 95.4 |
| `REALTIME_COARSE` | 4 000 000 | 4 087 169 | 3.3 | 79.1 |
| `MONOTONIC` | 1 | 14 | 15.3 | 97.2 |
| `MONOTONIC_COARSE` | 4 000 000 | 4 087 169 | 3.4 | 88.2 |
| `MONOTONIC_RAW` | 1 | 14 | 16.0 | 99.3 |
| `BOOTTIME` | 1 | 14 | 15.5 | 100.5 |
| `TAI` | 1 | 14 | 16.4 | 97.5 |
| `PROCESS_CPUTIME` | 1 | 139 | 151.8 | 152.0 |
| `THREAD_CPUTIME` | 1 | 134 | 146.3 | 144.4 |

### 2.2. Періодичний цикл (`./ticker rel|abs|tfd`)
| Режим | Період, мс | Тіки | `work_ms` | `elapsed_ms` | `expected_ms` | `drift_ms` | `late_us` (med/p99/max) | `missed` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `rel` | 10.0 | 200 | 0 | 2076.104 | 2000.000 | **76.104** | 367.3 / 610.7 / 1149.9 | 0 |
| `abs` | 10.0 | 200 | 0 | 2000.290 | 2000.000 | **0.290** | 406.1 / 667.4 / 670.9 | 0 |
| `tfd` | 10.0 | 200 | 0 | 2000.335 | 2000.000 | **0.335** | 357.7 / 700.9 / 743.3 | 0 |
| `abs` (overrun) | 8.0 | 100 | 160 | 16800.299 | 16800.000 | **0.299** | 337.7 / 601.6 / 601.6 | 2000 |

### 2.3. Зведена таблиця компонентів
| Файл | Реалізований механізм | Результат |
| --- | --- | --- |
| `clocks.c` | Прогрів + серія `N` викликів `clock_gettime` + медіана | vDSO ~15 нс, coarse ~3.3 нс, syscall ~95–152 нс |
| `ticker.c` | `clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME)` від попереднього дедлайну + `EINTR` | Дрейф 0.290 мс проти 76.104 мс у `rel` |
| `whenis.c` | Перебір `tm_isdst` (0/1), `mktime` + зворотна перевірка `localtime_r` | Виявлення `gap` (весна), `ambiguous` (осінь), доба 23/24/25 год |
| `loc.c` | Локаль `"C"` через `newlocale`, `strtod_l` та тимчасовий `uselocale` | Коректний парсинг `3.5` у `uk_UA.UTF-8`, відхилення `,` |
| `units/lab08-stamp.timer` | `OnCalendar=*-*-* *:00/2:00`, `AccuracySec=1s`, `Persistent=true` | Запуск щопарної хвилини, рестарт служби після `SIGKILL` |

## 3. Журнал служби `systemd`
```text
# Пульс та перезапуск після SIGKILL (lab08-ticker.service)
Nov 23 16:07:00 MSI ticker[2126]: tick 1 mono_s 1.000 real 2026-11-23T15:07:00.217Z late_us 21273.1 missed 0
Nov 23 16:07:03 MSI ticker[2126]: tick 4 mono_s 4.000 real 2026-11-23T15:07:03.196Z late_us 302.9 missed 0
Nov 23 16:08:26 MSI systemd[1]: lab08-ticker.service: Main process exited, code=killed, status=9/KILL
Nov 23 16:08:29 MSI systemd[1]: Started ЛР 8: пульс ticker раз на секунду.
Nov 23 16:08:29 MSI ticker[2150]: ticker started period_ms 1000 pid 2150

# Зупинка за SIGTERM
tick 4 mono_s 1.000 real 2026-11-23T15:15:11.162Z late_us 298.0 missed 0
stopped after 4 ticks

# Два спрацювання таймера (lab08-stamp.timer)
Nov 23 16:08:00 MSI whenis[2164]: now Europe/Kyiv 2026-11-23 17:08:00 EET +0200
Nov 23 16:08:00 MSI whenis[2164]: now UTC 2026-11-23 15:08:00 UTC +0000
Nov 23 16:10:00 MSI whenis[2198]: now Europe/Kyiv 2026-11-23 17:10:00 EET +0200
Nov 23 16:10:00 MSI whenis[2198]: now UTC 2026-11-23 15:10:00 UTC +0000
cat << 'EOF' > REPORT.md
# Лабораторна робота № 8. Час, локалізація і служби: годинники ядра, часові пояси, локаль і systemd

**Студент:** Гнатів Мар'ян, КІ-31 | **Гілка:** `lab08-hnativ`

## 1. Середовище виконання
* **ОС та ядро:** `Linux MSI 6.6.87.2-microsoft-standard-WSL2 x86_64 GNU/Linux` (Ubuntu 22.04)
* **CPU / Clocksource:** `12th Gen Intel(R) Core(TM) i7-12650H` / `tsc`
* **Компілятор та glibc:** `gcc 11.4.0`, `Ubuntu GLIBC 2.35`
* **Каталог роботи:** `~/CS1232026/lab08/submissions/КІ-31_Гнатів`

## 2. Таблиці вимірювань

### 2.1. Годинники POSIX (`./clocks info`, `./clocks step`, `./clocks cost`)
| Годинник | `getres`, нс | `step`, нс | vDSO `cost`, нс | syscall `raw`, нс |
| --- | ---: | ---: | ---: | ---: |
| `REALTIME` | 1 | 15 | 16.1 | 95.4 |
| `REALTIME_COARSE` | 4 000 000 | 4 087 169 | 3.3 | 79.1 |
| `MONOTONIC` | 1 | 14 | 15.3 | 97.2 |
| `MONOTONIC_COARSE` | 4 000 000 | 4 087 169 | 3.4 | 88.2 |
| `MONOTONIC_RAW` | 1 | 14 | 16.0 | 99.3 |
| `BOOTTIME` | 1 | 14 | 15.5 | 100.5 |
| `TAI` | 1 | 14 | 16.4 | 97.5 |
| `PROCESS_CPUTIME` | 1 | 139 | 151.8 | 152.0 |
| `THREAD_CPUTIME` | 1 | 134 | 146.3 | 144.4 |

### 2.2. Періодичний цикл (`./ticker rel|abs|tfd`)
| Режим | Період, мс | Тіки | `work_ms` | `elapsed_ms` | `expected_ms` | `drift_ms` | `late_us` (med/p99/max) | `missed` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `rel` | 10.0 | 200 | 0 | 2076.104 | 2000.000 | **76.104** | 367.3 / 610.7 / 1149.9 | 0 |
| `abs` | 10.0 | 200 | 0 | 2000.290 | 2000.000 | **0.290** | 406.1 / 667.4 / 670.9 | 0 |
| `tfd` | 10.0 | 200 | 0 | 2000.335 | 2000.000 | **0.335** | 357.7 / 700.9 / 743.3 | 0 |
| `abs` (overrun) | 8.0 | 100 | 160 | 16800.299 | 16800.000 | **0.299** | 337.7 / 601.6 / 601.6 | 2000 |

### 2.3. Зведена таблиця компонентів
| Файл | Реалізований механізм | Результат |
| --- | --- | --- |
| `clocks.c` | Прогрів + серія `N` викликів `clock_gettime` + медіана | vDSO ~15 нс, coarse ~3.3 нс, syscall ~95–152 нс |
| `ticker.c` | `clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME)` від попереднього дедлайну + `EINTR` | Дрейф 0.290 мс проти 76.104 мс у `rel` |
| `whenis.c` | Перебір `tm_isdst` (0/1), `mktime` + зворотна перевірка `localtime_r` | Виявлення `gap` (весна), `ambiguous` (осінь), доба 23/24/25 год |
| `loc.c` | Локаль `"C"` через `newlocale`, `strtod_l` та тимчасовий `uselocale` | Коректний парсинг `3.5` у `uk_UA.UTF-8`, відхилення `,` |
| `units/lab08-stamp.timer` | `OnCalendar=*-*-* *:00/2:00`, `AccuracySec=1s`, `Persistent=true` | Запуск щопарної хвилини, рестарт служби після `SIGKILL` |

## 3. Журнал служби `systemd`
```text
# Пульс та перезапуск після SIGKILL (lab08-ticker.service)
Nov 23 16:07:00 MSI ticker[2126]: tick 1 mono_s 1.000 real 2026-11-23T15:07:00.217Z late_us 21273.1 missed 0
Nov 23 16:07:03 MSI ticker[2126]: tick 4 mono_s 4.000 real 2026-11-23T15:07:03.196Z late_us 302.9 missed 0
Nov 23 16:08:26 MSI systemd[1]: lab08-ticker.service: Main process exited, code=killed, status=9/KILL
Nov 23 16:08:29 MSI systemd[1]: Started ЛР 8: пульс ticker раз на секунду.
Nov 23 16:08:29 MSI ticker[2150]: ticker started period_ms 1000 pid 2150

# Зупинка за SIGTERM
tick 4 mono_s 1.000 real 2026-11-23T15:15:11.162Z late_us 298.0 missed 0
stopped after 4 ticks

# Два спрацювання таймера (lab08-stamp.timer)
Nov 23 16:08:00 MSI whenis[2164]: now Europe/Kyiv 2026-11-23 17:08:00 EET +0200
Nov 23 16:08:00 MSI whenis[2164]: now UTC 2026-11-23 15:08:00 UTC +0000
Nov 23 16:10:00 MSI whenis[2198]: now Europe/Kyiv 2026-11-23 17:10:00 EET +0200
Nov 23 16:10:00 MSI whenis[2198]: now UTC 2026-11-23 15:10:00 UTC +0000
OK t_clocks_info | OK t_clocks_cost | OK t_ticker_rel | OK t_ticker_abs
OK t_ticker_overrun | OK t_ticker_sigterm | OK t_whenis_ok | OK t_whenis_gap
OK t_whenis_ambiguous | OK t_whenis_daily | OK t_loc_parse | OK t_loc_reject | OK t_units
13/13
cat << 'EOF' >> REPORT.md

## 5. Відповіді на контрольні питання
1. **`CLOCK_REALTIME` vs `CLOCK_MONOTONIC`:** `REALTIME` може стрибати при корекції NTP/часу; `MONOTONIC` завжди зростає монотонно, тому лише він придатний для інтервалів.
2. **`MONOTONIC`, `MONOTONIC_RAW`, `BOOTTIME`:** `MONOTONIC` враховує плавну корекцію частоти NTP без часу сну; `RAW` читає апаратний TSC без NTP; `BOOTTIME` додатково враховує час у режимі `suspend`.
3. **Вартість читання:** `MONOTONIC` (~15 нс) і `COARSE` (~3.4 нс, без читання TSC) працюють через vDSO у просторі користувача; `PROCESS_CPUTIME` (~152 нс) вимагає системного виклику в ядро.
4. **Прогрів, серія та медіана у `cost_ns`:** прогрів завантажує vDSO у кеш, серія нівелює квантування годинника (14 нс), а медіана відсіює викиди планувальника ОС.
5. **Дрейф у `rel` vs `TIMER_ABSTIME`:** у `rel` кожне запізнення додається до наступного періоду; у `abs` дедлайн обчислюється від попереднього дедлайну (`t0 + k·T`), тому фаза не зсувається.
6. **Помилки та `EINTR` у `clock_nanosleep`:** функція повертає код помилки напряму (не через `errno`); при `EINTR` достатньо повторити виклик із тим самим абсолютним дедлайном.
7. **Переведення годинника та `+86400 с`:** навесні доба триває 23 год (1 год випадає — `gap`), восени — 25 год (1 год повторюється — `ambiguous`); фіксовані 86400 с зсувають локальний час на годину.
8. **Виявлення `gap` і `ambiguous` у `wall_to_utc`:** перебираються `tm_isdst` 0 та 1, після `mktime` виконується зворотне `localtime_r` і звіряються всі поля часу та `tm_isdst` (0 збігів — `gap`, 2 різні `time_t` — `ambiguous`).
9. **Небезпека глобальної локалі для `strtod`/`snprintf`:** у локалях на кшталт `uk_UA.UTF-8` десятковим роздільником є `,`, що ламає парсинг і серіалізацію чисел із крапкою `.` у конфігах та протоколах.
10. **`.timer` і `.service` у `systemd`:** таймер запускає одноіменну службу за розкладом `OnCalendar`; `AccuracySec=1s` обмежує вікно пробудження до 1 с, а `Persistent=true` запускає пропущений цикл після ввімкнення системи.

## 6. Висновки
Для опитування датчика кожні `100 мс` і журналювання міток часу слід обрати:
* **Годинники:** `CLOCK_MONOTONIC` для відліку періодів (захист від стрибків NTP) та `CLOCK_REALTIME` у форматі UTC ISO-8601 (`...Z`) для міток у логах (відсутність проблем із DST/часовими поясами).
* **Очікування:** `clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, ...)` від попереднього дедлайну з обробкою `EINTR` (або `timerfd` при роботі з `epoll`).
* **Запуск:** фонова служба `systemd` (`Restart=on-failure`, `RestartSec=3s`) із логуванням у `journald` та фіксованою локаллю `LC_NUMERIC=C`.
