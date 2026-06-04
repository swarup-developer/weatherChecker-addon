# -*- coding: utf-8 -*-
# Weather Checker NVDA Add-on
# Entry point global plugin implementation

import globalPluginHandler
import gui
import ui
import speech
import api
import wx
import threading
import time
import json
from . import config_manager
from . import weather_client
from .settings_panel import WeatherCheckerSettingsPanel
import addonHandler

addonHandler.initTranslation()

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    # Bind gestures to their script handlers
    __gestures = {
        "kb:NVDA+shift+w": "speakCurrentWeather",
        "kb:NVDA+shift+f": "speakForecast",
        "kb:NVDA+shift+a": "speakActiveAlerts",
        "kb:NVDA+shift+s": "speakAstronomy",
        "kb:NVDA+shift+l": "cycleFavoriteLocations"
    }

    def __init__(self):
        super().__init__()
        
        # Initialize configuration schema
        config_manager.registerConfig()
        
        # Register settings category in NVDA
        from gui.settingsDialogs import NVDASettingsDialog
        if WeatherCheckerSettingsPanel not in NVDASettingsDialog.categoryClasses:
            NVDASettingsDialog.categoryClasses.append(WeatherCheckerSettingsPanel)

        # Background alert checking state
        self.alertThread = None
        self.seenAlerts = set()
        self.lastAnnouncedAlerts = {}
        
        # Hotkey press timing for clipboard copy double-press detection
        self._last_w_press = 0.0
        self._last_f_press = 0.0
        self._last_a_press = 0.0
        self._last_s_press = 0.0

        # Start Alert Polling loop if configured
        self.startAlertChecker()

        # Check for first run and queue welcome message
        if config_manager.getConfigVal("firstRun"):
            wx.CallAfter(self.showFirstRunMessage)
        elif config_manager.getConfigVal("auto_update_check"):
            # Queue startup update check
            wx.CallAfter(self.startStartupUpdateCheck)

    def terminate(self):
        # Stop background alert thread
        self.stopAlertChecker()

        # Unregister settings panel category
        from gui.settingsDialogs import NVDASettingsDialog
        if WeatherCheckerSettingsPanel in NVDASettingsDialog.categoryClasses:
            NVDASettingsDialog.categoryClasses.remove(WeatherCheckerSettingsPanel)
            
        super().terminate()

    def showFirstRunMessage(self):
        gui.messageBox(
            message=_("Weather Checker requires one or more API keys before it can be used. Please open NVDA Settings and configure your weather provider."),
            caption=_("Weather Checker"),
            style=wx.OK | wx.ICON_INFORMATION
        )
        config_manager.setConfigVal("firstRun", False)
        import config
        config.conf.save()

    # ----------------------------------------------------
    # Location Resolution Helper
    # ----------------------------------------------------
    def resolveLocation(self):
        """
        Resolves coordinates (latitude, longitude, display name).
        Uses manually configured default location if present; otherwise, falls back to IP-based detection.
        """
        lat = config_manager.getConfigVal("defaultLat")
        lon = config_manager.getConfigVal("defaultLon")
        name = config_manager.getConfigVal("defaultLocationName")
        
        if lat and lon:
            return float(lat), float(lon), name
            
        # Fallback: Check cached location
        cached_lat = config_manager.getConfigVal("cachedLat")
        cached_lon = config_manager.getConfigVal("cachedLon")
        cached_name = config_manager.getConfigVal("cachedLocationName")
        cached_time = config_manager.getConfigVal("cachedTime")
        
        # Cache is valid for 1 hour
        if cached_lat and cached_lon and (time.time() - cached_time < 3600):
            return float(cached_lat), float(cached_lon), cached_name
            
        # Geocode IP
        loc = weather_client.detectLocationIP()
        config_manager.setConfigVal("cachedLat", str(loc["lat"]))
        config_manager.setConfigVal("cachedLon", str(loc["lon"]))
        config_manager.setConfigVal("cachedLocationName", loc["name"])
        config_manager.setConfigVal("cachedTime", time.time())
        import config
        config.conf.save()
        return loc["lat"], loc["lon"], loc["name"]

    # ----------------------------------------------------
    # Background Startup Update Checking
    # ----------------------------------------------------
    def startStartupUpdateCheck(self):
        """Starts a background update checker delay thread."""
        t = threading.Thread(target=self._runStartupUpdateCheck)
        t.daemon = True
        t.start()

    def _runStartupUpdateCheck(self):
        # Wait 15 seconds after NVDA starts so it doesn't interrupt speech initially
        time.sleep(15.0)
        try:
            update_available, latest_version, download_url, body = weather_client.checkForUpdates()
            if update_available:
                wx.CallAfter(weather_client.promptUpdate, latest_version, download_url, body)
        except Exception:
            pass

    # ----------------------------------------------------
    # Background Alert Polling Loop
    # ----------------------------------------------------
    def startAlertChecker(self):
        has_notif = (
            config_manager.getConfigVal("alert_speakAuto") or
            config_manager.getConfigVal("alert_showDialog") or
            config_manager.getConfigVal("alert_showNotification")
        )
        if not has_notif:
            return

        if self.alertThread is None:
            self.alertThread = AlertCheckerThread(self)
            self.alertThread.start()

    def stopAlertChecker(self):
        if self.alertThread:
            self.alertThread.stop()
            self.alertThread.join(timeout=1.0)
            self.alertThread = None

    def restartAlertChecker(self):
        self.stopAlertChecker()
        self.startAlertChecker()

    def getPollInterval(self):
        choice = config_manager.getConfigVal("alert_repeatInterval")
        intervals = {1: 300, 2: 600, 3: 900, 4: 1800, 5: 3600}
        return intervals.get(choice, 900)

    def checkAlerts(self):
        try:
            lat, lon, name = self.resolveLocation()
            provider = config_manager.getConfigVal("provider")
            ow_key = config_manager.getConfigVal("openWeatherApiKey")
            pw_key = config_manager.getConfigVal("pirateWeatherApiKey")
            
            weather_data = weather_client.fetchWeatherData(lat, lon, provider, ow_key, pw_key)
            
            if provider == 2:
                if "OpenWeather" in weather_data and "Pirate Weather" in weather_data:
                    weather_data = self.mergeWeatherData(weather_data)
            
            # Save fetched weather report to local history
            config_manager.addHistoryEntry(name, weather_data, lat, lon)
            
            for prov_name, prov_data in weather_data.items():
                alerts = prov_data.get("alerts", [])
                self._processProviderAlerts(prov_name, alerts)
        except Exception:
            pass

    def _processProviderAlerts(self, provider, alerts):
        severity_filter = config_manager.getConfigVal("alert_severityFilter")
        repeat_choice = config_manager.getConfigVal("alert_repeatInterval")
        
        repeat_intervals = {1: 300, 2: 600, 3: 900, 4: 1800, 5: 3600}
        repeat_seconds = repeat_intervals.get(repeat_choice, 0)
        
        filtered_alerts = []
        severity_levels = {"minor": 0, "moderate": 1, "severe": 2, "extreme": 3}
        
        for alert in alerts:
            title = alert.get("title", "")
            desc = alert.get("description", "")
            sev = alert.get("severity", "moderate").lower()
            
            level = severity_levels.get(sev, 1)
            if level < severity_filter:
                continue
                
            if self._matchesAlertCategories(title, desc):
                filtered_alerts.append(alert)

        now = time.time()
        for alert in filtered_alerts:
            title = alert.get("title", "")
            desc = alert.get("description", "")
            start = alert.get("start", 0)
            end = alert.get("end", 0)
            
            alert_id = (provider, title, start, end)
            
            if end and now > end:
                continue
                
            should_announce = False
            
            if alert_id not in self.seenAlerts:
                self.seenAlerts.add(alert_id)
                self.lastAnnouncedAlerts[alert_id] = now
                should_announce = True
            elif repeat_seconds > 0:
                last_time = self.lastAnnouncedAlerts.get(alert_id, 0)
                if now - last_time >= repeat_seconds:
                    self.lastAnnouncedAlerts[alert_id] = now
                    should_announce = True
            
            if should_announce:
                self._announceAlert(provider, title, desc)

    def _matchesAlertCategories(self, title, desc):
        text = (title + " " + desc).lower()
        
        mapping = {
            "alert_thunderstorm": ["thunderstorm", "lightning", "squall"],
            "alert_heavyRain": ["rain", "precipitation", "shower", "downpour"],
            "alert_flood": ["flood"],
            "alert_snow": ["snow", "blizzard", "sleet", "ice", "winter", "avalanche"],
            "alert_heat": ["heat", "warmth", "high temp"],
            "alert_cold": ["cold", "frost", "freeze", "chill", "low temp"],
            "alert_wind": ["wind", "gale", "draft"],
            "alert_hurricane": ["hurricane", "cyclone", "typhoon", "tropical"],
            "alert_tornado": ["tornado", "funnel", "twister"],
            "alert_fog": ["fog", "mist", "visibility"],
            "alert_airQuality": ["air quality", "smoke", "pollution", "pm2.5", "ozone"],
        }
        
        for setting_key, keywords in mapping.items():
            if config_manager.getConfigVal(setting_key):
                if any(k in text for k in keywords):
                    return True
                    
        if config_manager.getConfigVal("alert_severe"):
            if "severe" in text or "warning" in text or "danger" in text or "emergency" in text:
                return True
                
        return False

    def _announceAlert(self, provider, title, desc):
        message = _("Weather Warning from {provider}: {title}").format(provider=provider, title=title)
        full_desc = _("{title}: {description}").format(title=title, description=desc)
        
        if config_manager.getConfigVal("alert_speakAuto"):
            wx.CallAfter(speech.speakMessage, message)
            
        if config_manager.getConfigVal("alert_showNotification"):
            def show_toast():
                notification = wx.NotificationMessage(title=_("Weather Warning"), message=message)
                notification.Show()
            wx.CallAfter(show_toast)
            
        if config_manager.getConfigVal("alert_showDialog"):
            wx.CallAfter(
                gui.messageBox,
                message=full_desc,
                caption=_("Weather Alert Details"),
                style=wx.OK | wx.ICON_WARNING
            )

    # ----------------------------------------------------
    # Keyboard Commands (Scripts)
    def mergeWeatherData(self, weather_data):
        import datetime
        ow = weather_data.get("OpenWeather", {})
        pw = weather_data.get("Pirate Weather", {})
        
        merged = {}
        
        ow_curr = ow.get("current", {})
        pw_curr = pw.get("current", {})
        
        def avg(v1, v2):
            if v1 is None: return v2
            if v2 is None: return v1
            return (v1 + v2) / 2.0
            
        def combine_cond(c1, c2):
            if not c1: return c2
            if not c2: return c1
            if c1.strip().lower() == c2.strip().lower():
                return c1
            return f"{c1} / {c2}"
            
        merged["current"] = {
            "condition": combine_cond(ow_curr.get("condition"), pw_curr.get("condition")),
            "temp": avg(ow_curr.get("temp"), pw_curr.get("temp")),
            "feels_like": avg(ow_curr.get("feels_like"), pw_curr.get("feels_like")),
            "humidity": avg(ow_curr.get("humidity"), pw_curr.get("humidity")),
            "wind_speed": avg(ow_curr.get("wind_speed"), pw_curr.get("wind_speed")),
            "wind_dir": avg(ow_curr.get("wind_dir"), pw_curr.get("wind_dir")),
            "pressure": avg(ow_curr.get("pressure"), pw_curr.get("pressure")),
            "visibility": avg(ow_curr.get("visibility"), pw_curr.get("visibility")),
            "uvi": avg(ow_curr.get("uvi"), pw_curr.get("uvi")),
            "clouds": avg(ow_curr.get("clouds"), pw_curr.get("clouds")),
            "dew_point": avg(ow_curr.get("dew_point"), pw_curr.get("dew_point")),
            "aqi": ow_curr.get("aqi")
        }
        
        ow_astro = ow.get("astronomy", {})
        pw_astro = pw.get("astronomy", {})
        merged["astronomy"] = {
            "sunrise": ow_astro.get("sunrise") or pw_astro.get("sunrise"),
            "sunset": ow_astro.get("sunset") or pw_astro.get("sunset"),
            "moonrise": ow_astro.get("moonrise") or pw_astro.get("moonrise"),
            "moonset": ow_astro.get("moonset") or pw_astro.get("moonset"),
            "moon_phase": avg(ow_astro.get("moon_phase"), pw_astro.get("moon_phase"))
        }
        
        ow_hourly = {item["time"]: item for item in ow.get("hourly", []) if "time" in item}
        pw_hourly = {item["time"]: item for item in pw.get("hourly", []) if "time" in item}
        
        merged_hourly = []
        all_hourly_times = sorted(list(set(ow_hourly.keys()) | set(pw_hourly.keys())))
        for t in all_hourly_times:
            o_item = ow_hourly.get(t)
            p_item = pw_hourly.get(t)
            if o_item and p_item:
                merged_hourly.append({
                    "time": t,
                    "temp": avg(o_item.get("temp"), p_item.get("temp")),
                    "feels_like": avg(o_item.get("feels_like"), p_item.get("feels_like")),
                    "condition": combine_cond(o_item.get("condition"), p_item.get("condition"))
                })
            elif o_item:
                merged_hourly.append(o_item)
            elif p_item:
                merged_hourly.append(p_item)
        merged["hourly"] = merged_hourly
        
        def get_date(ts):
            return datetime.datetime.fromtimestamp(ts).date()
            
        ow_daily_by_date = {get_date(item["time"]): item for item in ow.get("daily", []) if "time" in item}
        pw_daily_by_date = {get_date(item["time"]): item for item in pw.get("daily", []) if "time" in item}
        
        merged_daily = []
        all_dates = sorted(list(set(ow_daily_by_date.keys()) | set(pw_daily_by_date.keys())))
        for d in all_dates:
            o_item = ow_daily_by_date.get(d)
            p_item = pw_daily_by_date.get(d)
            if o_item and p_item:
                merged_daily.append({
                    "time": o_item["time"],
                    "temp_min": avg(o_item.get("temp_min"), p_item.get("temp_min")),
                    "temp_max": avg(o_item.get("temp_max"), p_item.get("temp_max")),
                    "condition": combine_cond(o_item.get("condition"), p_item.get("condition")),
                    "sunrise": o_item.get("sunrise") or p_item.get("sunrise"),
                    "sunset": o_item.get("sunset") or p_item.get("sunset"),
                    "moon_phase": avg(o_item.get("moon_phase"), p_item.get("moon_phase"))
                })
            elif o_item:
                merged_daily.append(o_item)
            elif p_item:
                merged_daily.append(p_item)
        merged["daily"] = merged_daily
        
        alerts = []
        seen_titles = set()
        for alert in ow.get("alerts", []) + pw.get("alerts", []):
            title = alert.get("title", "").strip().lower()
            if title not in seen_titles:
                seen_titles.add(title)
                alerts.append(alert)
        merged["alerts"] = alerts
        
        return {"All Providers": merged}

    # ----------------------------------------------------
    def _runAsyncWeatherAction(self, report_func, copy_to_clipboard=False, lat=None, lon=None, location_name=None):
        """Runs weather fetching on a background thread."""
        thread = threading.Thread(
            target=self._asyncWeatherWrapper, 
            args=(report_func, copy_to_clipboard, lat, lon, location_name)
        )
        thread.daemon = True
        thread.start()

    def _asyncWeatherWrapper(self, report_func, copy_to_clipboard, lat, lon, location_name):
        try:
            if lat is None or lon is None:
                lat, lon, location_name = self.resolveLocation()
                
            provider = config_manager.getConfigVal("provider")
            ow_key = config_manager.getConfigVal("openWeatherApiKey")
            pw_key = config_manager.getConfigVal("pirateWeatherApiKey")
            
            # Fetch data
            weather_data = weather_client.fetchWeatherData(lat, lon, provider, ow_key, pw_key)
            
            warning = None
            if provider == 2:
                has_ow = "OpenWeather" in weather_data
                has_pw = "Pirate Weather" in weather_data
                
                if has_ow and has_pw:
                    weather_data = self.mergeWeatherData(weather_data)
                elif has_pw and not has_ow:
                    warning = _("OpenWeather is currently unavailable. Using Pirate Weather.")
                elif has_ow and not has_pw:
                    warning = _("Pirate Weather is currently unavailable. Using OpenWeather.")
            
            # Log to weather history!
            config_manager.addHistoryEntry(location_name, weather_data, lat, lon)
            
            if warning:
                wx.CallAfter(ui.message, warning)
                time.sleep(1.5)
                
            # Format and speak on main GUI thread
            wx.CallAfter(report_func, location_name, weather_data, copy_to_clipboard)
        except weather_client.WeatherClientError as e:
            wx.CallAfter(ui.message, _("Weather Checker Error: ") + str(e))
        except Exception as e:
            wx.CallAfter(ui.message, _("Weather Checker connection failed. Please check network and API key settings."))

    # Gesture 1: Speak Current Weather
    def script_speakCurrentWeather(self, gesture):
        now = time.time()
        copy_pref = config_manager.getConfigVal("copy_to_clipboard")
        if copy_pref or (now - self._last_w_press < 0.5):
            self._runAsyncWeatherAction(self._reportCurrentWeather, copy_to_clipboard=True)
        else:
            ui.message(_("Checking weather..."))
            self._runAsyncWeatherAction(self._reportCurrentWeather, copy_to_clipboard=False)
        self._last_w_press = now

    def _reportCurrentWeather(self, name, weather_data, copy_to_clipboard):
        unit_temp = config_manager.getConfigVal("unit_temp")
        unit_wind = config_manager.getConfigVal("unit_wind")
        unit_pressure = config_manager.getConfigVal("unit_pressure")
        unit_visibility = config_manager.getConfigVal("unit_visibility")
        
        reports = []
        
        for prov, data in weather_data.items():
            curr = data.get("current", {})
            parts = []
            
            if config_manager.getConfigVal("info_currentWeather") and curr.get("condition"):
                parts.append(_("Conditions: {cond}").format(cond=curr["condition"]))
                
            if config_manager.getConfigVal("info_temperature") and curr.get("temp") is not None:
                temp_val = weather_client.convertTemp(curr["temp"], unit_temp)
                deg = "°F" if unit_temp == 1 else "°C"
                parts.append(_("Temperature: {temp:.1f}{deg}").format(temp=temp_val, deg=deg))
                    
            if config_manager.getConfigVal("info_feelsLike") and curr.get("feels_like") is not None:
                feels_val = weather_client.convertTemp(curr["feels_like"], unit_temp)
                deg = "°F" if unit_temp == 1 else "°C"
                parts.append(_("Feels like: {feels:.1f}{deg}").format(feels=feels_val, deg=deg))
                    
            if config_manager.getConfigVal("info_humidity") and curr.get("humidity") is not None:
                parts.append(_("Humidity: {humidity}%").format(humidity=curr["humidity"]))
                
            if config_manager.getConfigVal("info_windSpeed") and curr.get("wind_speed") is not None:
                wind_val = weather_client.convertWindSpeed(curr["wind_speed"], unit_wind)
                unit_labels = {0: _("m/s"), 1: _("km/h"), 2: _("mph")}
                lbl = unit_labels.get(unit_wind, "")
                speed_str = _("{wind:.1f} {lbl}").format(wind=wind_val, lbl=lbl)
                    
                if config_manager.getConfigVal("info_windDirection") and curr.get("wind_dir") is not None:
                    dir_name = weather_client.getWindDirectionName(curr["wind_dir"])
                    parts.append(_("Wind: {speed} from {dir}").format(speed=speed_str, dir=dir_name))
                else:
                    parts.append(_("Wind: {speed}").format(speed=speed_str))
            elif config_manager.getConfigVal("info_windDirection") and curr.get("wind_dir") is not None:
                dir_name = weather_client.getWindDirectionName(curr["wind_dir"])
                parts.append(_("Wind direction: {dir}").format(dir=dir_name))
                
            if config_manager.getConfigVal("info_pressure") and curr.get("pressure") is not None:
                press_val = weather_client.convertPressure(curr["pressure"], unit_pressure)
                lbl = _("inHg") if unit_pressure == 1 else _("hPa")
                press_fmt = "{press:.2f}" if unit_pressure == 1 else "{press:.0f}"
                parts.append((_("Pressure: ") + press_fmt + " {lbl}").format(press=press_val, lbl=lbl))
                    
            if config_manager.getConfigVal("info_visibility") and curr.get("visibility") is not None:
                vis_val = weather_client.convertVisibility(curr["visibility"], unit_visibility)
                lbl = _("miles") if unit_visibility == 1 else _("km")
                parts.append(_("Visibility: {vis:.1f} {lbl}").format(vis=vis_val, lbl=lbl))
                    
            if config_manager.getConfigVal("info_uvIndex") and curr.get("uvi") is not None:
                parts.append(_("UV index: {uvi}").format(uvi=curr["uvi"]))
                
            if config_manager.getConfigVal("info_clouds") and curr.get("clouds") is not None:
                parts.append(_("Clouds: {clouds}%").format(clouds=curr["clouds"]))
                
            if config_manager.getConfigVal("info_dewPoint") and curr.get("dew_point") is not None:
                dew_val = weather_client.convertTemp(curr["dew_point"], unit_temp)
                deg = "°F" if unit_temp == 1 else "°C"
                parts.append(_("Dew point: {dew:.1f}{deg}").format(dew=dew_val, deg=deg))
                    
            if config_manager.getConfigVal("info_airQuality") and curr.get("aqi") is not None:
                parts.append(_("Air quality: {aqi}").format(aqi=curr["aqi"]))
                
            report_str = ", ".join(parts)
            if len(weather_data) > 1:
                reports.append(f"{prov}: {report_str}")
            else:
                reports.append(report_str)

        loc_header = _("Weather for {location}").format(location=name)
        full_msg = loc_header + ". " + ". ".join(reports)
        
        if copy_to_clipboard:
            api.setClipData(full_msg)
            ui.message(_("Current weather copied to clipboard."))
        else:
            ui.message(full_msg)

    # Gesture 2: Speak Forecast
    def script_speakForecast(self, gesture):
        now = time.time()
        copy_pref = config_manager.getConfigVal("copy_to_clipboard")
        if copy_pref or (now - self._last_f_press < 0.5):
            self._runAsyncWeatherAction(self._reportForecast, copy_to_clipboard=True)
        else:
            ui.message(_("Checking forecast..."))
            self._runAsyncWeatherAction(self._reportForecast, copy_to_clipboard=False)
        self._last_f_press = now

    def _reportForecast(self, name, weather_data, copy_to_clipboard):
        unit_temp = config_manager.getConfigVal("unit_temp")
        forecast_type = config_manager.getConfigVal("forecast_type")
        max_entries = config_manager.getConfigVal("forecast_entries")
        
        forecast_type_names = {
            0: _("Hourly forecast"),
            1: _("12-hour forecast"),
            2: _("24-hour forecast"),
            3: _("Daily forecast"),
            4: _("7-day forecast"),
            5: _("10-day forecast")
        }
        
        prov_reports = []
        for prov, data in weather_data.items():
            hourly_list = data.get("hourly", [])
            daily_list = data.get("daily", [])
            
            entries = []
            is_hourly = forecast_type in (0, 1, 2)
            
            if forecast_type == 0:
                entries = hourly_list[:max_entries]
            elif forecast_type == 1:
                candidates = [h for h in hourly_list if h["time"] <= time.time() + 12 * 3600]
                if not candidates:
                    candidates = hourly_list
                if len(candidates) <= max_entries:
                    entries = candidates
                else:
                    step = len(candidates) / float(max_entries)
                    entries = [candidates[int(i * step)] for i in range(max_entries)]
            elif forecast_type == 2:
                candidates = [h for h in hourly_list if h["time"] <= time.time() + 24 * 3600]
                if not candidates:
                    candidates = hourly_list
                if len(candidates) <= max_entries:
                    entries = candidates
                else:
                    step = len(candidates) / float(max_entries)
                    entries = [candidates[int(i * step)] for i in range(max_entries)]
            elif forecast_type == 3:
                entries = daily_list[:max_entries]
            elif forecast_type == 4:
                entries = daily_list[:min(max_entries, 7)]
            elif forecast_type == 5:
                entries = daily_list[:min(max_entries, 10)]

            formatted_entries = []
            for item in entries:
                t_str = weather_client.formatTimestamp(item["time"])
                cond = item.get("condition", "")
                
                if is_hourly:
                    temp_val = item.get("temp")
                    if temp_val is not None:
                        temp_val = weather_client.convertTemp(temp_val, unit_temp)
                        deg = "°F" if unit_temp == 1 else "°C"
                        temp_str = f"{temp_val:.1f}{deg}"
                    else:
                        temp_str = ""
                    formatted_entries.append(_("{time}: {cond}, {temp}").format(
                        time=t_str, cond=cond, temp=temp_str
                    ))
                else:
                    day_name = weather_client.formatDay(item["time"])
                    t_min = item.get("temp_min")
                    t_max = item.get("temp_max")
                    
                    if t_min is not None:
                        t_min = weather_client.convertTemp(t_min, unit_temp)
                    if t_max is not None:
                        t_max = weather_client.convertTemp(t_max, unit_temp)
                            
                    min_str = f"{t_min:.1f}°F" if unit_temp == 1 else f"{t_min:.1f}°C"
                    max_str = f"{t_max:.1f}°F" if unit_temp == 1 else f"{t_max:.1f}°C"
                    
                    formatted_entries.append(_("{day}: {cond}, Min {t_min}, Max {t_max}").format(
                        day=day_name, cond=cond, t_min=min_str, t_max=max_str
                    ))
                    
            prov_str = ". ".join(formatted_entries)
            if len(weather_data) > 1:
                prov_reports.append(f"{prov}: {prov_str}")
            else:
                prov_reports.append(prov_str)

        header = _("{type_name} for {location}").format(
            type_name=forecast_type_names.get(forecast_type, _("Forecast")),
            location=name
        )
        full_msg = header + ". " + ". ".join(prov_reports)
        
        if copy_to_clipboard:
            api.setClipData(full_msg)
            ui.message(_("Forecast copied to clipboard."))
        else:
            ui.message(full_msg)

    # Gesture 3: Speak Active Weather Alerts
    def script_speakActiveAlerts(self, gesture):
        now = time.time()
        copy_pref = config_manager.getConfigVal("copy_to_clipboard")
        if copy_pref or (now - self._last_a_press < 0.5):
            self._runAsyncWeatherAction(self._reportActiveAlerts, copy_to_clipboard=True)
        else:
            ui.message(_("Checking weather alerts..."))
            self._runAsyncWeatherAction(self._reportActiveAlerts, copy_to_clipboard=False)
        self._last_a_press = now

    def _reportActiveAlerts(self, name, weather_data, copy_to_clipboard):
        severity_filter = config_manager.getConfigVal("alert_severityFilter")
        reports = []
        severity_levels = {"minor": 0, "moderate": 1, "severe": 2, "extreme": 3}
        
        for prov, data in weather_data.items():
            prov_alerts = []
            for alert in data.get("alerts", []):
                title = alert.get("title", "")
                desc = alert.get("description", "")
                sev = alert.get("severity", "moderate").lower()
                
                level = severity_levels.get(sev, 1)
                if level < severity_filter:
                    continue
                    
                if self._matchesAlertCategories(title, desc):
                    prov_alerts.append(f"{title}: {desc}")
                    
            if prov_alerts:
                reports.append(f"{prov}: " + "; ".join(prov_alerts))

        if not reports:
            msg = _("No active weather alerts for {location}.").format(location=name)
        else:
            header = _("Active weather alerts for {location}").format(location=name)
            msg = header + ". " + ". ".join(reports)
            
        if copy_to_clipboard:
            api.setClipData(msg)
            ui.message(_("Weather alerts copied to clipboard."))
        else:
            ui.message(msg)

    # Gesture 4: Speak Astronomy
    def script_speakAstronomy(self, gesture):
        now = time.time()
        copy_pref = config_manager.getConfigVal("copy_to_clipboard")
        if copy_pref or (now - self._last_s_press < 0.5):
            self._runAsyncWeatherAction(self._reportAstronomy, copy_to_clipboard=True)
        else:
            ui.message(_("Checking astronomy data..."))
            self._runAsyncWeatherAction(self._reportAstronomy, copy_to_clipboard=False)
        self._last_s_press = now

    def _reportAstronomy(self, name, weather_data, copy_to_clipboard):
        reports = []
        
        for prov, data in weather_data.items():
            astro = data.get("astronomy", {})
            parts = []
            
            if config_manager.getConfigVal("astro_sunrise") and astro.get("sunrise") is not None:
                t_str = weather_client.formatTimestamp(astro["sunrise"])
                parts.append(_("Sunrise: {time}").format(time=t_str))
                
            if config_manager.getConfigVal("astro_sunset") and astro.get("sunset") is not None:
                t_str = weather_client.formatTimestamp(astro["sunset"])
                parts.append(_("Sunset: {time}").format(time=t_str))
                
            if config_manager.getConfigVal("astro_moonrise") and astro.get("moonrise") is not None:
                t_str = weather_client.formatTimestamp(astro["moonrise"])
                parts.append(_("Moonrise: {time}").format(time=t_str))
                
            if config_manager.getConfigVal("astro_moonset") and astro.get("moonset") is not None:
                t_str = weather_client.formatTimestamp(astro["moonset"])
                parts.append(_("Moonset: {time}").format(time=t_str))
                
            if config_manager.getConfigVal("astro_moonphase") and astro.get("moon_phase") is not None:
                phase_name = weather_client.getMoonPhaseName(astro["moon_phase"])
                parts.append(_("Moon phase: {phase}").format(phase=phase_name))
                
            if parts:
                report_str = ", ".join(parts)
                if len(weather_data) > 1:
                    reports.append(f"{prov}: {report_str}")
                else:
                    reports.append(report_str)
            else:
                reports.append(_("No astronomy options enabled in settings."))

        header = _("Astronomy data for {location}").format(location=name)
        full_msg = header + ". " + ". ".join(reports)
        
        if copy_to_clipboard:
            api.setClipData(full_msg)
            ui.message(_("Astronomy data copied to clipboard."))
        else:
            ui.message(full_msg)

    # Gesture 5: Cycle Favorites
    def script_cycleFavoriteLocations(self, gesture):
        fav_json = config_manager.getConfigVal("favorites")
        try:
            favorites = json.loads(fav_json)
        except Exception:
            favorites = []
            
        if not favorites:
            ui.message(_("No favorite locations saved. Please open settings and add them."))
            return
            
        idx = config_manager.getConfigVal("current_favorite_index")
        idx = (idx + 1) % len(favorites)
        config_manager.setConfigVal("current_favorite_index", idx)
        
        import config
        config.conf.save()
        
        fav = favorites[idx]
        ui.message(_("Checking weather for favorite location: {name}").format(name=fav["name"]))
        self._runAsyncWeatherAction(
            self._reportCurrentWeather, 
            copy_to_clipboard=False, 
            lat=fav["lat"], 
            lon=fav["lon"], 
            location_name=fav["name"]
        )


class AlertCheckerThread(threading.Thread):
    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin
        self.stopEvent = threading.Event()
        self.daemon = True

    def run(self):
        self.stopEvent.wait(10.0)
        while not self.stopEvent.is_set():
            self.plugin.checkAlerts()
            
            interval = self.plugin.getPollInterval()
            elapsed = 0
            while elapsed < interval and not self.stopEvent.is_set():
                self.stopEvent.wait(1.0)
                elapsed += 1

    def stop(self):
        self.stopEvent.set()
