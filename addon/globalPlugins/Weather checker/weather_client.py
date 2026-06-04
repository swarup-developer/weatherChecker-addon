# -*- coding: utf-8 -*-
# Weather Client for Weather Checker NVDA add-on

import requests
import time
import datetime
from logHandler import log
import addonHandler

try:
    import wx
except ImportError:
    wx = None

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


# Bundled geocode.maps.co API key for reliable location search
MAPS_CO_API_KEY = "6a218bad06dc3956819174ndibaa210"


def _parse_nominatim_results(results, query):
    """Parse Nominatim-compatible JSON (used by both Nominatim and maps.co) into a standard list."""
    if not results:
        raise GeocodingError(_("No locations found for: ") + query)
    formatted = []
    for item in results:
        display_name = item.get("display_name", "")
        address = item.get("address", {})
        name = (address.get("city") or address.get("town") or address.get("village") or
                address.get("suburb") or address.get("hamlet") or address.get("municipality") or
                address.get("county") or display_name.split(",")[0])
        region = address.get("state") or address.get("province") or address.get("county") or ""
        country = address.get("country") or ""
        formatted.append({
            "name": name,
            "region": region,
            "country": country,
            "lat": float(item.get("lat", 0)),
            "lon": float(item.get("lon", 0))
        })
    return formatted


