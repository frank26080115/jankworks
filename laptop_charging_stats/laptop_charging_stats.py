import wmi

def get_battery_status():
    c = wmi.WMI(namespace="root\\wmi")

    results = c.BatteryStatus()

    if not results:
        print("No BatteryStatus data found.")
        return None

    # If multiple batteries exist, use the first
    b = results[0]

    data = {
        "Voltage_mV": getattr(b, "Voltage", None),
        "ChargeRate_mW": getattr(b, "ChargeRate", None)
    }

    return data


def has_battery():
    c = wmi.WMI(namespace="root\\cimv2")
    return len(c.Win32_Battery()) > 0


if __name__ == "__main__":
    if not has_battery():
        print("No Battery")
        quit()

    battery_data = get_battery_status()

    if battery_data:
        print("Battery Data:")
        print(battery_data)

        # Optional friendly formatting
        if battery_data["Voltage_mV"] is not None:
            print(f"Voltage: {battery_data['Voltage_mV'] / 1000:.2f} V")

        if battery_data["ChargeRate_mW"] is not None:
            print(f"Charge Rate: {battery_data['ChargeRate_mW'] / 1000:.2f} W")
