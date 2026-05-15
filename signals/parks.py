"""
Static MLB park factors and stadium metadata.
Park factors: 100 = league average. >100 = more of that outcome at this park.
Source: Statcast 3-year rolling park factors (2024-2026 approximation).
cf_bearing: compass bearing (degrees) from home plate to center field.
           Wind blowing IN this direction = tailwind for batters (helps Overs).
Update: once per season or when dramatically stale.
"""

NEUTRAL_PARK = {
    "name": "Unknown",
    "is_dome": False,
    "lat": 39.5, "lon": -98.35,   # geographic center of USA
    "cf_bearing": 0,
    "k_factor": 100, "hits_factor": 100, "tb_factor": 100, "hr_factor": 100,
}

_PARKS: dict[str, dict] = {
    "Arizona Diamondbacks": {
        "name": "Chase Field", "is_dome": True,
        "lat": 33.4453, "lon": -112.0667, "cf_bearing": 330,
        "k_factor": 98, "hits_factor": 105, "tb_factor": 107, "hr_factor": 110,
    },
    "Atlanta Braves": {
        "name": "Truist Park", "is_dome": False,
        "lat": 33.8905, "lon": -84.4677, "cf_bearing": 0,
        "k_factor": 98, "hits_factor": 102, "tb_factor": 103, "hr_factor": 102,
    },
    "Baltimore Orioles": {
        "name": "Camden Yards", "is_dome": False,
        "lat": 39.2838, "lon": -76.6218, "cf_bearing": 10,
        "k_factor": 98, "hits_factor": 106, "tb_factor": 108, "hr_factor": 116,
    },
    "Boston Red Sox": {
        "name": "Fenway Park", "is_dome": False,
        "lat": 42.3467, "lon": -71.0972, "cf_bearing": 85,
        "k_factor": 96, "hits_factor": 110, "tb_factor": 109, "hr_factor": 100,
    },
    "Chicago Cubs": {
        "name": "Wrigley Field", "is_dome": False,
        "lat": 41.9484, "lon": -87.6553, "cf_bearing": 60,
        "k_factor": 97, "hits_factor": 106, "tb_factor": 106, "hr_factor": 107,
    },
    "Chicago White Sox": {
        "name": "Guaranteed Rate Field", "is_dome": False,
        "lat": 41.8300, "lon": -87.6339, "cf_bearing": 350,
        "k_factor": 99, "hits_factor": 102, "tb_factor": 104, "hr_factor": 108,
    },
    "Cincinnati Reds": {
        "name": "Great American Ball Park", "is_dome": False,
        "lat": 39.0975, "lon": -84.5060, "cf_bearing": 10,
        "k_factor": 95, "hits_factor": 107, "tb_factor": 112, "hr_factor": 130,
    },
    "Cleveland Guardians": {
        "name": "Progressive Field", "is_dome": False,
        "lat": 41.4962, "lon": -81.6852, "cf_bearing": 10,
        "k_factor": 101, "hits_factor": 98, "tb_factor": 98, "hr_factor": 95,
    },
    "Colorado Rockies": {
        "name": "Coors Field", "is_dome": False,
        "lat": 39.7559, "lon": -104.9942, "cf_bearing": 50,
        "k_factor": 92, "hits_factor": 126, "tb_factor": 119, "hr_factor": 124,
    },
    "Detroit Tigers": {
        "name": "Comerica Park", "is_dome": False,
        "lat": 42.3390, "lon": -83.0485, "cf_bearing": 355,
        "k_factor": 100, "hits_factor": 99, "tb_factor": 98, "hr_factor": 90,
    },
    "Houston Astros": {
        "name": "Minute Maid Park", "is_dome": True,
        "lat": 29.7573, "lon": -95.3556, "cf_bearing": 340,
        "k_factor": 100, "hits_factor": 100, "tb_factor": 103, "hr_factor": 103,
    },
    "Kansas City Royals": {
        "name": "Kauffman Stadium", "is_dome": False,
        "lat": 39.0517, "lon": -94.4803, "cf_bearing": 15,
        "k_factor": 100, "hits_factor": 101, "tb_factor": 101, "hr_factor": 99,
    },
    "Los Angeles Angels": {
        "name": "Angel Stadium", "is_dome": False,
        "lat": 33.8003, "lon": -117.8827, "cf_bearing": 325,
        "k_factor": 102, "hits_factor": 97, "tb_factor": 97, "hr_factor": 92,
    },
    "Los Angeles Dodgers": {
        "name": "Dodger Stadium", "is_dome": False,
        "lat": 34.0739, "lon": -118.2400, "cf_bearing": 25,
        "k_factor": 103, "hits_factor": 95, "tb_factor": 97, "hr_factor": 95,
    },
    "Miami Marlins": {
        "name": "loanDepot Park", "is_dome": True,
        "lat": 25.7781, "lon": -80.2197, "cf_bearing": 350,
        "k_factor": 101, "hits_factor": 95, "tb_factor": 95, "hr_factor": 91,
    },
    "Milwaukee Brewers": {
        "name": "American Family Field", "is_dome": True,
        "lat": 43.0280, "lon": -87.9712, "cf_bearing": 310,
        "k_factor": 99, "hits_factor": 100, "tb_factor": 101, "hr_factor": 102,
    },
    "Minnesota Twins": {
        "name": "Target Field", "is_dome": False,
        "lat": 44.9817, "lon": -93.2783, "cf_bearing": 330,
        "k_factor": 101, "hits_factor": 99, "tb_factor": 100, "hr_factor": 99,
    },
    "New York Mets": {
        "name": "Citi Field", "is_dome": False,
        "lat": 40.7571, "lon": -73.8458, "cf_bearing": 350,
        "k_factor": 103, "hits_factor": 95, "tb_factor": 96, "hr_factor": 87,
    },
    "New York Yankees": {
        "name": "Yankee Stadium", "is_dome": False,
        "lat": 40.8296, "lon": -73.9262, "cf_bearing": 315,
        "k_factor": 100, "hits_factor": 99, "tb_factor": 109, "hr_factor": 126,
    },
    "Oakland Athletics": {
        "name": "Sutter Health Park", "is_dome": False,
        "lat": 38.5833, "lon": -121.5100, "cf_bearing": 0,
        "k_factor": 100, "hits_factor": 98, "tb_factor": 97, "hr_factor": 95,
    },
    "Philadelphia Phillies": {
        "name": "Citizens Bank Park", "is_dome": False,
        "lat": 39.9061, "lon": -75.1665, "cf_bearing": 355,
        "k_factor": 97, "hits_factor": 107, "tb_factor": 110, "hr_factor": 121,
    },
    "Pittsburgh Pirates": {
        "name": "PNC Park", "is_dome": False,
        "lat": 40.4469, "lon": -80.0057, "cf_bearing": 30,
        "k_factor": 101, "hits_factor": 99, "tb_factor": 98, "hr_factor": 96,
    },
    "San Diego Padres": {
        "name": "Petco Park", "is_dome": False,
        "lat": 32.7076, "lon": -117.1570, "cf_bearing": 325,
        "k_factor": 102, "hits_factor": 93, "tb_factor": 94, "hr_factor": 91,
    },
    "San Francisco Giants": {
        "name": "Oracle Park", "is_dome": False,
        "lat": 37.7786, "lon": -122.3893, "cf_bearing": 355,
        "k_factor": 104, "hits_factor": 88, "tb_factor": 91, "hr_factor": 78,
    },
    "Seattle Mariners": {
        "name": "T-Mobile Park", "is_dome": False,
        "lat": 47.5914, "lon": -122.3325, "cf_bearing": 0,
        "k_factor": 101, "hits_factor": 96, "tb_factor": 96, "hr_factor": 88,
    },
    "St. Louis Cardinals": {
        "name": "Busch Stadium", "is_dome": False,
        "lat": 38.6226, "lon": -90.1928, "cf_bearing": 0,
        "k_factor": 101, "hits_factor": 97, "tb_factor": 98, "hr_factor": 94,
    },
    "Tampa Bay Rays": {
        "name": "Tropicana Field", "is_dome": True,
        "lat": 27.7683, "lon": -82.6534, "cf_bearing": 0,
        "k_factor": 100, "hits_factor": 97, "tb_factor": 97, "hr_factor": 100,
    },
    "Texas Rangers": {
        "name": "Globe Life Field", "is_dome": True,
        "lat": 32.7512, "lon": -97.0826, "cf_bearing": 0,
        "k_factor": 100, "hits_factor": 99, "tb_factor": 100, "hr_factor": 100,
    },
    "Toronto Blue Jays": {
        "name": "Rogers Centre", "is_dome": True,
        "lat": 43.6414, "lon": -79.3892, "cf_bearing": 320,
        "k_factor": 99, "hits_factor": 101, "tb_factor": 104, "hr_factor": 107,
    },
    "Washington Nationals": {
        "name": "Nationals Park", "is_dome": False,
        "lat": 38.8730, "lon": -77.0074, "cf_bearing": 355,
        "k_factor": 100, "hits_factor": 99, "tb_factor": 100, "hr_factor": 100,
    },
}

_ALIASES: dict[str, str] = {
    "Athletics":                  "Oakland Athletics",
    "Sacramento Athletics":       "Oakland Athletics",
    "Diamondbacks":               "Arizona Diamondbacks",
    "D-backs":                    "Arizona Diamondbacks",
}


def get_park(home_team: str) -> dict:
    """Return park data for the home team. Falls back to NEUTRAL_PARK."""
    team = _ALIASES.get(home_team, home_team)
    return _PARKS.get(team, NEUTRAL_PARK)


def list_teams() -> list[str]:
    return list(_PARKS.keys())
