import requests
from django.shortcuts import render
from django.conf import settings
from django.core.cache import cache
from .forms import CityForm
from datetime import datetime, timedelta
from collections import defaultdict

# -- helpers ------------------------------------------------------------------
def _openweather_request(path, params):
    base = settings.OPENWEATHER_BASE
    api_key = settings.OPENWEATHER_API_KEY
    params = {**params, 'appid': api_key}
    url = f"{base}/{path}"
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()

def fetch_current_by_city(city, units='metric'):
    return _openweather_request('weather', {'q': city, 'units': units})

def fetch_current_by_coords(lat, lon, units='metric'):
    return _openweather_request('weather', {'lat': lat, 'lon': lon, 'units': units})

def fetch_forecast_by_city(city, units='metric'):
    return _openweather_request('forecast', {'q': city, 'units': units})

def fetch_forecast_by_coords(lat, lon, units='metric'):
    return _openweather_request('forecast', {'lat': lat, 'lon': lon, 'units': units})

def build_current_payload(raw, units):
    tz = raw.get('timezone', 0)
    return {
        'city': f"{raw.get('name')}, {raw.get('sys',{}).get('country')}",
        'description': raw['weather'][0]['description'].title(),
        'temp': raw['main']['temp'],
        'feels_like': raw['main'].get('feels_like'),
        'temp_min': raw['main'].get('temp_min'),
        'temp_max': raw['main'].get('temp_max'),
        'humidity': raw['main'].get('humidity'),
        'pressure': raw['main'].get('pressure'),
        'wind_speed': raw.get('wind', {}).get('speed'),
        'icon': raw['weather'][0]['icon'],
        'sunrise': datetime.utcfromtimestamp(raw['sys']['sunrise'] + tz).strftime('%H:%M'),
        'sunset': datetime.utcfromtimestamp(raw['sys']['sunset'] + tz).strftime('%H:%M'),
        'units': '°C' if units=='metric' else '°F',
        'coord': raw.get('coord', {})
    }

def build_forecast_payload(raw_forecast, units):
    """
    raw_forecast: JSON from /forecast (3-hour steps, ~40 entries)
    We'll aggregate per calendar day (based on UTC + city timezone if present).
    For each day we compute min/max temps, choose a representative icon (midday if possible),
    and produce a list for charting (daily_avg).
    """
    tz = raw_forecast.get('city', {}).get('timezone', 0)
    entries = raw_forecast.get('list', [])
    days = defaultdict(list)

    for e in entries:
        ts = e['dt'] + tz
        dt = datetime.utcfromtimestamp(ts)
        day_key = dt.date().isoformat()
        days[day_key].append({
            'dt': dt,
            'temp': e['main']['temp'],
            'icon': e['weather'][0]['icon'],
            'desc': e['weather'][0]['description'].title()
        })

    # build daily summaries (limit to next 5 distinct days)
    sorted_days = sorted(days.items(), key=lambda kv: kv[0])
    daily = []
    for day, items in sorted_days[:5]:
        temps = [it['temp'] for it in items]
        # Try to pick icon at ~12:00 if present, else first
        midday = min(items, key=lambda it: abs(it['dt'].hour - 12))
        daily.append({
            'date': day,
            'temp_min': min(temps),
            'temp_max': max(temps),
            'temp_avg': sum(temps)/len(temps),
            'icon': midday['icon'],
            'desc': midday['desc']
        })

    # prepare chart arrays (dates and avg temps)
    chart = {
        'labels': [d['date'] for d in daily],
        'data': [round(d['temp_avg'], 2) for d in daily]
    }
    return {'daily': daily, 'chart': chart, 'units': '°C' if units=='metric' else '°F'}

# -- main view ---------------------------------------------------------------
def index(request):
    weather_data = None
    forecast_data = None
    error = None
    form = CityForm(request.GET or None)

    # Decide lookup mode: coordinates override city if both provided
    lat = request.GET.get('lat') or (form.data.get('lat') if form.is_bound else None)
    lon = request.GET.get('lon') or (form.data.get('lon') if form.is_bound else None)
    city = request.GET.get('city') or (form.data.get('city') if form.is_bound else None)
    units = request.GET.get('units', 'metric')

    # normalize values
    if city:
        city = city.strip()
    if lat == '':
        lat = None
    if lon == '':
        lon = None

    if city or (lat and lon):
        # create cache keys
        if lat and lon:
            key_cur = f"weather:coords:{lat}:{lon}:{units}"
            key_fore = f"forecast:coords:{lat}:{lon}:{units}"
        else:
            key_cur = f"weather:city:{city.lower()}:{units}"
            key_fore = f"forecast:city:{city.lower()}:{units}"

        # try cache
        cached_cur = cache.get(key_cur)
        cached_fore = cache.get(key_fore)
        if cached_cur:
            weather_data = cached_cur
        if cached_fore:
            forecast_data = cached_fore

        # fetch if missing
        try:
            if not weather_data:
                if lat and lon:
                    raw = fetch_current_by_coords(lat, lon, units=units)
                else:
                    raw = fetch_current_by_city(city, units=units)
                weather_data = build_current_payload(raw, units)
                # short cache for current weather (5 minutes)
                cache.set(key_cur, weather_data, timeout=300)

            if not forecast_data:
                if lat and lon:
                    rawf = fetch_forecast_by_coords(lat, lon, units=units)
                else:
                    rawf = fetch_forecast_by_city(city, units=units)
                forecast_data = build_forecast_payload(rawf, units)
                # forecast can be cached longer (20 minutes)
                cache.set(key_fore, forecast_data, timeout=1200)

        except requests.HTTPError as e:
            try:
                msg = e.response.json().get('message', '')
            except Exception:
                msg = str(e)
            error = f"API error: {msg}"
        except requests.RequestException as e:
            error = f"Connection error: {str(e)}"
        except Exception as e:
            error = f"Unexpected error: {str(e)}"

    context = {
        'form': form,
        'weather': weather_data,
        'forecast': forecast_data,
        'error': error,
    }
    return render(request, 'weather/index.html', context)
