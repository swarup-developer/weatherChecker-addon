# -*- coding: utf-8 -*-
# Settings Panel for Weather Checker NVDA add-on

import wx
import gui
import ui
import speech
import threading
import time
import json
import datetime
from gui.settingsDialogs import SettingsPanel
from . import config_manager
from . import weather_client
import addonHandler

addonHandler.initTranslation()

class WeatherHistoryDialog(wx.Dialog):
    """Sub-dialog to review weather history logs and compare them with live conditions."""
    def __init__(self, parent):
        super().__init__(parent, title=_("Weather History"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.history = config_manager.loadHistory()
        self.parent = parent
        self._buildGui()
        
    def _buildGui(self):
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        
        listLabel = wx.StaticText(self, label=_("&Recent Weather Reports (select to view or compare):"))
        self.historyList = wx.ListBox(self, style=wx.LB_SINGLE, size=(450, 150))
        self.historyList.Bind(wx.EVT_LISTBOX, self.onItemSelected)
        
        # Populate history list
        for entry in self.history:
            dt = datetime.datetime.fromtimestamp(entry["timestamp"])
            date_str = dt.strftime("%Y-%m-%d %I:%M %p")
            self.historyList.Append(f"{entry['location']} - {date_str}")
            
        mainSizer.Add(listLabel, 0, wx.ALL | wx.EXPAND, 10)
        mainSizer.Add(self.historyList, 1, wx.ALL | wx.EXPAND, 10)
        
        # Action buttons
        btnSizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.viewForecastBtn = wx.Button(self, label=_("View &Forecast"))
        self.viewForecastBtn.Bind(wx.EVT_BUTTON, self.onViewForecast)
        btnSizer.Add(self.viewForecastBtn, 0, wx.ALL, 5)
        
        self.viewAlertsBtn = wx.Button(self, label=_("View &Alerts"))
        self.viewAlertsBtn.Bind(wx.EVT_BUTTON, self.onViewAlerts)
        btnSizer.Add(self.viewAlertsBtn, 0, wx.ALL, 5)
        
        self.compareBtn = wx.Button(self, label=_("&Compare with Current"))
        self.compareBtn.Bind(wx.EVT_BUTTON, self.onCompare)
        btnSizer.Add(self.compareBtn, 0, wx.ALL, 5)
        
        mainSizer.Add(btnSizer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)
        
        # OK / Close button
        closeSizer = self.CreateButtonSizer(wx.OK)
        mainSizer.Add(closeSizer, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        
        if self.history:
            self.historyList.SetSelection(0)
            self.onItemSelected(None)
        else:
            self.viewForecastBtn.Disable()
            self.viewAlertsBtn.Disable()
            self.compareBtn.Disable()
            
        self.SetSizerAndFit(mainSizer)
        self.CentreOnParent()

    def onItemSelected(self, event):
        selection = self.historyList.GetSelection()
        if selection == wx.NOT_FOUND:
            self.viewForecastBtn.Disable()
            self.viewAlertsBtn.Disable()
            self.compareBtn.Disable()
            return
            
        self.viewForecastBtn.Enable()
        self.viewAlertsBtn.Enable()
        self.compareBtn.Enable()

    def onViewForecast(self, event):
        selection = self.historyList.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        entry = self.history[selection]
        lines = []
        
        unit_temp = config_manager.getConfigVal("unit_temp")
        
        for prov, data in entry.get("providers", {}).items():
            lines.append(f"{prov}:")
            forecast = data.get("forecast", [])
            for f in forecast:
                day = weather_client.formatDay(f["time"])
                cond = f.get("condition", "")
                t_min = f.get("temp_min")
                t_max = f.get("temp_max")
                
                if unit_temp == 1:
                    t_min = weather_client.convertTemp(t_min, 1)
                    t_max = weather_client.convertTemp(t_max, 1)
                    min_str = f"{t_min:.1f}°F"
                    max_str = f"{t_max:.1f}°F"
                else:
                    min_str = f"{t_min:.1f}°C"
                    max_str = f"{t_max:.1f}°C"
                    
                lines.append(f"  {day}: {cond}, Min {min_str}, Max {max_str}")
                
        report = "\n".join(lines) if lines else _("No forecast saved in this entry.")
        gui.messageBox(report, _("Historical Forecast"), wx.OK | wx.ICON_INFORMATION, parent=self)

    def onViewAlerts(self, event):
        selection = self.historyList.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        entry = self.history[selection]
        lines = []
        
        for prov, data in entry.get("providers", {}).items():
            alerts = data.get("alerts", [])
            if alerts:
                lines.append(f"{prov}:")
                for a in alerts:
                    lines.append(f"  {a['title']}: {a['description']}")
                    
        report = "\n".join(lines) if lines else _("No alerts saved in this entry.")
        gui.messageBox(report, _("Historical Alerts"), wx.OK | wx.ICON_INFORMATION, parent=self)

    def onCompare(self, event):
        selection = self.historyList.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        entry = self.history[selection]
        lat = entry.get("lat")
        lon = entry.get("lon")
        
        if not lat or not lon:
            # Fallback to current default
            lat = config_manager.getConfigVal("defaultLat")
            lon = config_manager.getConfigVal("defaultLon")
            
        if not lat or not lon:
            gui.messageBox(_("Coordinates missing from history entry, cannot fetch current weather."), _("Error"), wx.OK | wx.ICON_ERROR, parent=self)
            return
            
        self.compareBtn.Disable()
        self.compareBtn.SetLabel(_("Comparing..."))
        
        provider = config_manager.getConfigVal("provider")
        ow_key = config_manager.getConfigVal("openWeatherApiKey")
        pw_key = config_manager.getConfigVal("pirateWeatherApiKey")
        
        def run_fetch():
            try:
                weather_data = weather_client.fetchWeatherData(float(lat), float(lon), provider, ow_key, pw_key)
                wx.CallAfter(self.showComparison, entry, weather_data)
            except Exception as e:
                wx.CallAfter(self.onComparisonFailed, str(e))
                
        t = threading.Thread(target=run_fetch)
        t.daemon = True
        t.start()

    def showComparison(self, entry, weather_data):
        self.compareBtn.Enable()
        self.compareBtn.SetLabel(_("&Compare with Current"))
        
        lines = []
        unit_temp = config_manager.getConfigVal("unit_temp")
        unit_wind = config_manager.getConfigVal("unit_wind")
        unit_pressure = config_manager.getConfigVal("unit_pressure")
        unit_visibility = config_manager.getConfigVal("unit_visibility")
        
        for prov, current_prov_data in weather_data.items():
            history_prov_data = entry.get("providers", {}).get(prov)
            if not history_prov_data:
                continue
                
            lines.append(f"{prov}:")
            
            # Temp
            hist_temp = history_prov_data.get("temp")
            curr_temp = current_prov_data.get("current", {}).get("temp")
            if hist_temp is not None and curr_temp is not None:
                diff = curr_temp - hist_temp
                symbol = "+" if diff >= 0 else ""
                
                if unit_temp == 1:
                    hist_disp = weather_client.convertTemp(hist_temp, 1)
                    curr_disp = weather_client.convertTemp(curr_temp, 1)
                    # For Fahrenheit, diff must be scaled by 1.8
                    diff_disp = diff * 1.8
                    deg = "°F"
                else:
                    hist_disp = hist_temp
                    curr_disp = curr_temp
                    diff_disp = diff
                    deg = "°C"
                    
                lines.append(_("  Temperature: Previous {hist:.1f}{deg}, Current {curr:.1f}{deg} (Difference: {symbol}{diff:.1f}{deg})").format(
                    hist=hist_disp, curr=curr_disp, symbol=symbol, diff=diff_disp, deg=deg
                ))
                
            # Humidity
            hist_hum = history_prov_data.get("humidity")
            curr_hum = current_prov_data.get("current", {}).get("humidity")
            if hist_hum is not None and curr_hum is not None:
                diff = curr_hum - hist_hum
                symbol = "+" if diff >= 0 else ""
                lines.append(_("  Humidity: Previous {hist}%, Current {curr}% (Difference: {symbol}{diff}%)").format(
                    hist=hist_hum, curr=curr_hum, symbol=symbol, diff=diff
                ))
                
            # Wind speed
            hist_wind = history_prov_data.get("wind_speed")
            curr_wind = current_prov_data.get("current", {}).get("wind_speed")
            if hist_wind is not None and curr_wind is not None:
                diff = curr_wind - hist_wind
                symbol = "+" if diff >= 0 else ""
                
                hist_disp = weather_client.convertWindSpeed(hist_wind, unit_wind)
                curr_disp = weather_client.convertWindSpeed(curr_wind, unit_wind)
                diff_disp = weather_client.convertWindSpeed(diff, unit_wind)
                
                unit_labels = {0: _("m/s"), 1: _("km/h"), 2: _("mph")}
                lbl = unit_labels.get(unit_wind, "")
                lines.append(_("  Wind Speed: Previous {hist:.1f} {lbl}, Current {curr:.1f} {lbl} (Difference: {symbol}{diff:.1f} {lbl})").format(
                    hist=hist_disp, curr=curr_disp, symbol=symbol, diff=diff_disp, lbl=lbl
                ))
                
            # Conditions
            hist_cond = history_prov_data.get("condition")
            curr_cond = current_prov_data.get("current", {}).get("condition")
            if hist_cond and curr_cond:
                lines.append(_("  Conditions: Previous '{hist}', Current '{curr}'").format(
                    hist=hist_cond, curr=curr_cond
                ))
                
        report = "\n".join(lines) if lines else _("No comparison data available.")
        gui.messageBox(report, _("Weather Conditions Comparison"), wx.OK | wx.ICON_INFORMATION, parent=self)

    def onComparisonFailed(self, error_msg):
        self.compareBtn.Enable()
        self.compareBtn.SetLabel(_("&Compare with Current"))
        gui.messageBox(error_msg, _("Comparison Failed"), wx.OK | wx.ICON_ERROR, parent=self)



class LocationSearchDialog(wx.Dialog):
    """Dialog to search for a location and select it."""
    def __init__(self, parent, provider, ow_key):
        super().__init__(parent, title=_("Search for Location"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.provider = provider
        self.ow_key = ow_key
        self.selectedLocation = None
        self.latestSearchResults = []
        self._buildGui()
        
    def _buildGui(self):
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        
        searchLabel = wx.StaticText(self, label=_("&Search query (type to search):"))
        self.searchCtrl = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.searchCtrl.Bind(wx.EVT_TEXT, self.onSearchTextChanged)
        self.searchCtrl.Bind(wx.EVT_TEXT_ENTER, self.onSearchEnter)
        
        searchBtnSizer = wx.BoxSizer(wx.HORIZONTAL)
        searchBtnSizer.Add(self.searchCtrl, 1, wx.EXPAND | wx.RIGHT, 5)
        self.searchBtn = wx.Button(self, label=_("&Search"))
        self.searchBtn.Bind(wx.EVT_BUTTON, self.onSearchBtnClick)
        searchBtnSizer.Add(self.searchBtn, 0, wx.ALIGN_CENTER_VERTICAL)
        
        mainSizer.Add(searchLabel, 0, wx.ALL | wx.EXPAND, 10)
        mainSizer.Add(searchBtnSizer, 0, wx.ALL | wx.EXPAND, 10)
        
        resultsLabel = wx.StaticText(self, label=_("Search &Results:"))
        self.resultsList = wx.ListBox(self, style=wx.LB_SINGLE, size=(450, 150))
        self.resultsList.Bind(wx.EVT_LISTBOX, self.onResultSelected)
        self.resultsList.Bind(wx.EVT_LISTBOX_DCLICK, self.onResultDoubleClicked)
        
        mainSizer.Add(resultsLabel, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 10)
        mainSizer.Add(self.resultsList, 1, wx.ALL | wx.EXPAND, 10)
        
        btnSizer = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        mainSizer.Add(btnSizer, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        
        self.okBtn = self.FindWindowById(wx.ID_OK)
        if self.okBtn:
            self.okBtn.Disable()
            
        self.Bind(wx.EVT_BUTTON, self.onOK, id=wx.ID_OK)
        
        self.searchTimer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.onSearchTimerTrigger, self.searchTimer)
        
        self.SetSizerAndFit(mainSizer)
        self.CentreOnParent()

    def onSearchTextChanged(self, event):
        self.searchTimer.Start(500, oneShot=True)

    def onSearchTimerTrigger(self, event):
        self.triggerSearch()

    def onSearchEnter(self, event):
        self.triggerSearch()

    def onSearchBtnClick(self, event):
        self.triggerSearch()

    def triggerSearch(self):
        query = self.searchCtrl.GetValue().strip()
        if len(query) < 2:
            return
            
        self.searchBtn.Disable()
        self.searchBtn.SetLabel(_("Searching..."))
        
        thread = threading.Thread(target=self._runGeocoding, args=(query, self.provider, self.ow_key))
        thread.daemon = True
        thread.start()

    def _runGeocoding(self, query, provider, ow_key):
        try:
            results = weather_client.geocodeLocation(query, provider, ow_key)
            wx.CallAfter(self._onGeocodingSuccess, results)
        except Exception as e:
            wx.CallAfter(self._onGeocodingFailed, str(e))

    def _onGeocodingSuccess(self, results):
        self.searchBtn.Enable()
        self.searchBtn.SetLabel(_("&Search"))
        self.resultsList.Clear()
        self.latestSearchResults = results
        
        for item in results:
            region_str = f", {item['region']}" if item['region'] else ""
            display_str = f"{item['name']}{region_str} ({item['country']})"
            self.resultsList.Append(display_str)
            
        if results:
            self.resultsList.SetSelection(0)
            if self.okBtn:
                self.okBtn.Enable()
            speech.speakMessage(_("Search complete. found {count} results.").format(count=len(results)))
        else:
            if self.okBtn:
                self.okBtn.Disable()
            speech.speakMessage(_("No results found."))

    def _onGeocodingFailed(self, error_msg):
        self.searchBtn.Enable()
        self.searchBtn.SetLabel(_("&Search"))
        self.resultsList.Clear()
        self.latestSearchResults = []
        if self.okBtn:
            self.okBtn.Disable()
        speech.speakMessage(error_msg)

    def onResultSelected(self, event):
        if self.okBtn:
            self.okBtn.Enable()

    def onResultDoubleClicked(self, event):
        self.onOK(None)

    def onOK(self, event):
        selection = self.resultsList.GetSelection()
        if selection != wx.NOT_FOUND and selection < len(self.latestSearchResults):
            self.selectedLocation = self.latestSearchResults[selection]
            self.EndModal(wx.ID_OK)
        else:
            self.EndModal(wx.ID_CANCEL)


class WeatherCheckerSettingsPanel(SettingsPanel):
    # Category Title shown in the NVDA Settings list
    title = _("Weather Checker")
    panelDescription = _("Configure settings for the Weather Checker add-on.")

    def makeSettings(self, sizer):
        self.mainSettingsSizer = sizer
        config_manager.registerConfig()

        # ----------------------------------------------------
        # 1. Weather Provider Settings Section
        # ----------------------------------------------------
        providerBox = wx.StaticBox(self, label=_("Weather Provider Settings"))
        providerSizer = wx.StaticBoxSizer(providerBox, wx.VERTICAL)

        providerLabel = wx.StaticText(self, label=_("Weather &Provider:"))
        providerChoices = [
            _("OpenWeather"),
            _("Pirate Weather"),
            _("All Providers")
        ]
        self.providerChoice = wx.Choice(self, choices=providerChoices)
        self.providerChoice.SetSelection(config_manager.getConfigVal("provider"))
        self.providerChoice.Bind(wx.EVT_CHOICE, self.onProviderChanged)
        
        providerSizer.Add(providerLabel, 0, wx.ALL | wx.EXPAND, 5)
        providerSizer.Add(self.providerChoice, 0, wx.ALL | wx.EXPAND, 5)

        self.openWeatherKeyLabel = wx.StaticText(self, label=_("Open&Weather API Key:"))
        self.openWeatherKeyCtrl = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.openWeatherKeyCtrl.SetValue(config_manager.getConfigVal("openWeatherApiKey"))
        
        self.openWeatherKeySizer = wx.BoxSizer(wx.VERTICAL)
        self.openWeatherKeySizer.Add(self.openWeatherKeyLabel, 0, wx.ALL | wx.EXPAND, 5)
        self.openWeatherKeySizer.Add(self.openWeatherKeyCtrl, 0, wx.ALL | wx.EXPAND, 5)
        providerSizer.Add(self.openWeatherKeySizer, 0, wx.EXPAND)

        self.pirateWeatherKeyLabel = wx.StaticText(self, label=_("P&irate Weather API Key:"))
        self.pirateWeatherKeyCtrl = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.pirateWeatherKeyCtrl.SetValue(config_manager.getConfigVal("pirateWeatherApiKey"))
        
        self.pirateWeatherKeySizer = wx.BoxSizer(wx.VERTICAL)
        self.pirateWeatherKeySizer.Add(self.pirateWeatherKeyLabel, 0, wx.ALL | wx.EXPAND, 5)
        self.pirateWeatherKeySizer.Add(self.pirateWeatherKeyCtrl, 0, wx.ALL | wx.EXPAND, 5)
        providerSizer.Add(self.pirateWeatherKeySizer, 0, wx.EXPAND)

        self.verifyBtn = wx.Button(self, label=_("&Verify Provider Settings"))
        self.verifyBtn.Bind(wx.EVT_BUTTON, self.onVerifySettings)
        providerSizer.Add(self.verifyBtn, 0, wx.ALL | wx.ALIGN_LEFT, 5)

        self.mainSettingsSizer.Add(providerSizer, 0, wx.ALL | wx.EXPAND, 10)

        # ----------------------------------------------------
        # 2. Location & Favorites Settings Section
        # ----------------------------------------------------
        locationBox = wx.StaticBox(self, label=_("Location Settings"))
        locationSizer = wx.StaticBoxSizer(locationBox, wx.VERTICAL)

        self.autoDetectCb = wx.CheckBox(self, label=_("&Automatically detect my location"))
        self.autoDetectCb.SetValue(config_manager.getConfigVal("autoDetectLocation"))
        self.autoDetectCb.Bind(wx.EVT_CHECKBOX, self.onAutoDetectChanged)
        locationSizer.Add(self.autoDetectCb, 0, wx.ALL, 5)

        self.currentLocationLabel = wx.StaticText(self, label="")
        self.updateLocationDisplay()
        locationSizer.Add(self.currentLocationLabel, 0, wx.ALL | wx.EXPAND, 5)

        # Location buttons
        locationBtnSizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.searchLocationBtn = wx.Button(self, label=_("&Search for Location..."))
        self.searchLocationBtn.Bind(wx.EVT_BUTTON, self.onSearchLocationClick)
        locationBtnSizer.Add(self.searchLocationBtn, 0, wx.RIGHT, 5)
        
        self.useCurrentLocationBtn = wx.Button(self, label=_("Use Current &Location"))
        self.useCurrentLocationBtn.Bind(wx.EVT_BUTTON, self.onUseCurrentLocationClick)
        locationBtnSizer.Add(self.useCurrentLocationBtn, 0)

        # Favorites list Box
        self.favoritesLabel = wx.StaticText(self, label=_("&Favorite Locations:"))
        self.favoritesList = wx.ListBox(self, style=wx.LB_SINGLE, size=(-1, 100))
        self.favoritesList.Bind(wx.EVT_LISTBOX, self.onFavoriteSelected)
        
        favoritesBtnSizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.addFavoriteBtn = wx.Button(self, label=_("&Add Favorite Location..."))
        self.addFavoriteBtn.Bind(wx.EVT_BUTTON, self.onAddFavoriteLocationClick)
        favoritesBtnSizer.Add(self.addFavoriteBtn, 0, wx.RIGHT, 5)
        
        self.removeFavoriteBtn = wx.Button(self, label=_("&Remove Favorite"))
        self.removeFavoriteBtn.Bind(wx.EVT_BUTTON, self.onRemoveFavorite)
        self.removeFavoriteBtn.Disable()
        favoritesBtnSizer.Add(self.removeFavoriteBtn, 0)

        self.searchSizer = wx.BoxSizer(wx.VERTICAL)
        self.searchSizer.Add(locationBtnSizer, 0, wx.ALL | wx.EXPAND, 5)
        self.searchSizer.Add(self.favoritesLabel, 0, wx.ALL | wx.EXPAND, 5)
        self.searchSizer.Add(self.favoritesList, 0, wx.ALL | wx.EXPAND, 5)
        self.searchSizer.Add(favoritesBtnSizer, 0, wx.ALL | wx.EXPAND, 5)
        
        locationSizer.Add(self.searchSizer, 0, wx.EXPAND)
        self.mainSettingsSizer.Add(locationSizer, 0, wx.ALL | wx.EXPAND, 10)

        # Load Favorites list
        fav_json = config_manager.getConfigVal("favorites")
        try:
            self.favoriteLocations = json.loads(fav_json)
        except Exception:
            self.favoriteLocations = []
        self.updateFavoritesDisplay()

        # ----------------------------------------------------
        # 3. Granular Unit Settings Section
        # ----------------------------------------------------
        unitsBox = wx.StaticBox(self, label=_("Unit Settings"))
        unitsSizer = wx.StaticBoxSizer(unitsBox, wx.VERTICAL)
        
        # Temp units choice
        tempLabel = wx.StaticText(self, label=_("&Temperature Unit:"))
        self.tempChoice = wx.Choice(self, choices=[_("Celsius (°C)"), _("Fahrenheit (°F)")])
        self.tempChoice.SetSelection(config_manager.getConfigVal("unit_temp"))
        unitsSizer.Add(tempLabel, 0, wx.ALL | wx.EXPAND, 3)
        unitsSizer.Add(self.tempChoice, 0, wx.ALL | wx.EXPAND, 3)
        
        # Wind speed units choice
        windLabel = wx.StaticText(self, label=_("&Wind Speed Unit:"))
        self.windChoice = wx.Choice(self, choices=[_("Meters per second (m/s)"), _("Kilometers per hour (km/h)"), _("Miles per hour (mph)")])
        self.windChoice.SetSelection(config_manager.getConfigVal("unit_wind"))
        unitsSizer.Add(windLabel, 0, wx.ALL | wx.EXPAND, 3)
        unitsSizer.Add(self.windChoice, 0, wx.ALL | wx.EXPAND, 3)

        # Pressure units choice
        pressLabel = wx.StaticText(self, label=_("&Atmospheric Pressure Unit:"))
        self.pressChoice = wx.Choice(self, choices=[_("Hectopascals (hPa)"), _("Inches of Mercury (inHg)")])
        self.pressChoice.SetSelection(config_manager.getConfigVal("unit_pressure"))
        unitsSizer.Add(pressLabel, 0, wx.ALL | wx.EXPAND, 3)
        unitsSizer.Add(self.pressChoice, 0, wx.ALL | wx.EXPAND, 3)

        # Visibility units choice
        visLabel = wx.StaticText(self, label=_("&Visibility Unit:"))
        self.visChoice = wx.Choice(self, choices=[_("Kilometers"), _("Miles")])
        self.visChoice.SetSelection(config_manager.getConfigVal("unit_visibility"))
        unitsSizer.Add(visLabel, 0, wx.ALL | wx.EXPAND, 3)
        unitsSizer.Add(self.visChoice, 0, wx.ALL | wx.EXPAND, 3)
        
        self.mainSettingsSizer.Add(unitsSizer, 0, wx.ALL | wx.EXPAND, 10)

        # ----------------------------------------------------
        # 4. History review button
        # ----------------------------------------------------
        historyBox = wx.StaticBox(self, label=_("Weather History"))
        historySizer = wx.StaticBoxSizer(historyBox, wx.VERTICAL)
        
        self.viewHistoryBtn = wx.Button(self, label=_("&View Weather History"))
        self.viewHistoryBtn.Bind(wx.EVT_BUTTON, self.onViewHistory)
        historySizer.Add(self.viewHistoryBtn, 0, wx.ALL, 5)
        
        self.mainSettingsSizer.Add(historySizer, 0, wx.ALL | wx.EXPAND, 10)

        # ----------------------------------------------------
        # 5. Add-on Updates Settings Section
        # ----------------------------------------------------
        updatesBox = wx.StaticBox(self, label=_("Add-on Updates"))
        updatesSizer = wx.StaticBoxSizer(updatesBox, wx.VERTICAL)
        
        self.autoUpdateCb = wx.CheckBox(self, label=_("&Check for updates automatically"))
        self.autoUpdateCb.SetValue(config_manager.getConfigVal("auto_update_check"))
        updatesSizer.Add(self.autoUpdateCb, 0, wx.ALL, 5)
        
        self.checkUpdateBtn = wx.Button(self, label=_("Check for &Updates Now"))
        self.checkUpdateBtn.Bind(wx.EVT_BUTTON, self.onCheckForUpdates)
        updatesSizer.Add(self.checkUpdateBtn, 0, wx.ALL, 5)
        
        self.mainSettingsSizer.Add(updatesSizer, 0, wx.ALL | wx.EXPAND, 10)

        # ----------------------------------------------------
        # 6. Weather Information (Announcement checkboxes)
        # ----------------------------------------------------
        infoBox = wx.StaticBox(self, label=_("Weather Information to Announce"))
        infoSizer = wx.StaticBoxSizer(infoBox, wx.VERTICAL)
        
        self.infoCbs = {}
        info_keys = [
            ("info_currentWeather", _("Current weather conditions")),
            ("info_temperature", _("Temperature")),
            ("info_feelsLike", _("Feels-like temperature")),
            ("info_humidity", _("Humidity")),
            ("info_windSpeed", _("Wind speed")),
            ("info_windDirection", _("Wind direction")),
            ("info_pressure", _("Atmospheric pressure")),
            ("info_visibility", _("Visibility")),
            ("info_uvIndex", _("UV index")),
            ("info_clouds", _("Cloud coverage")),
            ("info_dewPoint", _("Dew point")),
            ("info_airQuality", _("Air quality when available"))
        ]
        for key, label in info_keys:
            cb = wx.CheckBox(self, label=label)
            cb.SetValue(config_manager.getConfigVal(key))
            infoSizer.Add(cb, 0, wx.ALL, 3)
            self.infoCbs[key] = cb
            
        self.mainSettingsSizer.Add(infoSizer, 0, wx.ALL | wx.EXPAND, 10)

        # ----------------------------------------------------
        # 7. Forecast Settings Section
        # ----------------------------------------------------
        forecastBox = wx.StaticBox(self, label=_("Forecast Settings"))
        forecastSizer = wx.StaticBoxSizer(forecastBox, wx.VERTICAL)

        forecastTypeLabel = wx.StaticText(self, label=_("&Forecast Type:"))
        forecastChoices = [
            _("Hourly forecast"),
            _("12-hour forecast"),
            _("24-hour forecast"),
            _("Daily forecast"),
            _("7-day forecast"),
            _("10-day forecast")
        ]
        self.forecastTypeChoice = wx.Choice(self, choices=forecastChoices)
        self.forecastTypeChoice.SetSelection(config_manager.getConfigVal("forecast_type"))
        forecastSizer.Add(forecastTypeLabel, 0, wx.ALL | wx.EXPAND, 5)
        forecastSizer.Add(self.forecastTypeChoice, 0, wx.ALL | wx.EXPAND, 5)

        forecastEntriesLabel = wx.StaticText(self, label=_("&Maximum entries to announce:"))
        self.forecastEntriesCtrl = wx.SpinCtrl(self, min=1, max=24, initial=config_manager.getConfigVal("forecast_entries"))
        forecastSizer.Add(forecastEntriesLabel, 0, wx.ALL | wx.EXPAND, 5)
        forecastSizer.Add(self.forecastEntriesCtrl, 0, wx.ALL | wx.EXPAND, 5)

        self.mainSettingsSizer.Add(forecastSizer, 0, wx.ALL | wx.EXPAND, 10)

        # ----------------------------------------------------
        # 8. Astronomy Settings Section
        # ----------------------------------------------------
        astroBox = wx.StaticBox(self, label=_("Astronomy Settings"))
        astroSizer = wx.StaticBoxSizer(astroBox, wx.VERTICAL)

        self.astroCbs = {}
        astro_keys = [
            ("astro_sunrise", _("Sunrise time")),
            ("astro_sunset", _("Sunset time")),
            ("astro_moonrise", _("Moonrise time")),
            ("astro_moonset", _("Moonset time")),
            ("astro_moonphase", _("Moon phase"))
        ]
        for key, label in astro_keys:
            cb = wx.CheckBox(self, label=label)
            cb.SetValue(config_manager.getConfigVal(key))
            astroSizer.Add(cb, 0, wx.ALL, 3)
            self.astroCbs[key] = cb

        self.mainSettingsSizer.Add(astroSizer, 0, wx.ALL | wx.EXPAND, 10)

        # ----------------------------------------------------
        # 9. Weather Alerts Settings Section
        # ----------------------------------------------------
        alertsBox = wx.StaticBox(self, label=_("Weather Alerts Settings"))
        alertsSizer = wx.StaticBoxSizer(alertsBox, wx.VERTICAL)

        typesLabel = wx.StaticText(self, label=_("Alert Categories to Enable:"))
        alertsSizer.Add(typesLabel, 0, wx.ALL | wx.EXPAND, 5)

        self.alertCbs = {}
        alert_keys = [
            ("alert_severe", _("Severe weather alerts")),
            ("alert_thunderstorm", _("Thunderstorm alerts")),
            ("alert_heavyRain", _("Heavy rain alerts")),
            ("alert_flood", _("Flood alerts")),
            ("alert_snow", _("Snow alerts")),
            ("alert_heat", _("Heat warnings")),
            ("alert_cold", _("Cold weather warnings")),
            ("alert_wind", _("High wind alerts")),
            ("alert_hurricane", _("Hurricane or cyclone alerts")),
            ("alert_tornado", _("Tornado alerts")),
            ("alert_fog", _("Fog alerts")),
            ("alert_airQuality", _("Air quality alerts"))
        ]
        for key, label in alert_keys:
            cb = wx.CheckBox(self, label=label)
            cb.SetValue(config_manager.getConfigVal(key))
            alertsSizer.Add(cb, 0, wx.ALL, 3)
            self.alertCbs[key] = cb

        alertsSizer.AddSpacer(5)

        behaviorLabel = wx.StaticText(self, label=_("Alert Notification Methods:"))
        alertsSizer.Add(behaviorLabel, 0, wx.ALL | wx.EXPAND, 5)

        self.alertSpeakAutoCb = wx.CheckBox(self, label=_("Speak alerts &automatically"))
        self.alertSpeakAutoCb.SetValue(config_manager.getConfigVal("alert_speakAuto"))
        alertsSizer.Add(self.alertSpeakAutoCb, 0, wx.ALL, 3)

        self.alertShowDialogCb = wx.CheckBox(self, label=_("Show alerts in accessible &dialogs"))
        self.alertShowDialogCb.SetValue(config_manager.getConfigVal("alert_showDialog"))
        alertsSizer.Add(self.alertShowDialogCb, 0, wx.ALL, 3)

        self.alertShowNotifCb = wx.CheckBox(self, label=_("Display NVDA &notifications"))
        self.alertShowNotifCb.SetValue(config_manager.getConfigVal("alert_showNotification"))
        alertsSizer.Add(self.alertShowNotifCb, 0, wx.ALL, 3)

        repeatLabel = wx.StaticText(self, label=_("&Repeat alerts interval:"))
        repeatChoices = [
            _("Disabled"),
            _("Every 5 minutes"),
            _("Every 10 minutes"),
            _("Every 15 minutes"),
            _("Every 30 minutes"),
            _("Every 60 minutes")
        ]
        self.alertRepeatChoice = wx.Choice(self, choices=repeatChoices)
        self.alertRepeatChoice.SetSelection(config_manager.getConfigVal("alert_repeatInterval"))
        alertsSizer.Add(repeatLabel, 0, wx.ALL | wx.EXPAND, 5)
        alertsSizer.Add(self.alertRepeatChoice, 0, wx.ALL | wx.EXPAND, 5)

        severityLabel = wx.StaticText(self, label=_("Filter alerts by &severity:"))
        severityChoices = [
            _("All alerts"),
            _("Moderate and above"),
            _("Severe and above"),
            _("Extreme only")
        ]
        self.alertSeverityChoice = wx.Choice(self, choices=severityChoices)
        self.alertSeverityChoice.SetSelection(config_manager.getConfigVal("alert_severityFilter"))
        alertsSizer.Add(severityLabel, 0, wx.ALL | wx.EXPAND, 5)
        alertsSizer.Add(self.alertSeverityChoice, 0, wx.ALL | wx.EXPAND, 5)

        self.mainSettingsSizer.Add(alertsSizer, 0, wx.ALL | wx.EXPAND, 10)

        self.updateProviderFieldsVisibility()
        self.updateLocationFieldsVisibility()

    # Dynamic Field Visibilities
    def updateProviderFieldsVisibility(self):
        selection = self.providerChoice.GetSelection()
        show_ow = (selection in (0, 2))
        show_pw = (selection in (1, 2))
        
        self.openWeatherKeySizer.Show(self.openWeatherKeyLabel, show_ow)
        self.openWeatherKeySizer.Show(self.openWeatherKeyCtrl, show_ow)
        self.pirateWeatherKeySizer.Show(self.pirateWeatherKeyLabel, show_pw)
        self.pirateWeatherKeySizer.Show(self.pirateWeatherKeyCtrl, show_pw)
        
        self.Layout()
        self._sendLayoutUpdatedEvent()

    def updateLocationFieldsVisibility(self):
        auto_detect = self.autoDetectCb.GetValue()
        enable_search = not auto_detect
        
        self.searchLocationBtn.Show(enable_search)
        self.useCurrentLocationBtn.Show(enable_search)
        self.favoritesLabel.Show(enable_search)
        self.favoritesList.Show(enable_search)
        self.addFavoriteBtn.Show(enable_search)
        self.removeFavoriteBtn.Show(enable_search)
        
        self.Layout()
        self._sendLayoutUpdatedEvent()

    def updateLocationDisplay(self):
        lat = config_manager.getConfigVal("defaultLat")
        lon = config_manager.getConfigVal("defaultLon")
        name = config_manager.getConfigVal("defaultLocationName")
        
        if not lat or not lon:
            self.currentLocationLabel.SetLabel(_("Default Location: Not Configured"))
        else:
            self.currentLocationLabel.SetLabel(_("Default Location: {name} (Lat: {lat}, Lon: {lon})").format(
                name=name, lat=lat, lon=lon
            ))

    def updateFavoritesDisplay(self):
        self.favoritesList.Clear()
        for item in self.favoriteLocations:
            self.favoritesList.Append(item["name"])
        self.removeFavoriteBtn.Disable()

    # Event Handlers
    def onProviderChanged(self, event):
        self.updateProviderFieldsVisibility()

    def onAutoDetectChanged(self, event):
        self.updateLocationFieldsVisibility()

    def onVerifySettings(self, event):
        provider = self.providerChoice.GetSelection()
        ow_key = self.openWeatherKeyCtrl.GetValue().strip()
        pw_key = self.pirateWeatherKeyCtrl.GetValue().strip()
        
        self.verifyBtn.Disable()
        self.verifyBtn.SetLabel(_("Verifying..."))
        
        thread = threading.Thread(target=self._runVerification, args=(provider, ow_key, pw_key))
        thread.daemon = True
        thread.start()

    def _runVerification(self, provider, ow_key, pw_key):
        success, msg = weather_client.verifyKeys(provider, ow_key, pw_key)
        wx.CallAfter(self._onVerificationComplete, success, msg)

    def _onVerificationComplete(self, success, msg):
        self.verifyBtn.Enable()
        self.verifyBtn.SetLabel(_("&Verify Provider Settings"))
        ui.message(msg)
        
        style = wx.OK | (wx.ICON_INFORMATION if success else wx.ICON_ERROR)
        gui.messageBox(
            message=msg,
            caption=_("API Settings Verification"),
            style=style,
            parent=self
        )

    # Location Search Handlers
    def onSearchLocationClick(self, event):
        provider = self.providerChoice.GetSelection()
        ow_key = self.openWeatherKeyCtrl.GetValue().strip()
        
        dlg = LocationSearchDialog(self, provider, ow_key)
        if dlg.ShowModal() == wx.ID_OK:
            loc = dlg.selectedLocation
            if loc:
                region_str = f", {loc['region']}" if loc['region'] else ""
                full_name = f"{loc['name']}{region_str} ({loc['country']})"
                
                config_manager.setConfigVal("defaultLat", str(loc["lat"]))
                config_manager.setConfigVal("defaultLon", str(loc["lon"]))
                config_manager.setConfigVal("defaultLocationName", full_name)
                
                self.updateLocationDisplay()
                msg = _("Location saved: {name}").format(name=full_name)
                ui.message(msg)
        dlg.Destroy()

    def onAddFavoriteLocationClick(self, event):
        provider = self.providerChoice.GetSelection()
        ow_key = self.openWeatherKeyCtrl.GetValue().strip()
        
        dlg = LocationSearchDialog(self, provider, ow_key)
        if dlg.ShowModal() == wx.ID_OK:
            loc = dlg.selectedLocation
            if loc:
                region_str = f", {loc['region']}" if loc['region'] else ""
                full_name = f"{loc['name']}{region_str} ({loc['country']})"
                
                # Check if already exists in favorites
                for fav in self.favoriteLocations:
                    if abs(fav["lat"] - loc["lat"]) < 0.001 and abs(fav["lon"] - loc["lon"]) < 0.001:
                        ui.message(_("Location is already in favorites: ") + full_name)
                        dlg.Destroy()
                        return
                        
                fav_item = {
                    "name": full_name,
                    "lat": loc["lat"],
                    "lon": loc["lon"]
                }
                self.favoriteLocations.append(fav_item)
                self.updateFavoritesDisplay()
                ui.message(_("Added to favorites: {name}").format(name=full_name))
        dlg.Destroy()

    def onUseCurrentLocationClick(self, event):
        self.useCurrentLocationBtn.Disable()
        self.useCurrentLocationBtn.SetLabel(_("Detecting..."))
        
        def run_detect():
            try:
                loc = weather_client.detectLocationIP()
                wx.CallAfter(self.onDetectSuccess, loc)
            except Exception as e:
                wx.CallAfter(self.onDetectFailed, str(e))
                
        t = threading.Thread(target=run_detect)
        t.daemon = True
        t.start()

    def onDetectSuccess(self, loc):
        self.useCurrentLocationBtn.Enable()
        self.useCurrentLocationBtn.SetLabel(_("Use Current &Location"))
        
        full_name = f"{loc['name']} ({loc['country']})" if loc.get("country") else loc['name']
        
        config_manager.setConfigVal("defaultLat", str(loc["lat"]))
        config_manager.setConfigVal("defaultLon", str(loc["lon"]))
        config_manager.setConfigVal("defaultLocationName", full_name)
        
        self.updateLocationDisplay()
        msg = _("Location set to {name}").format(name=full_name)
        ui.message(msg)
        speech.speakMessage(msg)

    def onDetectFailed(self, error_msg):
        self.useCurrentLocationBtn.Enable()
        self.useCurrentLocationBtn.SetLabel(_("Use Current &Location"))
        ui.message(error_msg)
        gui.messageBox(error_msg, _("Location Detection Failed"), wx.OK | wx.ICON_ERROR, parent=self)

    def onFavoriteSelected(self, event):
        self.removeFavoriteBtn.Enable()

    def onRemoveFavorite(self, event):
        selection = self.favoritesList.GetSelection()
        if selection == wx.NOT_FOUND or selection >= len(self.favoriteLocations):
            return
            
        item = self.favoriteLocations[selection]
        del self.favoriteLocations[selection]
        self.updateFavoritesDisplay()
        ui.message(_("Removed from favorites: {name}").format(name=item["name"]))

    # Update Checker Handler
    def onCheckForUpdates(self, event):
        self.checkUpdateBtn.Disable()
        self.checkUpdateBtn.SetLabel(_("Checking..."))
        
        def run_check():
            try:
                update_available, latest_version, download_url, body = weather_client.checkForUpdates()
                wx.CallAfter(self.onUpdateCheckComplete, update_available, latest_version, download_url, body)
            except Exception as e:
                wx.CallAfter(self.onUpdateCheckFailed, str(e))
                
        t = threading.Thread(target=run_check)
        t.daemon = True
        t.start()

    def onUpdateCheckComplete(self, update_available, latest_version, download_url, body):
        self.checkUpdateBtn.Enable()
        self.checkUpdateBtn.SetLabel(_("Check for Updates Now"))
        
        if update_available:
            weather_client.promptUpdate(latest_version, download_url, body, parent=self)
        else:
            try:
                addon = addonHandler.getCodeAddon()
                current_version = addon.manifest.version
            except Exception:
                current_version = "1.0.4"
            msg = _("Weather Checker is up to date. Current version: {version}.").format(version=current_version)
            ui.message(msg)
            gui.messageBox(msg, _("Weather Checker Update"), wx.OK | wx.ICON_INFORMATION, parent=self)

    def onUpdateCheckFailed(self, error_msg):
        self.checkUpdateBtn.Enable()
        self.checkUpdateBtn.SetLabel(_("Check for Updates Now"))
        ui.message(error_msg)
        gui.messageBox(error_msg, _("Update Check Failed"), wx.OK | wx.ICON_ERROR, parent=self)

    # History Review Handler
    def onViewHistory(self, event):
        dlg = WeatherHistoryDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    # Save and Validation
    def isValid(self):
        provider = self.providerChoice.GetSelection()
        ow_key = self.openWeatherKeyCtrl.GetValue().strip()
        pw_key = self.pirateWeatherKeyCtrl.GetValue().strip()
        auto_detect = self.autoDetectCb.GetValue()
        
        if provider == 0 or provider == 2:
            if not ow_key:
                self._validationErrorMessageBox(
                    message=_("OpenWeather is selected, but OpenWeather API key is empty. Please enter a valid API key."),
                    option=_("OpenWeather API Key")
                )
                return False
                
        if provider == 1 or provider == 2:
            if not pw_key:
                self._validationErrorMessageBox(
                    message=_("Pirate Weather is selected, but Pirate Weather API key is empty. Please enter a valid API key."),
                    option=_("Pirate Weather API Key")
                )
                return False

        if not auto_detect:
            lat = config_manager.getConfigVal("defaultLat")
            lon = config_manager.getConfigVal("defaultLon")
            if not lat or not lon:
                self._validationErrorMessageBox(
                    message=_("Location auto-detect is disabled, but no default location has been searched and saved. Please search for a location and save it."),
                    option=_("Search for location")
                )
                return False
                
        return True

    def onSave(self):
        # Save credentials and providers
        config_manager.setConfigVal("provider", self.providerChoice.GetSelection())
        config_manager.setConfigVal("openWeatherApiKey", self.openWeatherKeyCtrl.GetValue().strip())
        config_manager.setConfigVal("pirateWeatherApiKey", self.pirateWeatherKeyCtrl.GetValue().strip())
        config_manager.setConfigVal("autoDetectLocation", self.autoDetectCb.GetValue())
        
        # Save Granular Units
        config_manager.setConfigVal("unit_temp", self.tempChoice.GetSelection())
        config_manager.setConfigVal("unit_wind", self.windChoice.GetSelection())
        config_manager.setConfigVal("unit_pressure", self.pressChoice.GetSelection())
        config_manager.setConfigVal("unit_visibility", self.visChoice.GetSelection())
        
        # Save Update options
        config_manager.setConfigVal("auto_update_check", self.autoUpdateCb.GetValue())
        
        # Save Favorites
        favs_str = json.dumps(self.favoriteLocations, ensure_ascii=False)
        config_manager.setConfigVal("favorites", favs_str)
        
        # Forecast settings
        config_manager.setConfigVal("forecast_type", self.forecastTypeChoice.GetSelection())
        config_manager.setConfigVal("forecast_entries", self.forecastEntriesCtrl.GetValue())
        
        # Weather checkboxes
        for key, cb in self.infoCbs.items():
            config_manager.setConfigVal(key, cb.GetValue())
            
        # Astronomy checkboxes
        for key, cb in self.astroCbs.items():
            config_manager.setConfigVal(key, cb.GetValue())
            
        # Alert checkboxes & options
        for key, cb in self.alertCbs.items():
            config_manager.setConfigVal(key, cb.GetValue())
            
        config_manager.setConfigVal("alert_speakAuto", self.alertSpeakAutoCb.GetValue())
        config_manager.setConfigVal("alert_showDialog", self.alertShowDialogCb.GetValue())
        config_manager.setConfigVal("alert_showNotification", self.alertShowNotifCb.GetValue())
        config_manager.setConfigVal("alert_repeatInterval", self.alertRepeatChoice.GetSelection())
        config_manager.setConfigVal("alert_severityFilter", self.alertSeverityChoice.GetSelection())
        
        import config
        config.conf.save()
        
        # Restart alerts checking thread if needed
        wx.CallAfter(self._restartAlertChecker)

    def _restartAlertChecker(self):
        try:
            import globalPluginHandler
            for p in globalPluginHandler.runningPlugins:
                if p.__class__.__name__ == "GlobalPlugin" and "Weather checker" in p.__class__.__module__:
                    if hasattr(p, "restartAlertChecker"):
                        p.restartAlertChecker()
                    break
        except Exception:
            pass
