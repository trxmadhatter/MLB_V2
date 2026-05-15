"""
Home plate umpire K-tendency scores.
Scale: -1.0 = very tight zone (fewer Ks), 0.0 = league avg, +1.0 = wide zone (more Ks).
Source: UmpScorecards historical data (approximate, refresh periodically).
"""
from __future__ import annotations

_UMPIRES: dict[str, float] = {
    "jordan baker":        0.3,
    "vic carapazza":       0.3,
    "alan porter":         0.3,
    "pat hoberg":          0.2,
    "adam hamari":         0.2,
    "tripp gibson":        0.2,
    "tim timmons":         0.2,
    "hunter wendelstedt":  0.2,
    "bill miller":         0.1,
    "james hoye":          0.1,
    "cory blaser":         0.1,
    "scott barry":         0.1,
    "ron kulpa":           0.1,
    "todd tichenor":       0.1,
    "paul nauert":         0.2,
    "mike muchlinski":     0.2,
    "nic lentz":           0.1,
    "david rackley":       0.1,
    "shane livensparger":  0.1,
    "chris guccione":      0.0,
    "ted barrett":         0.0,
    "dan iassogna":        0.0,
    "manny gonzalez":      0.1,
    "mark ripperger":      0.0,
    "ryan blakney":        0.0,
    "nate tomlinson":      0.1,
    "john bacon":          0.0,
    "edwin moscoso":       0.0,
    "ben may":             0.0,
    "jeremie rehak":       0.0,
    "chris conroy":        0.0,
    "brennan miller":      0.1,
    "jeff nelson":         0.1,
    "sam holbrook":       -0.1,
    "phil cuzzi":         -0.1,
    "tom hallion":        -0.1,
    "gary cederstrom":    -0.2,
    "roberto ortiz":      -0.2,
    "dan bellino":        -0.2,
    "marty foster":       -0.2,
    "jerry meals":        -0.2,
    "cb bucknor":         -0.3,
    "laz diaz":           -0.3,
    "lance barksdale":    -0.3,
    "adrian johnson":     -0.1,
}


def get_ump_k_tendency(umpire_name: str | None) -> float:
    """Return K-tendency for umpire name. 0.0 if unknown."""
    if not umpire_name:
        return 0.0
    return _UMPIRES.get(umpire_name.lower().strip(), 0.0)
