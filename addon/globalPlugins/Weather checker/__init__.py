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
    """
    Weather Checker NVDA Add-on.
    Only NVDA+Alt+W is assigned by default. All other commands can be
    assigned freely via NVDA Menu > Preferences > Input Gestures > Weather Checker.
    """

    # NVDA Input Gestures category name for all Weather Checker scripts
    scriptCategory = _("Weather Checker")

    # Only the primary gesture is hardcoded — all others are user-configurable
    __gestures = {
        "kb:NVDA+alt+w": "speakCurrentWeather",
    }

    # Class-level flag: ensures the startup update check fires exactly once per session
    _update_check_done = False

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
        if config_manager.getConfigVal("auto_update_check"):
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
        """
        auto_detect = config_manager.getConfigVal("autoDetectLocation")
        if auto_detect:
            # Check cached location
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
        else:
            lat = config_manager.getConfigVal("defaultLat")
            lon = config_manager.getConfigVal("defaultLon")
            name = config_manager.getConfigVal("defaultLocationName")
            if not lat or not lon:
                raise weather_client.WeatherClientError(
                    _("Location not configured. Please open NVDA Settings and configure your weather provider and location.")
                )
            return float(lat), float(lon), name

    # ----------------------------------------------------
    # Background Startup Update Checking
    # ----------------------------------------------------
    def startStartupUpdateCheck(self):
        """Starts the one-shot background update checker (fires at most once per session)."""
        if GlobalPlugin._update_check_done:
            return
        GlobalPlugin._update_check_done = True
        t = threading.Thread(
            target=self._runStartupUpdateCheck,
            name="WCStartupUpdateCheck",
            daemon=True
        )
        t.start()

    def _runStartupUpdateCheck(self):
        # Wait 5 s after NVDA starts so initial speech is not interrupted
        time.sleep(5.0)
        try:
            update_available, latest_version, download_url, body = weather_client.checkForUpdates()
            if update_available:
                # force=False: anti-spam rules apply for automatic startup checks
                wx.CallAfter(weather_client.promptUpdate, latest_version, download_url, body)
        except weather_client.NetworkError:
            # Network unavailable at startup — not worth alerting the user
            log.info("Weather Checker startup update check: network unavailable.")
        except Exception:
            log.warning("Weather Checker startup update check failed.", exc_info=True)

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
        
        ignored = config_manager.getConfigVal("alert_ignoredKeywords")
        if ignored:
            keywords = [k.strip().lower() for k in ignored.split(",") if k.strip()]
            if any(kw in text for kw in keywords):
                return False
        
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
            "wind_gust": avg(ow_curr.get("wind_gust"), pw_curr.get("wind_gust")),
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
                    "summary": o_item.get("summary") or p_item.get("summary") or "",
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
                
                ow_configured = bool(ow_key and ow_key.strip())
                pw_configured = bool(pw_key and pw_key.strip())
                
                if ow_configured and pw_configured:
                    if has_ow and has_pw:
                        weather_data = self.mergeWeatherData(weather_data)
                    elif has_pw and not has_ow:
                        warning = _("OpenWeather is currently unavailable. Using Pirate Weather.")
                    elif has_ow and not has_pw:
                        warning = _("Pirate Weather is currently unavailable. Using OpenWeather.")
                else:
                    # If only one provider is configured, no warning is issued and the single source data is presented.
                    pass
            
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

    # Script 1: Speak Current Weather (NVDA+Alt+W by default)
    def script_speakCurrentWeather(self, gesture):
        """Report current weather conditions for the configured location. Press twice quickly to copy to clipboard."""
        now = time.time()
        copy_pref = config_manager.getConfigVal("copy_to_clipboard")
        if copy_pref or (now - self._last_w_press < 0.5):
            self._runAsyncWeatherAction(self._reportCurrentWeather, copy_to_clipboard=True)
        else:
            ui.message(_("Checking weather..."))
            self._runAsyncWeatherAction(self._reportCurrentWeather, copy_to_clipboard=False)
        self._last_w_press = now

    def _reportCurrentWeather(self, name, weather_data, copy_to_clipboard):
        import datetime
        reports = []
        
        for prov, data in weather_data.items():
            curr = data.get("current", {})
            hourly_list = data.get("hourly", [])
            daily_list = data.get("daily", [])
            
            lines = []
            
            # Date and Time Period
            dt = datetime.datetime.now()
            day_str = dt.strftime("%A, %B ") + str(dt.day) + dt.strftime(", %Y")
            hour = dt.hour
            if 5 <= hour < 12:
                period = _("this morning")
            elif 12 <= hour < 17:
                period = _("this afternoon")
            elif 17 <= hour < 21:
                period = _("this evening")
            else:
                period = _("tonight")
                
            lines.append(_("Here is the current weather report for {location} {period}, {day_str}.").format(
                location=name, period=period, day_str=day_str
            ))
            lines.append(_("Current Weather Report: {location}").format(location=name))
            lines.append(_("Current Conditions"))
            
            # Temperature
            temp_c_raw = curr.get("temp")
            if temp_c_raw is not None:
                temp_c = int(round(temp_c_raw))
                temp_f = int(round((temp_c_raw * 9/5) + 32))
            else:
                temp_c, temp_f = 0, 32
            lines.append(_("Temperature: Around {temp_c}°C ({temp_f}°F)").format(temp_c=temp_c, temp_f=temp_f))
            
            # RealFeel
            feels_raw = curr.get("feels_like")
            if feels_raw is not None:
                feels_c = int(round(feels_raw))
                feels_f = int(round((feels_raw * 9/5) + 32))
            else:
                feels_c, feels_f = temp_c, temp_f
            lines.append(_("RealFeel: {feels_c}°C ({feels_f}°F)").format(feels_c=feels_c, feels_f=feels_f))
            
            # Condition
            condition = curr.get("condition") or _("Unknown")
            lines.append(_("Condition: {condition}").format(condition=condition))
            
            # Wind speed, direction, gust
            wind_speed = curr.get("wind_speed") # m/s
            wind_dir = curr.get("wind_dir")
            wind_gust = curr.get("wind_gust") # m/s
            
            if wind_speed is not None:
                speed_kmh = int(round(wind_speed * 3.6))
                speed_mph = int(round(wind_speed * 2.23694))
            else:
                speed_kmh, speed_mph = 0, 0
                
            if wind_dir is not None:
                wind_dir_name = weather_client.getWindDirectionName(wind_dir)
            else:
                wind_dir_name = _("Unknown")
                
            if wind_gust is not None and wind_gust > 0:
                gust_kmh = int(round(wind_gust * 3.6))
                gust_mph = int(round(wind_gust * 2.23694))
                lines.append(_("Wind: {dir} at {speed_kmh} km/h ({speed_mph} mph), with occasional gusts up to {gust_kmh} km/h ({gust_mph} mph)").format(
                    dir=wind_dir_name, speed_kmh=speed_kmh, speed_mph=speed_mph, gust_kmh=gust_kmh, gust_mph=gust_mph
                ))
            else:
                lines.append(_("Wind: {dir} at {speed_kmh} km/h ({speed_mph} mph)").format(
                    dir=wind_dir_name, speed_kmh=speed_kmh, speed_mph=speed_mph
                ))
                
            # Humidity
            humidity_val = curr.get("humidity")
            if humidity_val is not None:
                humidity = int(round(humidity_val))
                if humidity < 30:
                    humidity_desc = _("Low")
                elif humidity <= 60:
                    humidity_desc = _("Moderate")
                else:
                    humidity_desc = _("High")
            else:
                humidity = 0
                humidity_desc = _("Unknown")
            lines.append(_("Humidity: {desc}, around {humidity}%").format(desc=humidity_desc, humidity=humidity))
            
            # Visibility
            vis_km = curr.get("visibility")
            if vis_km is not None:
                vis_miles = int(round(vis_km * 0.621371))
                if vis_km >= 9.5:
                    vis_desc = _("Clear")
                elif vis_km >= 5:
                    vis_desc = _("Moderate")
                elif vis_km >= 2:
                    vis_desc = _("Poor")
                else:
                    vis_desc = _("Very Poor")
            else:
                vis_miles = 0
                vis_desc = _("Unknown")
            lines.append(_("Visibility: {desc} (around {vis_miles} miles)").format(desc=vis_desc, vis_miles=vis_miles))
            
            # Air Quality
            aqi = curr.get("aqi")
            if aqi:
                lines.append(_("Air Quality: {aqi}").format(aqi=aqi))
                
            # Today's Forecast (Tonight's/Today's Forecast)
            if hour >= 18 or hour < 5:
                forecast_header = _("Tonight's Forecast")
            else:
                forecast_header = _("Today's Forecast")
            lines.append(forecast_header)
            
            today_forecast = daily_list[0] if daily_list else {}
            today_summary = today_forecast.get("summary") or today_forecast.get("condition") or _("No forecast available.")
            lines.append(today_summary)
            
            # Tomorrow's Outlook
            tomorrow_dt = dt + datetime.timedelta(days=1)
            tomorrow_date_str = tomorrow_dt.strftime("%A, %B ") + str(tomorrow_dt.day)
            lines.append(_("Tomorrow's Outlook ({tomorrow_date_str})").format(tomorrow_date_str=tomorrow_date_str))
            
            tomorrow_forecast = daily_list[1] if len(daily_list) > 1 else {}
            tomorrow_max = tomorrow_forecast.get("temp_max")
            tomorrow_min = tomorrow_forecast.get("temp_min")
            
            if tomorrow_max is not None:
                tomorrow_max_c = int(round(tomorrow_max))
                tomorrow_max_f = int(round((tomorrow_max * 9/5) + 32))
            else:
                tomorrow_max_c, tomorrow_max_f = 0, 32
                
            if tomorrow_min is not None:
                tomorrow_min_c = int(round(tomorrow_min))
                tomorrow_min_f = int(round((tomorrow_min * 9/5) + 32))
            else:
                tomorrow_min_c, tomorrow_min_f = 0, 32
                
            tomorrow_cond_day = ""
            tomorrow_cond_night = ""
            tomorrow_summary = tomorrow_forecast.get("summary", "")
            tomorrow_cond = tomorrow_forecast.get("condition", "")
            
            if tomorrow_summary:
                sentences = [s.strip() for s in tomorrow_summary.split(".") if s.strip()]
                if len(sentences) >= 2:
                    tomorrow_cond_day = sentences[0]
                    tomorrow_cond_night = sentences[1]
                    
            if not tomorrow_cond_day or not tomorrow_cond_night:
                h_day = ""
                h_night = ""
                tomorrow_date = tomorrow_dt.date()
                for item in hourly_list:
                    item_time = item.get("time")
                    if item_time:
                        item_dt = datetime.datetime.fromtimestamp(item_time)
                        if item_dt.date() == tomorrow_date:
                            if 12 <= item_dt.hour <= 15 and not h_day:
                                h_day = item.get("condition", "")
                            if 20 <= item_dt.hour <= 23 and not h_night:
                                h_night = item.get("condition", "")
                if not tomorrow_cond_day:
                    tomorrow_cond_day = h_day or tomorrow_cond or _("Unknown")
                if not tomorrow_cond_night:
                    tomorrow_cond_night = h_night or tomorrow_cond or _("Unknown")
                    
            day_cond = tomorrow_cond_day.rstrip('.')
            night_cond = tomorrow_cond_night.rstrip('.')
            
            lines.append(_("Daytime High: {max_c}°C ({max_f}°F) – {day_cond}.").format(
                max_c=tomorrow_max_c, max_f=tomorrow_max_f, day_cond=day_cond
            ))
            lines.append(_("Nighttime Low: {min_c}°C ({min_f}°F) – {night_cond}.").format(
                min_c=tomorrow_min_c, min_f=tomorrow_min_f, night_cond=night_cond
            ))
            
            report_str = "\n".join(lines)
            if len(weather_data) > 1:
                reports.append(f"[{prov}]\n{report_str}")
            else:
                reports.append(report_str)
                
        full_msg = "\n\n".join(reports)
        
        if copy_to_clipboard:
            api.setClipData(full_msg)
            ui.message(_("Current weather copied to clipboard."))
        else:
            ui.message(full_msg)

    # Script 2: Speak Forecast (no default gesture — assign in Input Gestures)
    def script_speakForecast(self, gesture):
        """Report the weather forecast for the configured location. Press twice quickly to copy to clipboard."""
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
            3: _("3-day forecast"),
            4: _("5-day forecast"),
            5: _("7-day forecast"),
            6: _("10-day forecast")
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
                entries = daily_list[:min(max_entries, 3)]
            elif forecast_type == 4:
                entries = daily_list[:min(max_entries, 5)]
            elif forecast_type == 5:
                entries = daily_list[:min(max_entries, 7)]
            elif forecast_type == 6:
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

    # Script 3: Speak Active Weather Alerts (no default gesture — assign in Input Gestures)
    def script_speakActiveAlerts(self, gesture):
        """Report active weather alerts for the configured location. Press twice quickly to copy to clipboard."""
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

    # Script 4: Speak Astronomy (no default gesture — assign in Input Gestures)
    def script_speakAstronomy(self, gesture):
        """Report astronomy data (sunrise, sunset, moon phase) for the configured location. Press twice quickly to copy to clipboard."""
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

    # Script 5: Cycle Favorite Locations (no default gesture — assign in Input Gestures)
    def script_cycleFavoriteLocations(self, gesture):
        """Cycle through saved favorite locations and report weather for each."""
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

    # Script 6: Open Weather Checker Settings (no default gesture — assign in Input Gestures)
    def script_openSettings(self, gesture):
        """Open the NVDA Settings dialog, focused on Weather Checker settings."""
        import gui
        from gui.settingsDialogs import NVDASettingsDialog
        wx.CallAfter(
            gui.mainFrame._popupSettingsDialog,
            NVDASettingsDialog,
            WeatherCheckerSettingsPanel
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
