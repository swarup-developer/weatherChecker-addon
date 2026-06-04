# -*- coding: utf-8 -*-
# Weather Client for Weather Checker NVDA add-on

import requests
import time
import datetime
from logHandler import log
import addonHandler

addonHandler.initTranslation()

class WeatherClientError(Exception):
    """Base exception for Weather Client errors."""
    pass

class InvalidApiKeyError(WeatherClientError):
    """Raised when an API key is rejected."""
    pass

class NetworkError(WeatherClientError):
    """Raised when there is a network connectivity issue."""
    pass

class GeocodingError(WeatherClientError):
    """Raised when geocoding fails or returns no results."""
    pass


def verifyKeys(provider, openWeatherKey, pirateWeatherKey):
    """
    Validate the configured provider keys.
    Returns (success, message).
    """
    try:
        if provider == 0:  # OpenWeather
            if not openWeatherKey:
                return False, _("OpenWeather API key cannot be empty.")
            return _verifyOpenWeatherKey(openWeatherKey)
        elif provider == 1:  # Pirate Weather
            if not pirateWeatherKey:
                return False, _("Pirate Weather API key cannot be empty.")
            return _verifyPirateWeatherKey(pirateWeatherKey)
        elif provider == 2:  # Both
            if not openWeatherKey or not pirateWeatherKey:
                return False, _("Both API keys are required and cannot be empty.")
            ow_ok, ow_msg = _verifyOpenWeatherKey(openWeatherKey)
            if not ow_ok:
                return False, _("OpenWeather key verification failed: ") + ow_msg
            pw_ok, pw_msg = _verifyPirateWeatherKey(pirateWeatherKey)
            if not pw_ok:
                return False, _("Pirate Weather key verification failed: ") + pw_msg
            return True, _("Both API keys verified successfully.")
        return False, _("Invalid weather provider selected.")
    except Exception as e:
        log.error("Exception in verifyKeys: ", exc_info=True)
        return False, str(e)


def _verifyOpenWeatherKey(key):
    """Verify OpenWeather API key using current weather API at Lat=0, Lon=0."""
    url = f"https://api.openweathermap.org/data/2.5/weather?lat=0&lon=0&appid={key}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return True, _("OpenWeather key is valid.")
        elif resp.status_code == 401:
            return False, _("Invalid API key. Please check your OpenWeather key.")
        else:
            return False, f"HTTP Error {resp.status_code}: {resp.reason}"
    except requests.RequestException as e:
        return False, _("Network error: ") + str(e)


def _verifyPirateWeatherKey(key):
    """Verify Pirate Weather API key using forecast API at Lat=0, Lon=0."""
    url = f"https://api.pirateweather.net/forecast/{key}/0,0"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return True, _("Pirate Weather key is valid.")
        elif resp.status_code in (401, 403):
            return False, _("Invalid API key. Please check your Pirate Weather key.")
        else:
            return False, f"HTTP Error {resp.status_code}: {resp.reason}"
    except requests.RequestException as e:
        return False, _("Network error: ") + str(e)


