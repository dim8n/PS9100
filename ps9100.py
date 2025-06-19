import socket
import usb.core
import usb.util
import sys
import argparse

# Жестко заданные Vendor ID и Product ID принтера
# (Пример: HP LaserJet P1007/P1008, но убедитесь, что это ваш принтер)
PRINTER_VENDOR_ID = 0x03f0
PRINTER_PRODUCT_ID = 0x4117

def print_raw_to_usb(data):
    """
    Отправляет RAW-данные напрямую на USB-принтер с жестко заданными VID/PID.
    """
    # Находим устройство по Vendor ID и Product ID
    dev = usb.core.find(idVendor=PRINTER_VENDOR_ID, idProduct=PRINTER_PRODUCT_ID)

    if dev is None:
        print(f"Ошибка: Принтер с Vendor ID {hex(PRINTER_VENDOR_ID)} и Product ID {hex(PRINTER_PRODUCT_ID)} не найден.")
        print("Убедитесь, что принтер подключен и его Vendor ID/Product ID совпадают с указанными в коде.")
        print("Также проверьте права доступа: возможно, потребуется запустить скрипт с sudo или настроить правила udev.")
        return False

    # Отсоединяем драйвер ядра от устройства, если он активен.
    # Это необходимо, чтобы pyusb мог получить эксклюзивный контроль над устройством.
    if sys.platform != "win32" and dev.is_kernel_driver_active(0):
        try:
            dev.detach_kernel_driver(0)
            print("Драйвер ядра отсоединен.")
        except usb.core.USBError as e:
            print(f"Не удалось отсоединить драйвер ядра: {e}")
            print("Возможно, другое приложение или драйвер удерживает контроль над принтером.")
            usb.util.dispose_resources(dev)
            return False

    # Устанавливаем активную конфигурацию и сбрасываем устройство.
    try:
        dev.set_configuration()
        dev.reset()
    except usb.core.USBError as e:
        print(f"Ошибка установки конфигурации/сброса USB-устройства: {e}")
        usb.util.dispose_resources(dev)
        return False

    # Находим конечную точку для вывода (OUT endpoint).
    cfg = dev.get_active_configuration()
    intf = cfg[(0,0)]
    ep = usb.util.find_descriptor(
        intf,
        custom_match = \
        lambda e: \
            usb.util.endpoint_direction(e.bEndpointAddress) == \
            usb.util.ENDPOINT_OUT)

    if ep is None:
        print("Ошибка: Не найдена конечная точка для вывода (OUT endpoint) на принтере.")
        print("Убедитесь, что это действительно принтер, поддерживающий RAW-печать через USB.")
        usb.util.dispose_resources(dev)
        return False

    print(f"Отправка {len(data)} байт данных на принтер...")
    try:
        # Отправляем данные на принтер. Таймаут в 1000 мс (1 секунда).
        ep.write(data, 1000)
        print("Данные успешно отправлены.")
        return True
    except usb.core.USBError as e:
        print(f"Ошибка при записи данных на принтер: {e}")
        print("Возможные причины: принтер не отвечает, таймаут, или проблемы с USB-соединением.")
        return False
    finally:
        # Важно освободить ресурсы USB после использования.
        usb.util.dispose_resources(dev)
        # Попытка присоединить драйвер ядра обратно, если он был отсоединен
        if sys.platform != "win32" and not dev.is_kernel_driver_active(0):
            try:
                dev.attach_kernel_driver(0)
                print("Драйвер ядра присоединен обратно.")
            except usb.core.USBError as e:
                print(f"Не удалось присоединить драйвер ядра обратно: {e}")


def start_print_server(port):
    """
    Запускает сервер, который слушает указанный порт и отправляет
    полученные данные на USB-принтер с жестко заданными VID/PID.
    """
    host = '0.0.0.0'
    buffer_size = 4096

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        s.bind((host, port))
        s.listen(1)
        print(f"Сервер запущен и слушает порт {port}...")
        print(f"Ожидание заданий на печать для принтера с Vendor ID: {hex(PRINTER_VENDOR_ID)}, Product ID: {hex(PRINTER_PRODUCT_ID)}")

        while True:
            conn, addr = s.accept()
            print(f"Получено новое соединение от {addr}")
            with conn:
                full_data = b""
                while True:
                    data = conn.recv(buffer_size)
                    if not data:
                        break
                    full_data += data
                print(f"Получено {len(full_data)} байт данных для печати.")
                if full_data:
                    print_raw_to_usb(full_data)
                else:
                    print("Получены пустые данные. Ничего не отправлено на принтер.")

    except OSError as e:
        print(f"Ошибка при запуске сервера: {e}")
        if e.errno == 98:
            print(f"Порт {port} уже занят другим приложением. Пожалуйста, выберите другой порт или освободите текущий.")
    except KeyboardInterrupt:
        print("\nСервер остановлен пользователем (Ctrl+C).")
    except Exception as e:
        print(f"Произошла непредвиденная ошибка сервера: {e}")
    finally:
        s.close()
        print("Сетевой сокет закрыт. Сервер завершил работу.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Сервер для удаленной RAW-печати на USB-принтер под Linux (VID/PID жестко заданы).")
    parser.add_argument("-p", "--port", type=int, default=9100,
                        help="Номер TCP-порта для прослушивания входящих заданий (по умолчанию: 9100).")

    args = parser.parse_args()

    # Предупреждение о правах доступа для Linux
    if sys.platform != "win32":
        print("\n--- ВАЖНО для Linux ---")
        print("Для доступа к USB-устройствам могут потребоваться права root или членство в группе 'lp'/'usb'.")
        print(f"Если возникнут ошибки доступа, попробуйте запустить: 'sudo python3 {sys.argv[0]} ...'")
        print("Или добавьте пользователя в группу 'lp' (sudo usermod -a -G lp $USER) и перезагрузитесь.")
        print("---")

    start_print_server(args.port)
