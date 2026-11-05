"""Cities searched in each state, largest first.

Every search is "<term> in <city>, <ST>". Google Maps returns agencies in and
around the city, so a handful of cities per state covers it well.
"""
from __future__ import annotations

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
NAME_TO_CODE = {v.lower(): k for k, v in STATE_NAMES.items()}

CITIES = {
    "AL": ["Birmingham", "Huntsville", "Montgomery", "Mobile", "Tuscaloosa", "Auburn"],
    "AK": ["Anchorage", "Fairbanks", "Juneau"],
    "AZ": ["Phoenix", "Tucson", "Mesa", "Scottsdale", "Chandler", "Gilbert", "Tempe", "Flagstaff"],
    "AR": ["Little Rock", "Fayetteville", "Fort Smith", "Bentonville", "Jonesboro"],
    "CA": ["Los Angeles", "San Diego", "San Jose", "San Francisco", "Fresno", "Sacramento",
           "Long Beach", "Oakland", "Irvine", "Riverside", "Santa Barbara", "Bakersfield",
           "Pasadena", "Santa Monica", "Newport Beach", "Temecula"],
    "CO": ["Denver", "Colorado Springs", "Aurora", "Fort Collins", "Boulder", "Lakewood"],
    "CT": ["Hartford", "New Haven", "Stamford", "Bridgeport", "Norwalk"],
    "DE": ["Wilmington", "Dover", "Newark"],
    "DC": ["Washington"],
    "FL": ["Miami", "Tampa", "Orlando", "Jacksonville", "St. Petersburg", "Fort Lauderdale",
           "Tallahassee", "Sarasota", "Naples", "Fort Myers", "West Palm Beach", "Boca Raton",
           "Gainesville", "Pensacola", "Lakeland", "Clearwater"],
    "GA": ["Atlanta", "Savannah", "Augusta", "Columbus", "Macon", "Athens", "Alpharetta", "Marietta"],
    "HI": ["Honolulu", "Hilo", "Kailua"],
    "ID": ["Boise", "Meridian", "Idaho Falls", "Coeur d'Alene"],
    "IL": ["Chicago", "Naperville", "Aurora", "Rockford", "Springfield", "Peoria", "Schaumburg"],
    "IN": ["Indianapolis", "Fort Wayne", "Evansville", "South Bend", "Carmel", "Bloomington"],
    "IA": ["Des Moines", "Cedar Rapids", "Davenport", "Iowa City", "Sioux City"],
    "KS": ["Wichita", "Overland Park", "Kansas City", "Topeka", "Lawrence"],
    "KY": ["Louisville", "Lexington", "Bowling Green", "Covington"],
    "LA": ["New Orleans", "Baton Rouge", "Shreveport", "Lafayette", "Lake Charles"],
    "ME": ["Portland", "Bangor", "Lewiston"],
    "MD": ["Baltimore", "Annapolis", "Frederick", "Rockville", "Columbia", "Bethesda"],
    "MA": ["Boston", "Worcester", "Springfield", "Cambridge", "Lowell", "Plymouth"],
    "MI": ["Detroit", "Grand Rapids", "Ann Arbor", "Lansing", "Troy", "Kalamazoo", "Traverse City"],
    "MN": ["Minneapolis", "St. Paul", "Rochester", "Duluth", "Bloomington"],
    "MS": ["Jackson", "Gulfport", "Hattiesburg", "Oxford"],
    "MO": ["Kansas City", "St. Louis", "Springfield", "Columbia", "Chesterfield"],
    "MT": ["Billings", "Missoula", "Bozeman", "Great Falls"],
    "NE": ["Omaha", "Lincoln", "Grand Island"],
    "NV": ["Las Vegas", "Henderson", "Reno"],
    "NH": ["Manchester", "Nashua", "Portsmouth", "Concord"],
    "NJ": ["Newark", "Jersey City", "Hoboken", "Princeton", "Morristown", "Cherry Hill", "Red Bank"],
    "NM": ["Albuquerque", "Santa Fe", "Las Cruces"],
    "NY": ["New York", "Brooklyn", "Buffalo", "Rochester", "Albany", "Syracuse", "Long Island",
           "White Plains", "Queens"],
    "NC": ["Charlotte", "Raleigh", "Durham", "Greensboro", "Wilmington", "Asheville", "Cary"],
    "ND": ["Fargo", "Bismarck", "Grand Forks"],
    "OH": ["Columbus", "Cleveland", "Cincinnati", "Toledo", "Akron", "Dayton"],
    "OK": ["Oklahoma City", "Tulsa", "Norman", "Edmond"],
    "OR": ["Portland", "Eugene", "Salem", "Bend", "Medford"],
    "PA": ["Philadelphia", "Pittsburgh", "Allentown", "Harrisburg", "Lancaster", "Erie", "Scranton"],
    "RI": ["Providence", "Warwick", "Newport"],
    "SC": ["Charleston", "Columbia", "Greenville", "Myrtle Beach", "Hilton Head Island"],
    "SD": ["Sioux Falls", "Rapid City"],
    "TN": ["Nashville", "Memphis", "Knoxville", "Chattanooga", "Franklin", "Murfreesboro"],
    "TX": ["Houston", "Dallas", "Austin", "San Antonio", "Fort Worth", "El Paso", "Plano",
           "Frisco", "The Woodlands", "Corpus Christi", "Lubbock", "McKinney", "Arlington"],
    "UT": ["Salt Lake City", "Provo", "Ogden", "St. George", "Lehi"],
    "VT": ["Burlington", "Montpelier"],
    "VA": ["Virginia Beach", "Richmond", "Arlington", "Norfolk", "Alexandria", "Roanoke",
           "Charlottesville"],
    "WA": ["Seattle", "Spokane", "Tacoma", "Bellevue", "Vancouver", "Everett"],
    "WV": ["Charleston", "Morgantown", "Huntington"],
    "WI": ["Milwaukee", "Madison", "Green Bay", "Appleton"],
    "WY": ["Cheyenne", "Casper", "Jackson"],
}


def all_queries(states: list[str], terms: list[str]) -> list[tuple[str, str]]:
    """(query, state) pairs, interleaved so a nightly batch spreads across
    states and terms instead of exhausting one city first."""
    states = [s.upper() for s in (states or sorted(CITIES))]
    out = []
    depth = max(len(CITIES.get(s, [])) for s in states) if states else 0
    for i in range(depth):
        for term in terms:
            for st in states:
                cities = CITIES.get(st, [])
                if i < len(cities):
                    out.append((f"{term} in {cities[i]}, {st}", st))
    return out
