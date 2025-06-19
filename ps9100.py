import socket
import usb.core
import usb.util
import sys
import argparse
import os
import datetime

# --- Конфигурация принтера ---
# Жестко заданные Vendor ID и Product ID принтера.
# Убедитесь, что это VID/PID именно вашего принтера.
PRINTER_VENDOR_ID = 0x03f0
PRINTER_PRODUCT_ID = 0x4117

# Папка для сохранения заданий на печать.
# Убедитесь, что у пользователя, запускающего скрипт, есть права на запись в эту папку.
JOBS_FOLDER = "jobs"
# --- Конец конфигурации ---

def print_raw_to_usb(data: bytes) -> bool:
    """
    Отправляет RAW-данные напрямую на USB-принтер с жестко заданными VID/PID.
    Возвращает True в случае успеха, False при ошибке.
    """
    # Находим USB-устройство по Vendor ID и Product ID
    dev = usb.core.find(idVendor=PRINTER_VENDOR_ID, idProduct=PRINTER_PRODUCT_ID)

    if dev is None:
        print(f"  Ошибка: Принтер с Vendor ID {hex(PRINTER_VENDOR_ID)} и Product ID {hex(PRINTER_PRODUCT_ID)} не найден.")
        print("  Подсказка: Убедитесь, что принтер подключен, включен и его VID/PID совпадают с указанными в коде.")
        print("  Также проверьте права доступа: возможно, потребуется запустить скрипт с 'sudo' или настроить правила 'udev'.")
        return False

    # Отсоединяем драйвер ядра от устройства, если он активен.
    # Это необходимо, чтобы pyusb мог получить эксклюзивный контроль над устройством в Linux.
    if sys.platform != "win32" and dev.is_kernel_driver_active(0):
        try:
            dev.detach_kernel_driver(0)
            print("  Драйвер ядра отсоединен для прямого доступа.")
        except usb.core.USBError as e:
            print(f"  Не удалось отсоединить драйвер ядра: {e}")
            print("  Подсказка: Возможно, другое приложение или драйвер удерживает контроль над принтером.")
            usb.util.dispose_resources(dev)
            return False

    # Устанавливаем активную конфигурацию и сбрасываем устройство.
    # Сброс часто помогает принтеру выйти из некорректного состояния.
    try:
        dev.set_configuration()
        dev.reset()
    except usb.core.USBError as e:
        print(f"  Ошибка установки конфигурации/сброса USB-устройства: {e}")
        usb.util.dispose_resources(dev)
        return False

    # Находим конечную точку для вывода (OUT endpoint).
    # Это канал, через который данные будут отправляться на принтер.
    cfg = dev.get_active_configuration()
    intf = cfg[(0,0)] # Обычно это первый интерфейс (индекс 0, альтернативная настройка 0)
    ep = usb.util.find_descriptor(
        intf,
        custom_match = \
        lambda e: \
            usb.util.endpoint_direction(e.bEndpointAddress) == \
            usb.util.ENDPOINT_OUT)

    if ep is None:
        print("  Ошибка: Не найдена конечная точка для вывода (OUT endpoint) на принтере.")
        print("  Подсказка: Убедитесь, что это принтер, поддерживающий RAW-печать через USB.")
        usb.util.dispose_resources(dev)
        return False

    print(f"  Отправка {len(data)} байт данных на принтер...")
    try:
        # Отправляем данные на принтер с таймаутом в 1 секунду.
        ep.write(data, 1000)
        print("  Данные успешно отправлены.")
        return True
    except usb.core.USBError as e:
        print(f"  Ошибка при записи данных на принтер: {e}")
        print("  Подсказка: Принтер не отвечает, таймаут или проблемы с USB-соединением.")
        return False
    finally:
        # Важно освободить ресурсы USB после использования, чтобы другие приложения
        # или драйвер ядра могли снова получить доступ к устройству.
        usb.util.dispose_resources(dev)
        # Попытка присоединить драйвер ядра обратно, если он был отсоединен
        if sys.platform != "win32" and not dev.is_kernel_driver_active(0):
            try:
                dev.attach_kernel_driver(0)
                print("  Драйвер ядра присоединен обратно.")
            except usb.core.USBError as e:
                print(f"  Не удалось присоединить драйвер ядра обратно: {e}")


