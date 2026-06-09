# Weather Checker NVDA Add-on

Weather Checker is a highly accessible NVDA add-on that provides up-to-date weather conditions, forecasts, astronomy data, and weather alerts. It integrates both the **OpenWeather** and **Pirate Weather** APIs to deliver accurate, reliable forecasts with seamless automatic failover.

---

## Key Features

1. **Dual Provider & All Providers Selection**: Choose between OpenWeather, Pirate Weather, or select **All Providers** to query both simultaneously and receive average weather statistics with combined weather descriptions.
2. **Programmatic Failover**: If you select a single provider but that provider goes down, the add-on automatically falls back to your secondary provider to ensure you always get the weather details, announcing: *"OpenWeather is currently unavailable. Using Pirate Weather."*
3. **Advanced Location Search**: Search for locations easily with a dedicated **Location Search Dialog**, which returns focus directly back to NVDA Settings once a location is chosen.
4. **Auto-Location Detection**: Detect your current location automatically using IP-based geolocation with a single click.
5. **Weather History & Comparison**: Log weather conditions over time and easily compare current weather details against your past records.
6. **Automatic Updates**: Features an accessible automatic update notification dialog displaying release notes inside a read-only multiline text field, focusing the "Yes" button by default.

---

## Keyboard Shortcuts (Non-Reserved Keys)

The add-on uses standard key shortcuts that do not conflict with NVDA's built-in reserved keys. 

*   **`NVDA + Shift + W`**: Speaks the current weather.
    *   *Double Press*: Copies the detailed current weather text to the clipboard.
*   **`NVDA + Shift + F`**: Speaks the weather forecast.
    *   *Double Press*: Copies the detailed forecast text to the clipboard.
*   **`NVDA + Shift + A`**: Speaks active weather alerts/warnings for your set location.
    *   *Double Press*: Copies the alert details to the clipboard.
*   **`NVDA + Shift + S`**: Speaks astronomy details (sunrise, sunset, moon phase).
    *   *Double Press*: Copies the astronomy details to the clipboard.
*   **`NVDA + Shift + L`**: Cycles through your configured favorite locations.

---

## How to Set Up and Configure

1. Go to **NVDA Menu** -> **Preferences** -> **Settings**.
2. Navigate to the **Weather Checker** category in the settings list.
3. **Select Weather Provider**:
    *   **OpenWeather**: Requires an OpenWeather API key.
    *   **Pirate Weather**: Requires a Pirate Weather API key.
    *   **All Providers**: Requires both API keys. Queries both services and aggregates results.
4. **Configure Location**:
    *   Check **Automatically detect my location** to query weather based on your current IP address.
    *   Or, uncheck it to configure a static default location: click **Search for Location...** to search for your city, or click **Use Current Location** to set it based on your current IP.
5. Configure your preferences for **Temperature Unit** (Celsius/Fahrenheit), **Wind Speed**, **Pressure**, **Visibility**, **Automatically copy spoken weather details to clipboard**, and **Auto-Update Checks**.
6. Press **OK** to save configurations.

---

## Download & Repository

The official source code, repository, and release packages are hosted on GitHub:
* **GitHub Repository**: [swarup-developer/weatherChecker-addon](https://github.com/swarup-developer/weatherChecker-addon)
* **Latest Release Download**: [Download .nvda-addon](https://github.com/swarup-developer/weatherChecker-addon/releases/latest)

---

## Contributions

Contributions are welcome! If you want to contribute, please follow these guidelines:

### Contribution Guidelines
1. **Reporting Issues**: If you encounter bugs or want to request features, please open an issue on the [GitHub Issues](https://github.com/swarup-developer/weatherChecker-addon/issues) page.
2. **Submitting Pull Requests**:
   - Fork the repository and create your branch from `main`.
   - Implement your changes, keeping the code clean and properly structured.
   - Commit your changes with clear, descriptive commit messages.
   - Submit a Pull Request describing your changes.
3. **Code Quality**:
   - Write clean, readable code.
   - Test your changes locally before submitting.
4. **Local Building & Testing**:
   - Run `scons` in the root directory to build the `.nvda-addon` package.
   - Install the generated package in NVDA to verify your changes.