def geocodeLocation(query, provider, openWeatherKey):
    """
    Search for location matching query.
    If OpenWeather key is available (provider is OpenWeather or Both), use OpenWeather Geocoding API.
    Otherwise, fall back to OpenStreetMap Nominatim API.
    """
    if not query or not query.strip():
        raise GeocodingError(_("Search query cannot be empty."))
        
    query = query.strip()
    
    # Try OpenWeather Geocoding if key is available
    if openWeatherKey and provider in (0, 2):
        url = f"https://api.openweathermap.org/geo/1.0/direct?q={requests.utils.quote(query)}&limit=10&appid={openWeatherKey}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                results = resp.json()
                if not results:
                    raise GeocodingError(_("No locations found for: ") + query)
                
                formatted_results = []
                for item in results:
                    name = item.get("name", "")
                    region = item.get("state", "")
                    country = item.get("country", "")
                    lat = item.get("lat")
                    lon = item.get("lon")
                    
                    formatted_results.append({
                        "name": name,
                        "region": region,
                        "country": country,
                        "lat": float(lat),
                        "lon": float(lon)
                    })
                return formatted_results
            elif resp.status_code == 401:
                raise InvalidApiKeyError(_("Invalid OpenWeather key for geocoding."))
            else:
                log.error(f"OpenWeather geocoding HTTP Error {resp.status_code}")
        except requests.RequestException as e:
            log.error("OpenWeather geocoding connection error, falling back to Nominatim", exc_info=True)

    # Fallback/Default: OpenStreetMap Nominatim API
    url = f"https://nominatim.openstreetmap.org/search?q={requests.utils.quote(query)}&format=json&limit=10&addressdetails=1"
    headers = {
        "User-Agent": "WeatherCheckerNVDA/1.0 (Contact: swarup.baral@example.com)"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            results = resp.json()
            if not results:
                raise GeocodingError(_("No locations found for: ") + query)
            
            formatted_results = []
            for item in results:
                display_name = item.get("display_name", "")
                address = item.get("address", {})
                
                name = (address.get("city") or 
                        address.get("town") or 
                        address.get("village") or 
                        address.get("suburb") or 
                        address.get("hamlet") or 
                        address.get("municipality") or 
                        address.get("county") or 
                        display_name.split(",")[0])
                
                region = address.get("state") or address.get("province") or address.get("county") or ""
                country = address.get("country") or ""
                
                lat = item.get("lat")
                lon = item.get("lon")
                
                formatted_results.append({
                    "name": name,
                    "region": region,
                    "country": country,
                    "lat": float(lat),
                    "lon": float(lon)
                })
            return formatted_results
        elif resp.status_code == 403:
            raise GeocodingError(_("Geocoding service rate limited or forbidden. Please try again later."))
        else:
            raise GeocodingError(f"Nominatim HTTP Error {resp.status_code}: {resp.reason}")
    except requests.RequestException as e:
        raise NetworkError(_("Network failure while geocoding: ") + str(e))


def detectLocationIP():
    """
    Detect location using ipwho.is IP-based geolocation.
    Returns {"lat": lat, "lon": lon, "name": name, "country": country}
    """
    url = "https://ipwho.is/"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                city = data.get("city", "")
                region = data.get("region", "")
                country = data.get("country", "")
                lat = data.get("latitude")
                lon = data.get("longitude")
                
                name_parts = [p for p in [city, region] if p]
                name = ", ".join(name_parts) if name_parts else _("Detected Location")
                
                return {
                    "lat": float(lat),
                    "lon": float(lon),
                    "name": name,
                    "country": country
                }
            else:
                raise GeocodingError(_("IP Geolocation failed: ") + str(data.get("message", "Unknown error")))
        else:
            raise NetworkError(f"IP Geolocation HTTP Error {resp.status_code}: {resp.reason}")
    except requests.RequestException as e:
        raise NetworkError(_("IP Geolocation network failure: ") + str(e))


def fetchWeatherData(lat, lon, provider, openWeatherKey, pirateWeatherKey):
    """
    Fetch all weather data for lat, lon coordinates.
    provider: 0=OpenWeather, 1=Pirate Weather, 2=OpenWeather + Pirate Weather
    Returns a dictionary of normalized weather data.
    """
    results = {}
    errors = []

    want_open_weather = (provider == 0 or provider == 2)
    want_pirate_weather = (provider == 1 or provider == 2)

    # 1. Fetch OpenWeather
    if want_open_weather and openWeatherKey:
        try:
            ow_data = _fetchOpenWeather(lat, lon, openWeatherKey)
            results["OpenWeather"] = ow_data
        except Exception as e:
            errors.append(f"OpenWeather: {str(e)}")
            log.error("Failed fetching OpenWeather", exc_info=True)
            
            if provider == 0 and pirateWeatherKey:
                log.info("OpenWeather failed. Attempting failover to Pirate Weather.")
                try:
                    pw_data = _fetchPirateWeather(lat, lon, pirateWeatherKey)
                    results["Pirate Weather"] = pw_data
                except Exception as ex:
                    errors.append(f"Pirate Weather (Failover): {str(ex)}")

    # 2. Fetch Pirate Weather
    if want_pirate_weather and pirateWeatherKey:
        if "Pirate Weather" not in results:
            try:
                pw_data = _fetchPirateWeather(lat, lon, pirateWeatherKey)
                results["Pirate Weather"] = pw_data
            except Exception as e:
                errors.append(f"Pirate Weather: {str(e)}")
                log.error("Failed fetching Pirate Weather", exc_info=True)
                
                if provider == 1 and openWeatherKey and "OpenWeather" not in results:
                    log.info("Pirate Weather failed. Attempting failover to OpenWeather.")
                    try:
                        ow_data = _fetchOpenWeather(lat, lon, openWeatherKey)
                        results["OpenWeather"] = ow_data
                    except Exception as ex:
                        errors.append(f"OpenWeather (Failover): {str(ex)}")

    if not results:
        error_msg = "; ".join(errors)
        raise WeatherClientError(_("Weather request failed: ") + error_msg)

    return results


def _fetchOpenWeather(lat, lon, key):
    data = None
    one_call_success = False

    # Attempt One Call 3.0 first
    try:
        url = f"https://api.openweathermap.org/data/3.0/onecall?lat={lat}&lon={lon}&appid={key}&units=metric"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            one_call_success = True
        elif resp.status_code in (401, 403):
            log.info("OpenWeather 3.0 One Call failed, trying 2.5 One Call.")
        else:
            resp.raise_for_status()
    except Exception as e:
        log.error("OpenWeather 3.0 One Call exception: ", exc_info=True)

    # Attempt One Call 2.5
    if not one_call_success:
        try:
            url = f"https://api.openweathermap.org/data/2.5/onecall?lat={lat}&lon={lon}&appid={key}&units=metric"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                one_call_success = True
            elif resp.status_code in (401, 403):
                log.info("OpenWeather 2.5 One Call failed. Falling back to Current and Forecast APIs.")
            else:
                resp.raise_for_status()
        except Exception as e:
            log.error("OpenWeather 2.5 One Call exception: ", exc_info=True)

    normalized = {}

    if one_call_success and data:
        current = data.get("current", {})
        weather_list = current.get("weather", [])
        condition = weather_list[0].get("description", "") if weather_list else ""
        
        normalized["current"] = {
            "condition": condition.capitalize(),
            "temp": current.get("temp"),
            "feels_like": current.get("feels_like"),
            "humidity": current.get("humidity"),
            "wind_speed": current.get("wind_speed"),
            "wind_dir": current.get("wind_deg"),
            "pressure": current.get("pressure"),
            "visibility": current.get("visibility", 10000) / 1000.0,
            "uvi": current.get("uvi"),
            "clouds": current.get("clouds"),
            "dew_point": current.get("dew_point"),
            "aqi": None
        }
        
        daily_list = data.get("daily", [])
        today_astro = daily_list[0] if daily_list else {}
        normalized["astronomy"] = {
            "sunrise": today_astro.get("sunrise") or current.get("sunrise"),
            "sunset": today_astro.get("sunset") or current.get("sunset"),
            "moonrise": today_astro.get("moonrise"),
            "moonset": today_astro.get("moonset"),
            "moon_phase": today_astro.get("moon_phase")
        }
        
        hourly_forecasts = []
        for h in data.get("hourly", []):
            h_weather = h.get("weather", [])
            h_cond = h_weather[0].get("description", "") if h_weather else ""
            hourly_forecasts.append({
                "time": h.get("dt"),
                "temp": h.get("temp"),
                "feels_like": h.get("feels_like"),
                "condition": h_cond.capitalize()
            })
        normalized["hourly"] = hourly_forecasts
        
        daily_forecasts = []
        for d in daily_list:
            d_weather = d.get("weather", [])
            d_cond = d_weather[0].get("description", "") if d_weather else ""
            d_temp = d.get("temp", {})
            daily_forecasts.append({
                "time": d.get("dt"),
                "temp_min": d_temp.get("min"),
                "temp_max": d_temp.get("max"),
                "condition": d_cond.capitalize(),
                "sunrise": d.get("sunrise"),
                "sunset": d.get("sunset"),
                "moon_phase": d.get("moon_phase")
            })
        normalized["daily"] = daily_forecasts
        
        alerts = []
        for alert in data.get("alerts", []):
            alerts.append({
                "title": alert.get("event", _("Weather Warning")),
                "description": alert.get("description", ""),
                "severity": alert.get("severity", "moderate").lower(),
                "start": alert.get("start"),
                "end": alert.get("end")
            })
        normalized["alerts"] = alerts
        
    else:
        # Fallback to Current 2.5 + Forecast 2.5
        current_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={key}&units=metric"
        forecast_url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={key}&units=metric"
        
        try:
            curr_resp = requests.get(current_url, timeout=10)
            if curr_resp.status_code == 401:
                raise InvalidApiKeyError(_("Invalid OpenWeather API Key."))
            curr_resp.raise_for_status()
            curr_data = curr_resp.json()
        except requests.RequestException as e:
            raise NetworkError(_("OpenWeather connection failed: ") + str(e))
            
        try:
            fore_resp = requests.get(forecast_url, timeout=10)
            fore_resp.raise_for_status()
            fore_data = fore_resp.json()
        except requests.RequestException as e:
            raise NetworkError(_("OpenWeather forecast connection failed: ") + str(e))
            
        weather_list = curr_data.get("weather", [])
        condition = weather_list[0].get("description", "") if weather_list else ""
        main_data = curr_data.get("main", {})
        wind_data = curr_data.get("wind", {})
        clouds_data = curr_data.get("clouds", {})
        sys_data = curr_data.get("sys", {})
        
        normalized["current"] = {
            "condition": condition.capitalize(),
            "temp": main_data.get("temp"),
            "feels_like": main_data.get("feels_like"),
            "humidity": main_data.get("humidity"),
            "wind_speed": wind_data.get("speed"),
            "wind_dir": wind_data.get("deg"),
            "pressure": main_data.get("pressure"),
            "visibility": curr_data.get("visibility", 10000) / 1000.0,
            "uvi": None,
            "clouds": clouds_data.get("all"),
            "dew_point": None,
            "aqi": None
        }
        
        normalized["astronomy"] = {
            "sunrise": sys_data.get("sunrise"),
            "sunset": sys_data.get("sunset"),
            "moonrise": None,
            "moonset": None,
            "moon_phase": None
        }
        
        hourly_forecasts = []
        forecast_list = fore_data.get("list", [])
        
        for item in forecast_list:
            item_weather = item.get("weather", [])
            item_cond = item_weather[0].get("description", "") if item_weather else ""
            item_main = item.get("main", {})
            hourly_forecasts.append({
                "time": item.get("dt"),
                "temp": item_main.get("temp"),
                "feels_like": item_main.get("feels_like"),
                "condition": item_cond.capitalize()
            })
        normalized["hourly"] = hourly_forecasts
        
        daily_groups = {}
        for item in forecast_list:
            dt = item.get("dt")
            dt_date = datetime.datetime.fromtimestamp(dt).date()
            if dt_date not in daily_groups:
                daily_groups[dt_date] = []
            daily_groups[dt_date].append(item)
            
        daily_forecasts = []
        sorted_dates = sorted(daily_groups.keys())
        for d_date in sorted_dates:
            items = daily_groups[d_date]
            temps = [it.get("main", {}).get("temp") for it in items if it.get("main", {}).get("temp") is not None]
            min_temp = min(temps) if temps else None
            max_temp = max(temps) if temps else None
            
            rep_item = items[0]
            for it in items:
                dt_time = datetime.datetime.fromtimestamp(it.get("dt")).time()
                if 11 <= dt_time.hour <= 14:
                    rep_item = it
                    break
            
            rep_weather = rep_item.get("weather", [])
            rep_cond = rep_weather[0].get("description", "") if rep_weather else ""
            
            daily_forecasts.append({
                "time": int(time.mktime(datetime.datetime.combine(d_date, datetime.time(12, 0)).timetuple())),
                "temp_min": min_temp,
                "temp_max": max_temp,
                "condition": rep_cond.capitalize(),
                "sunrise": None,
                "sunset": None,
                "moon_phase": None
            })
        normalized["daily"] = daily_forecasts
        normalized["alerts"] = []

    # Query Air Quality
    try:
        pollution_url = f"https://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={key}"
        poll_resp = requests.get(pollution_url, timeout=10)
        if poll_resp.status_code == 200:
            poll_data = poll_resp.json()
            poll_list = poll_data.get("list", [])
            if poll_list:
                aqi_code = poll_list[0].get("main", {}).get("aqi")
                aqi_names = {
                    1: _("Good"),
                    2: _("Fair"),
                    3: _("Moderate"),
                    4: _("Poor"),
                    5: _("Very Poor")
                }
                normalized["current"]["aqi"] = aqi_names.get(aqi_code, _("Unknown"))
    except Exception as e:
        log.error("Failed to query Air Pollution API", exc_info=True)

    return normalized


def _fetchPirateWeather(lat, lon, key):
    url = f"https://api.pirateweather.net/forecast/{key}/{lat},{lon}?units=si"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code in (401, 403):
            raise InvalidApiKeyError(_("Invalid Pirate Weather API Key."))
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise NetworkError(_("Pirate Weather connection failed: ") + str(e))

    normalized = {}

    current = data.get("currently", {})
    normalized["current"] = {
        "condition": current.get("summary", ""),
        "temp": current.get("temperature"),
        "feels_like": current.get("apparentTemperature"),
        "humidity": int(current.get("humidity", 0) * 100) if current.get("humidity") is not None else None,
        "wind_speed": current.get("windSpeed"),
        "wind_dir": current.get("windBearing"),
        "pressure": current.get("pressure"),
        "visibility": current.get("visibility"),
        "uvi": current.get("uvIndex"),
        "clouds": int(current.get("cloudCover", 0) * 100) if current.get("cloudCover") is not None else None,
        "dew_point": current.get("dewPoint"),
        "aqi": None
    }

    daily_list = data.get("daily", {}).get("data", [])
    today_daily = daily_list[0] if daily_list else {}
    normalized["astronomy"] = {
        "sunrise": today_daily.get("sunriseTime"),
        "sunset": today_daily.get("sunsetTime"),
        "moonrise": None,
        "moonset": None,
        "moon_phase": today_daily.get("moonPhase")
    }

    hourly_forecasts = []
    for h in data.get("hourly", {}).get("data", []):
        hourly_forecasts.append({
            "time": h.get("time"),
            "temp": h.get("temperature"),
            "feels_like": h.get("apparentTemperature"),
            "condition": h.get("summary", "")
        })
    normalized["hourly"] = hourly_forecasts

    daily_forecasts = []
    for d in daily_list:
        daily_forecasts.append({
            "time": d.get("time"),
            "temp_min": d.get("temperatureMin"),
            "temp_max": d.get("temperatureMax"),
            "condition": d.get("summary", ""),
            "sunrise": d.get("sunriseTime"),
            "sunset": d.get("sunsetTime"),
            "moon_phase": d.get("moonPhase")
        })
    normalized["daily"] = daily_forecasts

    alerts = []
    for alert in data.get("alerts", []):
        alerts.append({
            "title": alert.get("title", _("Weather Warning")),
            "description": alert.get("description", ""),
            "severity": alert.get("severity", "moderate").lower(),
            "start": alert.get("time"),
            "end": alert.get("expires")
        })
    normalized["alerts"] = alerts

    return normalized


# ----------------------------------------------------
# Granular Unit Conversions
# ----------------------------------------------------
def convertTemp(val_c, unit):
    """
    Convert Celsius to selected temperature unit.
    unit: 0 = Celsius, 1 = Fahrenheit
    """
    if val_c is None:
        return None
    if unit == 1:
        return (val_c * 9/5) + 32
    return val_c

def convertWindSpeed(val_ms, unit):
    """
    Convert m/s to selected wind speed unit.
    unit: 0 = m/s, 1 = km/h, 2 = mph
    """
    if val_ms is None:
        return None
    if unit == 1: # km/h
        return val_ms * 3.6
    elif unit == 2: # mph
        return val_ms * 2.23694
    return val_ms

def convertPressure(val_hpa, unit):
    """
    Convert hPa to selected pressure unit.
    unit: 0 = hPa, 1 = inHg
    """
    if val_hpa is None:
        return None
    if unit == 1: # inHg
        return val_hpa * 0.02953
    return val_hpa

def convertVisibility(val_km, unit):
    """
    Convert kilometers to selected visibility unit.
    unit: 0 = Kilometers, 1 = Miles
    """
    if val_km is None:
        return None
    if unit == 1: # Miles
        return val_km * 0.621371
    return val_km


def getWindDirectionName(degrees):
    """Convert wind direction angle in degrees to a text description."""
    if degrees is None:
        return _("Unknown")
    directions = [
        _("North"), _("North-Northeast"), _("Northeast"), _("East-Northeast"),
        _("East"), _("East-Southeast"), _("Southeast"), _("South-Southeast"),
        _("South"), _("South-Southwest"), _("Southwest"), _("West-Southwest"),
        _("West"), _("West-Northwest"), _("Northwest"), _("North-Northwest")
    ]
    idx = int((degrees + 11.25) / 22.5) % 16
    return directions[idx]


def getMoonPhaseName(phase):
    """Convert moon phase (0 to 1 value) to text description."""
    if phase is None:
        return _("Unknown")
    
    if phase < 0.01 or phase > 0.99:
        return _("New Moon")
    elif phase < 0.24:
        return _("Waxing Crescent")
    elif abs(phase - 0.25) < 0.01:
        return _("First Quarter")
    elif phase < 0.49:
        return _("Waxing Gibbous")
    elif abs(phase - 0.50) < 0.01:
        return _("Full Moon")
    elif phase < 0.74:
        return _("Waning Gibbous")
    elif abs(phase - 0.75) < 0.01:
        return _("Last Quarter")
    else:
        return _("Waning Crescent")


def formatTimestamp(ts):
    """Convert a unix timestamp to a formatted time string in local time."""
    if not ts:
        return _("N/A")
    try:
        dt = datetime.datetime.fromtimestamp(ts)
        return dt.strftime("%I:%M %p")
    except Exception:
        return _("N/A")


def formatDay(ts):
    """Convert unix timestamp to day of the week."""
    if not ts:
        return ""
    try:
        dt = datetime.datetime.fromtimestamp(ts)
        return dt.strftime("%A")
    except Exception:
        return ""


# ----------------------------------------------------
# GitHub-based Add-on Version Checker
# ----------------------------------------------------
def checkForUpdates():
    """
    Check for add-on updates on GitHub releases.
    Returns (update_available, latest_version, download_url, release_notes)
    """
    try:
        addon = addonHandler.getCodeAddon()
        current_version = addon.manifest.version
    except Exception:
        current_version = "1.0.4"
    url = "https://api.github.com/repos/swarup-developer/weatherChecker-addon/releases/latest"
    headers = {
        "User-Agent": "WeatherCheckerNVDAUpdateChecker/1.0 (Contact: swarup.baral@example.com)"
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            tag = data.get("tag_name", "1.0.0").strip().lstrip("v")
            
            assets = data.get("assets", [])
            download_url = ""
            for asset in assets:
                asset_name = asset.get("name", "")
                if asset_name.endswith(".nvda-addon"):
                    download_url = asset.get("browser_download_url", "")
                    break
            if not download_url:
                download_url = data.get("html_url", "https://github.com/swarup-developer/weatherChecker-addon")
                
            body = data.get("body", "")
            
            # Semantic Version check
            try:
                curr_parts = [int(p) for p in current_version.split(".")]
                tag_parts = [int(p) for p in tag.split(".")]
                
                # Zero pad to same length if needed
                max_len = max(len(curr_parts), len(tag_parts))
                curr_parts += [0] * (max_len - len(curr_parts))
                tag_parts += [0] * (max_len - len(tag_parts))
                
                update_available = tag_parts > curr_parts
            except Exception:
                update_available = tag != current_version
                
            return update_available, tag, download_url, body
        elif resp.status_code == 404:
            # No releases published yet
            return False, current_version, "", ""
        else:
            raise WeatherClientError(f"HTTP Error {resp.status_code} while checking for updates.")
    except requests.RequestException as e:
        raise NetworkError(_("Network failure while checking for updates: ") + str(e))


def downloadAndInstallUpdate(latest_version, download_url):
    """
    Downloads the nvda-addon file and installs it programmatically,
    then prompts to restart NVDA.
    """
    import os
    import tempfile
    import threading
    import requests
    from logHandler import log
    
    def run():
        import speech
        import addonHandler
        import gui
        import core
        import wx
        
        wx.CallAfter(speech.speakMessage, _("Downloading Weather Checker update..."))
        
        try:
            resp = requests.get(download_url, stream=True, timeout=60)
            resp.raise_for_status()
            
            temp_dir = tempfile.gettempdir()
            temp_path = os.path.join(temp_dir, f"weatherChecker-{latest_version}.nvda-addon")
            
            with open(temp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    
            wx.CallAfter(speech.speakMessage, _("Installing update..."))
            
            bundle = addonHandler.AddonBundle(temp_path)
            addon = addonHandler.installAddonBundle(bundle)
            if addon is None:
                raise Exception("addonHandler failed to install the addon bundle.")
                
            try:
                os.remove(temp_path)
            except Exception:
                pass
                
            def ask_restart():
                msg = _("Weather Checker has been updated to version {version}. You must restart NVDA for the changes to take effect. Would you like to restart now?").format(version=latest_version)
                resp = gui.messageBox(
                    message=msg,
                    caption=_("Restart NVDA"),
                    style=wx.YES_NO | wx.ICON_QUESTION
                )
                if resp == wx.YES:
                    core.restart()
            wx.CallAfter(ask_restart)
            
        except Exception as e:
            log.error("Failed to download and install update", exc_info=True)
            error_msg = _("Update failed: ") + str(e)
            wx.CallAfter(speech.speakMessage, error_msg)
            wx.CallAfter(gui.messageBox, error_msg, _("Update Failed"), wx.OK | wx.ICON_ERROR)
            
    t = threading.Thread(target=run)
    t.daemon = True
    t.start()


class UpdatePromptDialog(wx.Dialog):
    """Dialog to prompt the user about a new add-on update, displaying the changelog in a readable read-only edit box."""
    def __init__(self, parent, latest_version, body):
        import wx
        super().__init__(parent, title=_("Weather Checker Update"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.latest_version = latest_version
        self.body = body
        self._buildGui()
        
    def _buildGui(self):
        import wx
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        
        infoText = wx.StaticText(self, label=_("New version detected, update add-on - {version}").format(version=self.latest_version))
        mainSizer.Add(infoText, 0, wx.ALL | wx.EXPAND, 10)
        
        if self.body and self.body.strip():
            whatsNewLabel = wx.StaticText(self, label=_("What's new in this version:"))
            mainSizer.Add(whatsNewLabel, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 10)
            
            # Read-only multiline edit field for release notes
            self.notesCtrl = wx.TextCtrl(self, value=self.body.strip(), style=wx.TE_MULTILINE | wx.TE_READONLY, size=(450, 200))
            mainSizer.Add(self.notesCtrl, 1, wx.ALL | wx.EXPAND, 10)
            
        promptText = wx.StaticText(self, label=_("Do you want to update now?"))
        mainSizer.Add(promptText, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        
        btnSizer = self.CreateButtonSizer(wx.YES | wx.NO)
        mainSizer.Add(btnSizer, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        
        # Set focus to YES button by default
        yesBtn = self.FindWindowById(wx.ID_YES)
        if yesBtn:
            yesBtn.SetFocus()
            
        self.SetSizerAndFit(mainSizer)
        self.CentreOnParent()


def promptUpdate(latest_version, download_url, body, parent=None):
    """
    Shows a Yes/No dialog to prompt the user to update.
    """
    import wx
    
    dlg = UpdatePromptDialog(parent, latest_version, body)
    resp = dlg.ShowModal()
    dlg.Destroy()
    
    if resp == wx.ID_YES:
        downloadAndInstallUpdate(latest_version, download_url)