def start_print_server(port: int):
    """
    Запускает сервер, который слушает указанный порт, сохраняет задания
    и отправляет их на USB-принтер.
    """
    host = '0.0.0.0' # Слушаем все доступные сетевые интерфейсы
    buffer_size = 4096 # Размер буфера для приема данных за один раз

    # Создаем папку для заданий, если ее нет.
    if not os.path.exists(JOBS_FOLDER):
        try:
            os.makedirs(JOBS_FOLDER)
            print(f"Создана папка для сохранения заданий: '{JOBS_FOLDER}'")
        except OSError as e:
            print(f"Ошибка при создании папки '{JOBS_FOLDER}': {e}")
            print("Подсказка: Пожалуйста, создайте ее вручную или проверьте права доступа к директории, где запускается скрипт.")
            sys.exit(1) # Выходим, если не можем создать папку

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Позволяем немедленное повторное использование порта после закрытия.
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        s.bind((host, port))
        s.listen(1) # Сервер будет принимать одно входящее соединение за раз
        print(f"Сервер запущен и слушает порт {port}...")
        print(f"Ожидание заданий на печать для принтера с Vendor ID: {hex(PRINTER_VENDOR_ID)}, Product ID: {hex(PRINTER_PRODUCT_ID)}")
        print(f"Задания также будут сохраняться в папку '{JOBS_FOLDER}'.")

        job_counter = 0 # Счетчик заданий для создания уникальных имен файлов

        while True:
            conn, addr = s.accept() # Принимаем входящее соединение
            job_counter += 1
            print(f"\n--- Получено новое задание ({job_counter}) ---")
            print(f"  Источник: {addr[0]}:{addr[1]}") # IP-адрес и порт клиента

            with conn: # Автоматическое закрытие соединения при выходе из блока
                full_data = b""
                # Читаем все данные из сокета, пока клиент не закроет соединение
                while True:
                    data = conn.recv(buffer_size)
                    if not data: # Если данных больше нет (клиент закрыл соединение)
                        break
                    full_data += data

                print(f"  Размер задания: {len(full_data)} байт.")

                if full_data:
                    # Сохраняем задание в файл
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    # Имя файла включает IP-адрес клиента и порядковый номер задания для уникальности
                    filename = os.path.join(JOBS_FOLDER, f"job_{timestamp}_{addr[0].replace('.', '-')}_{job_counter}.prn")
                    try:
                        with open(filename, "wb") as f:
                            f.write(full_data)
                        print(f"  Задание успешно сохранено в файл: '{filename}'")
                    except IOError as e:
                        print(f"  Ошибка при сохранении задания в файл '{filename}': {e}")

                    # Отправляем задание на принтер (снова включено)
                    print_raw_to_usb(full_data)
                else:
                    print("  Получены пустые данные. Ничего не отправлено на принтер и не сохранено.")

    except OSError as e:
        print(f"Ошибка при запуске сервера: {e}")
        if e.errno == 98: # EADDRINUSE (Address already in use)
            print(f"Подсказка: Порт {port} уже занят другим приложением. Пожалуйста, выберите другой порт или освободите текущий.")
    except KeyboardInterrupt:
        print("\nСервер остановлен пользователем (Ctrl+C).")
    except Exception as e:
        print(f"Произошла непредвиденная ошибка сервера: {e}")
    finally:
        s.close()
        print("Сетевой сокет закрыт. Сервер завершил работу.")

if __name__ == "__main__":
    # Настройка парсера аргументов командной строки
    parser = argparse.ArgumentParser(
        description="Сервер для удаленной RAW-печати на USB-принтер под Linux (VID/PID жестко заданы).\n"
                    "Задания также сохраняются в папку 'jobs'.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("-p", "--port", type=int, default=9100,
                        help="""Номер TCP-порта для прослушивания входящих заданий (по умолчанию: 9100).
Пример: python3 your_script.py --port 9101""")

    args = parser.parse_args()

    # --- Важное предупреждение для Linux ---
    if sys.platform != "win32": # Это предупреждение актуально только для Linux/macOS
        print("\n--- ВАЖНО для Linux ---")
        print("Для доступа к USB-устройствам могут потребоваться права root или членство в группе 'lp'/'usb'.")
        print(f"Если возникнут ошибки доступа (например, 'Access denied'), попробуйте запустить:")
        print(f"  sudo python3 {sys.argv[0]} ...")
        print("Или добавьте пользователя в группу 'lp' (sudo usermod -a -G lp $USER) и ПЕРЕЗАГРУЗИТЕ систему.")
        print(f"Также убедитесь, что у пользователя есть права на запись в папку '{JOBS_FOLDER}' (в текущем каталоге).")
        print("---")
    # --- Конец предупреждения ---

    start_print_server(args.port)