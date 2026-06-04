# -*- coding: utf-8 -*-
# Configuration manager for Weather Checker NVDA add-on

import config
import os
import json
import time
import NVDAState

# Configuration specification dictionary
confspec_dict = {
    "weatherChecker": {
        "provider": "integer(default=0)",                  # 0: OpenWeather, 1: Pirate Weather, 2: OpenWeather + Pirate Weather
        "openWeatherApiKey": "string(default='')",
        "pirateWeatherApiKey": "string(default='')",
        "autoDetectLocation": "boolean(default=false)",
        "defaultLat": "string(default='')",
        "defaultLon": "string(default='')",
        "defaultLocationName": "string(default='')",
        "firstRun": "boolean(default=true)",
        
        # Granular Unit Settings
        "unit_temp": "integer(default=0)",                 # 0: Celsius, 1: Fahrenheit
        "unit_wind": "integer(default=0)",                 # 0: m/s, 1: km/h, 2: mph
        "unit_pressure": "integer(default=0)",             # 0: hPa, 1: inHg
        "unit_visibility": "integer(default=0)",           # 0: Kilometers, 1: Miles
        
        # Favorite Locations (JSON serialized string)
        "favorites": "string(default='[]')",
        "current_favorite_index": "integer(default=-1)",
        
        # Update Settings
        "auto_update_check": "boolean(default=true)",
        "copy_to_clipboard": "boolean(default=false)",
        "skippedUpdateVersion": "string(default='')",
        
        # Weather Information options (to speak/announce)
        "info_currentWeather": "boolean(default=true)",
        "info_temperature": "boolean(default=true)",
        "info_feelsLike": "boolean(default=true)",
        "info_humidity": "boolean(default=true)",
        "info_windSpeed": "boolean(default=true)",
        "info_windDirection": "boolean(default=true)",
        "info_pressure": "boolean(default=true)",
        "info_visibility": "boolean(default=true)",
        "info_uvIndex": "boolean(default=true)",
        "info_clouds": "boolean(default=true)",
        "info_dewPoint": "boolean(default=true)",
        "info_airQuality": "boolean(default=true)",
        
        # Forecast Settings
        "forecast_type": "integer(default=3)",             # 0: Hourly, 1: 12-hour, 2: 24-hour, 3: Daily, 4: 7-day, 5: 10-day
        "forecast_entries": "integer(default=3)",          # Number of forecast entries to announce
        
        # Astronomy Settings
        "astro_sunrise": "boolean(default=true)",
        "astro_sunset": "boolean(default=true)",
        "astro_moonrise": "boolean(default=true)",
        "astro_moonset": "boolean(default=true)",
        "astro_moonphase": "boolean(default=true)",
        
        # Weather Alerts Settings (Warning types to alert)
        "alert_severe": "boolean(default=true)",
        "alert_thunderstorm": "boolean(default=true)",
        "alert_heavyRain": "boolean(default=true)",
        "alert_flood": "boolean(default=true)",
        "alert_snow": "boolean(default=true)",
        "alert_heat": "boolean(default=true)",
        "alert_cold": "boolean(default=true)",
        "alert_wind": "boolean(default=true)",
        "alert_hurricane": "boolean(default=true)",
        "alert_tornado": "boolean(default=true)",
        "alert_fog": "boolean(default=true)",
        "alert_airQuality": "boolean(default=true)",
        
        # Alert behavior
        "alert_speakAuto": "boolean(default=false)",       # Speak alerts automatically
        "alert_showDialog": "boolean(default=false)",      # Show alerts in accessible dialogs
        "alert_showNotification": "boolean(default=true)",  # Display NVDA notifications
        "alert_repeatInterval": "integer(default=0)",      # Choice: 0: Disabled, 1: 5m, 2: 10m, 3: 15m, 4: 30m, 5: 60m
        "alert_severityFilter": "integer(default=0)",      # 0: All, 1: Moderate+, 2: Severe+, 3: Extreme
        
        # Cache for auto detected location
        "cachedLat": "string(default='')",
        "cachedLon": "string(default='')",
        "cachedLocationName": "string(default='')",
        "cachedTime": "float(default=0.0)"
    }
}

def registerConfig():
    """Register the Weather Checker config specification with NVDA's config system."""
    config.conf.spec.update(confspec_dict)

def getConfigVal(key):
    """Retrieve a config value under the weatherChecker section."""
    try:
        return config.conf["weatherChecker"][key]
    except Exception:
        # Fallback if config is accessed before initialization or key doesn't exist
        registerConfig()
        return config.conf["weatherChecker"][key]

def setConfigVal(key, value):
    """Set a config value under the weatherChecker section."""
    try:
        config.conf["weatherChecker"][key] = value
    except Exception:
        registerConfig()
        config.conf["weatherChecker"][key] = value


# ----------------------------------------------------
# Weather History JSON Database Helpers
# ----------------------------------------------------
def getHistoryFilePath():
    """Get the path to store weather history inside NVDA's config directory."""
    return os.path.join(NVDAState.WritePaths.configDir, "weather_checker_history.json")

def loadHistory():
    """Load weather history from local JSON file."""
    path = getHistoryFilePath()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def saveHistory(history):
    """Save weather history to local JSON file."""
    path = getHistoryFilePath()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def addHistoryEntry(location_name, weather_data, lat, lon):
    """Log a weather fetch request into history."""
    history = loadHistory()
    
    # Structure of history entry
    entry = {
        "timestamp": time.time(),
        "location": location_name,
        "lat": lat,
        "lon": lon,
        "providers": {}
    }
    
    for prov, data in weather_data.items():
        curr = data.get("current", {})
        # Map parameters
        entry["providers"][prov] = {
            "condition": curr.get("condition"),
            "temp": curr.get("temp"),
            "feels_like": curr.get("feels_like"),
            "humidity": curr.get("humidity"),
            "wind_speed": curr.get("wind_speed"),
            "wind_dir": curr.get("wind_dir"),
            "pressure": curr.get("pressure"),
            "visibility": curr.get("visibility"),
            "uvi": curr.get("uvi"),
            "clouds": curr.get("clouds"),
            "dew_point": curr.get("dew_point"),
            "aqi": curr.get("aqi")
        }
        # Save forecast and alerts for offline history review
        entry["providers"][prov]["forecast"] = data.get("daily", [])[:3]
        entry["providers"][prov]["alerts"] = data.get("alerts", [])
        
    history.insert(0, entry)
    # Cap at 20 entries to save space
    history = history[:20]
    saveHistory(history)
