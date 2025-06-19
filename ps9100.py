import socket
import sys
import argparse
import os
import datetime

# --- Конфигурация принтера (теперь не используется для печати, но можно оставить для информации) ---
# Жестко заданные Vendor ID и Product ID принтера.
# Эти значения больше не используются для отправки на USB-порт.
PRINTER_VENDOR_ID = 0x03f0
PRINTER_PRODUCT_ID = 0x4117

# Папка для сохранения заданий на печать.
# Убедитесь, что у пользователя, запускающего скрипт, есть права на запись в эту папку.
JOBS_FOLDER = "jobs"
# --- Конец конфигурации ---

# Функция print_raw_to_usb теперь не будет вызываться.
# Закомментирована или удалена, чтобы избежать ошибок и упростить логику.
# def print_raw_to_usb(data: bytes) -> bool:
#     """
#     Эта функция временно отключена и не будет отправлять данные на USB-принтер.
#     """
#     print("  (Функция отправки на USB-принтер временно отключена.)")
#     return True # Возвращаем True, чтобы не прерывать процесс сохранения


def start_print_server(port: int):
    """
    Запускает сервер, который слушает указанный порт и сохраняет
    полученные задания на печать в папку.
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
        print(f"Задания будут сохраняться в папку '{JOBS_FOLDER}'. Отправка на USB-принтер ОТКЛЮЧЕНА.")

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
                    
                    # Отправка задания на принтер ВРЕМЕННО ОТКЛЮЧЕНА
                    print("  Отправка задания на USB-принтер пропущена (функция отключена).")
                else:
                    print("  Получены пустые данные. Ничего не сохранено.")

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
        description="Сервер для сохранения RAW-заданий на печать в файл (отправка на USB-принтер отключена).",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("-p", "--port", type=int, default=9100,
                        help="""Номер TCP-порта для прослушивания входящих заданий (по умолчанию: 9100).
Пример: python3 your_script.py --port 9101""")

    args = parser.parse_args()

    # --- Важное предупреждение для Linux ---
    if sys.platform != "win32":
        print("\n--- ВАЖНО для Linux ---")
        print(f"Убедитесь, что у пользователя, запускающего скрипт, есть права на запись в папку '{JOBS_FOLDER}' (в текущем каталоге).")
        print("---")
    # --- Конец предупреждения ---

    start_print_server(args.port)