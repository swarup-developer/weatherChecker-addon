import os

addon_info = {
    "addon_name": "weatherChecker",
    "addon_version": "3.0.1",
    "summary": "Weather Checker",
    "description": "Provides weather conditions, forecasts, astronomy data, and weather alerts using OpenWeather and Pirate Weather APIs.",
    "author": "Swarup Baral",
    "url": "https://example.com/weatherChecker",
    "license": "GPL-2",
    "minimumNVDAVersion": "2024.1",
    "lastTestedNVDAVersion": "2026.3",
}

pythonSources = [
    os.path.join("addon", "globalPlugins", "*.py"),
    os.path.join("addon", "globalPlugins", "Weather checker", "*.py")
]

i18nSources = pythonSources + ["buildVars.py"]
sconstructFile = "SConstruct"
manifestFile = "manifest.ini"