def geocodeLocation(query, provider, openWeatherKey):
    """
    Search for location matching query.
    Priority:
      1. OpenWeather Geocoding API (if OW key is available)
      2. geocode.maps.co (keyed — reliable, no rate-limit issues)
      3. OpenStreetMap Nominatim (last resort — may be rate-limited)
    """
    if not query or not query.strip():
        raise GeocodingError(_("Search query cannot be empty."))

    query = query.strip()

    # --- 1. OpenWeather Geocoding (if key available) ---
    if openWeatherKey and provider in (0, 2):
        url = f"https://api.openweathermap.org/geo/1.0/direct?q={requests.utils.quote(query)}&limit=10&appid={openWeatherKey}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                results = resp.json()
                if results:
                    return [{
                        "name": item.get("name", ""),
                        "region": item.get("state", ""),
                        "country": item.get("country", ""),
                        "lat": float(item.get("lat", 0)),
                        "lon": float(item.get("lon", 0))
                    } for item in results]
            elif resp.status_code == 401:
                log.warning("OpenWeather geocoding key invalid, falling back.")
            else:
                log.warning(f"OpenWeather geocoding HTTP {resp.status_code}, falling back.")
        except Exception as e:
            log.warning(f"OpenWeather geocoding failed: {e}, falling back.")

    # --- 2. geocode.maps.co (keyed, primary fallback) ---
    try:
        maps_url = f"https://geocode.maps.co/search?q={requests.utils.quote(query)}&api_key={MAPS_CO_API_KEY}"
        resp = requests.get(maps_url, timeout=10,
                            headers={"User-Agent": "WeatherCheckerNVDA/2.0"})
        if resp.status_code == 200:
            results = resp.json()
            if results:
                return _parse_nominatim_results(results, query)
            log.info("geocode.maps.co returned no results, trying Nominatim.")
        else:
            log.warning(f"geocode.maps.co HTTP {resp.status_code}, falling back to Nominatim.")
    except Exception as e:
        log.warning(f"geocode.maps.co failed: {e}, falling back to Nominatim.")

    # --- 3. OpenStreetMap Nominatim (last resort) ---
    try:
        nom_url = f"https://nominatim.openstreetmap.org/search?q={requests.utils.quote(query)}&format=json&limit=10&addressdetails=1"
        headers = {"User-Agent": "WeatherCheckerNVDA/2.0 (Contact: swarup.baral@example.com)"}
        resp = requests.get(nom_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return _parse_nominatim_results(resp.json(), query)
        elif resp.status_code in (403, 429):
            raise GeocodingError(_("All geocoding services are currently busy. Please try again in a moment."))
        else:
            raise GeocodingError(f"Nominatim HTTP Error {resp.status_code}: {resp.reason}")
    except GeocodingError:
        raise
    except Exception as e:
        raise NetworkError(_("Network failure while geocoding: ") + str(e))


def detectLocationIP():
    """
    Detect location using IP-based geolocation.
    Tries multiple free services in sequence so one rate-limit doesn't break detection.
    Returns {"lat": lat, "lon": lon, "name": name, "country": country}
    """
    last_error = None

    # --- Service 1: ipwho.is ---
    try:
        resp = requests.get("https://ipwho.is/", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success"):
                city = data.get("city", "")
                region = data.get("region", "")
                country = data.get("country", "")
                lat = data.get("latitude")
                lon = data.get("longitude")
                if lat is not None and lon is not None:
                    name_parts = [p for p in [city, region] if p]
                    name = ", ".join(name_parts) if name_parts else _("Detected Location")
                    return {"lat": float(lat), "lon": float(lon), "name": name, "country": country}
        log.warning("ipwho.is returned no usable data, trying fallback.")
    except Exception as e:
        last_error = e
        log.warning(f"ipwho.is failed: {e}, trying fallback.")

    # --- Service 2: ip-api.com (free tier, no key needed) ---
    try:
        resp = requests.get("http://ip-api.com/json/?fields=status,city,regionName,country,lat,lon", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                city = data.get("city", "")
                region = data.get("regionName", "")
                country = data.get("country", "")
                lat = data.get("lat")
                lon = data.get("lon")
                if lat is not None and lon is not None:
                    name_parts = [p for p in [city, region] if p]
                    name = ", ".join(name_parts) if name_parts else _("Detected Location")
                    return {"lat": float(lat), "lon": float(lon), "name": name, "country": country}
        log.warning("ip-api.com returned no usable data, trying fallback.")
    except Exception as e:
        last_error = e
        log.warning(f"ip-api.com failed: {e}, trying fallback.")

    # --- Service 3: ipapi.co ---
    try:
        resp = requests.get("https://ipapi.co/json/", timeout=10,
                            headers={"User-Agent": "WeatherCheckerNVDA/2.0"})
        if resp.status_code == 200:
            data = resp.json()
            lat = data.get("latitude")
            lon = data.get("longitude")
            if lat is not None and lon is not None:
                city = data.get("city", "")
                region = data.get("region", "")
                country = data.get("country_name", "")
                name_parts = [p for p in [city, region] if p]
                name = ", ".join(name_parts) if name_parts else _("Detected Location")
                return {"lat": float(lat), "lon": float(lon), "name": name, "country": country}
        log.warning("ipapi.co returned no usable data.")
    except Exception as e:
        last_error = e
        log.warning(f"ipapi.co failed: {e}")

    raise GeocodingError(
        _("Could not auto-detect location. All IP geolocation services are unavailable. Please set your location manually in settings.")
    )


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

# Module-level session state — resets every time NVDA starts (never persisted)
_update_session_dismissed = set()   # versions user said "No" to this session
_update_check_scheduled = False     # guard: only one startup check per session


def _normalize_version(v):
    """
    Normalize a version string for reliable integer comparison.
    Eliminates leading zeros in each segment.
    '2.0.05' -> [2, 0, 5]   '2.0.5' -> [2, 0, 5]   'v2.1' -> [2, 1]
    """
    parts = []
    for p in str(v).strip().lstrip("v").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return parts


def _versions_equal(a, b):
    """Return True if two version strings represent the same version."""
    va = _normalize_version(a)
    vb = _normalize_version(b)
    max_len = max(len(va), len(vb))
    va += [0] * (max_len - len(va))
    vb += [0] * (max_len - len(vb))
    return va == vb


def _version_is_newer(candidate, current):
    """Return True if candidate version is strictly newer than current."""
    vc = _normalize_version(candidate)
    vn = _normalize_version(current)
    max_len = max(len(vc), len(vn))
    vc += [0] * (max_len - len(vc))
    vn += [0] * (max_len - len(vn))
    return vc > vn


def _get_installed_version():
    """
    Read the currently installed add-on version.
    Tries addonHandler first; falls back to the buildVars constant.
    """
    try:
        addon = addonHandler.getCodeAddon()
        # manifest behaves like a dict — use subscript access, not attribute
        v = addon.manifest["version"]
        if v and str(v).strip():
            return str(v).strip()
    except Exception:
        pass
    # Hard-coded fallback that always matches current buildVars
    return "3.0.1"


def checkForUpdates():
    """
    Query GitHub for the latest release and compare against the installed version.

    Returns:
        (update_available: bool,
         latest_version:   str,
         download_url:     str,
         release_notes:    str)

    Raises WeatherClientError / NetworkError on unrecoverable failures.
    """
    current_version = _get_installed_version()

    api_url = "https://api.github.com/repos/swarup-developer/weatherChecker-addon/releases/latest"
    headers = {"User-Agent": "WeatherCheckerNVDA/2.0 (weatherchecker-addon update check)"}

    try:
        resp = requests.get(api_url, headers=headers, timeout=15)
    except requests.exceptions.ConnectionError:
        raise NetworkError(_(
            "Could not connect to the update server. Please check your internet connection."
        ))
    except requests.exceptions.Timeout:
        raise NetworkError(_(
            "Update check timed out. The server did not respond in time."
        ))
    except requests.RequestException as e:
        raise NetworkError(_(
            "Network failure while checking for updates: "
        ) + str(e))

    if resp.status_code == 404:
        # No releases published on this repository yet
        log.info("Update check: no releases found (404).")
        return False, current_version, "", ""

    if resp.status_code == 403:
        # GitHub API rate limit
        raise WeatherClientError(_(
            "Update check was rate-limited by GitHub. Please try again later."
        ))

    if resp.status_code != 200:
        raise WeatherClientError(_(
            "Update server returned an unexpected response (HTTP {code})."
        ).format(code=resp.status_code))

    try:
        data = resp.json()
    except ValueError:
        raise WeatherClientError(_(
            "Update server returned an invalid response. Please try again later."
        ))

    # Extract tag — strip leading 'v' for clean comparison
    tag_raw = data.get("tag_name", "").strip()
    if not tag_raw:
        log.warning("Update check: release has no tag_name.")
        return False, current_version, "", ""
    latest_version = tag_raw.lstrip("v")

    # Find the .nvda-addon asset download URL
    download_url = ""
    for asset in data.get("assets", []):
        if asset.get("name", "").endswith(".nvda-addon"):
            download_url = asset.get("browser_download_url", "")
            break
    if not download_url:
        # Fall back to the HTML release page so the user can download manually
        download_url = data.get("html_url",
                                "https://github.com/swarup-developer/weatherChecker-addon/releases")

    release_notes = data.get("body", "") or ""

    update_available = _version_is_newer(latest_version, current_version)

    log.info(
        f"Update check complete: installed={current_version}, "
        f"latest={latest_version}, update_available={update_available}"
    )
    return update_available, latest_version, download_url, release_notes


def _save_update_state(key, value):
    """Safely persist an update tracking value to NVDA config."""
    try:
        import config as _cfg
        _cfg.conf["weatherChecker"][key] = value
        _cfg.conf.save()
    except Exception as e:
        log.warning(f"Could not save update state [{key}]: {e}")


def _read_update_state(key, default=""):
    """Safely read an update tracking value from NVDA config."""
    try:
        import config as _cfg
        val = _cfg.conf["weatherChecker"][key]
        return val if val is not None else default
    except Exception:
        return default


def promptUpdate(latest_version, download_url, release_notes, parent=None, force=False):
    """
    Gate-checks and shows the update dialog.

    Anti-spam rules (all bypassed when force=True, e.g. manual "Check Now" button):
      1. If user already installed this version → silent skip.
      2. If user dismissed this version this session → silent skip.

    Args:
        force: When True (manual check from settings), bypass session-dismissal so
               the dialog always appears even if the user said No earlier.
    """
    import wx
    import gui as _gui

    lv = latest_version.strip().lstrip("v")

    if not force:
        # Rule 1 — user already installed this version (persisted across restarts)
        last_installed = _read_update_state("lastUpdatedVersion")
        if last_installed and _versions_equal(last_installed, lv):
            log.info(f"Update prompt suppressed: v{lv} already installed.")
            return

        # Rule 2 — user said No this session (in-memory, resets on NVDA restart)
        if lv in _update_session_dismissed:
            log.info(f"Update prompt suppressed: user dismissed v{lv} this session.")
            return

    # Use mainFrame as fallback parent so the dialog always has a valid owner
    if parent is None:
        try:
            parent = _gui.mainFrame
        except Exception:
            parent = None

    # Show the update dialog
    try:
        dlg = UpdatePromptDialog(parent, lv, release_notes)
        result = dlg.ShowModal()
        dlg.Destroy()
    except Exception as e:
        log.error(f"Update dialog failed to display: {e}", exc_info=True)
        return

    if result == wx.ID_YES:
        _save_update_state("lastOfferedVersion", lv)
        # Remove from dismissed set so re-prompt works after install
        _update_session_dismissed.discard(lv)
        downloadAndInstallUpdate(lv, download_url)
    else:
        # Declined — remember for this session only
        _update_session_dismissed.add(lv)
        log.info(
            f"User declined update to v{lv}. "
            "Will not prompt again this session. "
            "Will re-offer after NVDA restart."
        )


def downloadAndInstallUpdate(latest_version, download_url):
    """
    Downloads the .nvda-addon file in a background thread and installs it on the
    main wx thread.  Records lastUpdatedVersion on success so the prompt is
    permanently suppressed for this version.
    """
    import os
    import tempfile
    import threading
    import requests as _requests

    def _run():
        import speech
        import addonHandler as _ah
        import gui
        import core
        import wx

        wx.CallAfter(speech.speakMessage, _(
            "Downloading Weather Checker update. Please wait..."
        ))

        temp_path = None
        try:
            dl_headers = {
                "User-Agent": "WeatherCheckerNVDA/2.0 (addon update download)"
            }
            dl_resp = _requests.get(
                download_url, headers=dl_headers, stream=True, timeout=60
            )
            dl_resp.raise_for_status()

            temp_path = os.path.join(
                tempfile.gettempdir(),
                f"weatherChecker-{latest_version}.nvda-addon"
            )
            with open(temp_path, "wb") as fp:
                for chunk in dl_resp.iter_content(chunk_size=8192):
                    if chunk:
                        fp.write(chunk)

            def _install_on_main_thread():
                nonlocal temp_path
                try:
                    speech.speakMessage(_(
                        "Installing Weather Checker update..."
                    ))

                    bundle = _ah.AddonBundle(temp_path)
                    bundle_name = bundle.manifest["name"]

                    # Mark existing version for removal before installing new one
                    for existing in list(_ah.getAvailableAddons()):
                        if existing.manifest["name"] == bundle_name:
                            log.info(
                                f"Marking {bundle_name} "
                                f"v{existing.manifest['version']} for removal."
                            )
                            existing.requestRemove()
                            break

                    installed = _ah.installAddonBundle(bundle)
                    # installAddonBundle schedules install for next NVDA restart.
                    # It returns the addon reference on success; None means the
                    # bundle was rejected (e.g. incompatible NVDA version).
                    if installed is None:
                        raise RuntimeError(
                            "The add-on bundle was rejected by NVDA "
                            "(possibly incompatible with your NVDA version)."
                        )

                    # Persist the installed version — suppresses future prompts
                    _save_update_state("lastUpdatedVersion", latest_version)
                    _save_update_state("lastOfferedVersion", latest_version)

                    # Clean up temp file
                    try:
                        os.remove(temp_path)
                        temp_path = None
                    except OSError:
                        pass

                    # Offer restart
                    restart_msg = _(
                        "Weather Checker has been updated to version {ver}. "
                        "You must restart NVDA for the changes to take effect. "
                        "Would you like to restart now?"
                    ).format(ver=latest_version)
                    if gui.messageBox(
                        message=restart_msg,
                        caption=_("Restart NVDA"),
                        style=wx.YES_NO | wx.ICON_QUESTION
                    ) == wx.YES:
                        core.restart()

                except Exception as exc:
                    log.error(
                        "Failed to install Weather Checker update.", exc_info=True
                    )
                    err_msg = _(
                        "Weather Checker update failed: {err}"
                    ).format(err=str(exc))
                    speech.speakMessage(err_msg)
                    gui.messageBox(err_msg, _("Update Failed"), wx.OK | wx.ICON_ERROR)
                finally:
                    if temp_path and os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except OSError:
                            pass

            wx.CallAfter(_install_on_main_thread)

        except Exception as exc:
            log.error(
                "Failed to download Weather Checker update.", exc_info=True
            )
            err_msg = _(
                "Weather Checker update download failed: {err}"
            ).format(err=str(exc))
            wx.CallAfter(speech.speakMessage, err_msg)
            wx.CallAfter(
                gui.messageBox, err_msg, _("Update Failed"), wx.OK | wx.ICON_ERROR
            )
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    t = threading.Thread(target=_run, name="WCUpdateDownload", daemon=True)
    t.start()


class UpdatePromptDialog(wx.Dialog):
    """
    Accessible dialog shown when a newer version is available.
    Displays version info and optional release notes.
    Inherits wx.Dialog directly (wx is always available when NVDA runs).
    """
    def __init__(self, parent, latest_version, release_notes):
        import wx
        super().__init__(
            parent,
            title=_("Weather Checker — Update Available"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        )
        self.latest_version = latest_version
        self.release_notes = release_notes
        self._build_gui()

    def _build_gui(self):
        import wx
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Main message — matches spec exactly
        msg = _(
            "A new version of Weather Checker is available (version {ver}). "
            "Would you like to update now?"
        ).format(ver=self.latest_version)
        info = wx.StaticText(self, label=msg)
        info.Wrap(440)
        sizer.Add(info, 0, wx.ALL | wx.EXPAND, 12)

        # Release notes (optional)
        if self.release_notes and self.release_notes.strip():
            notes_label = wx.StaticText(self, label=_("What's new:"))
            sizer.Add(notes_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
            notes_ctrl = wx.TextCtrl(
                self,
                value=self.release_notes.strip(),
                style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_AUTO_URL,
                size=(440, 180)
            )
            sizer.Add(notes_ctrl, 1, wx.ALL | wx.EXPAND, 12)

        btn_sizer = self.CreateButtonSizer(wx.YES | wx.NO)
        sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 12)

        # Accessible: focus the YES button so screen readers announce it first
        yes_btn = self.FindWindowById(wx.ID_YES)
        if yes_btn:
            yes_btn.SetFocus()

        self.SetSizerAndFit(sizer)
        self.CentreOnParent()
