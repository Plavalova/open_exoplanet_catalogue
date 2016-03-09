#!/usr/bin/env python
# this is a wicked script
import xml.etree.ElementTree as ET
import glob
import os
import hashlib
import sys
import datetime
import re
import math

num_format = re.compile(r'(?:^\s*([+\-]?(?:\d+\.?\d*|\d*\.?\d+)(?:[eE][\-+]?\d+)?)\s*$)')

# Variables to keep track of progress
fileschecked = 0
issues = 0
xmlerrors = 0
fileschanged = 0

minimal_code = 0


# Calculate md5 hash to check for changes in file.
def md5_for_file(f, block_size=2 ** 20):
    md5 = hashlib.md5()
    while True:
        data = f.read(block_size)
        if not data:
            break
        md5.update(data)
    return md5.digest()


# Nicely indents the XML output
# There is no good reason, xml.dom.minidom.parse(...) -> xml.toprettyxml()
def indent(elem, level=0):
    i = "\n" + level * "\t"
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "\t"
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            indent(elem, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


ATTRIBUTE_MAPPING = {
    'ep': ('errorplus',),
    'em': ('errorminus',),
    'error': ('errorplus', 'errorminus'),
    'e': ('errorplus', 'errorminus'),
}


def remap_attribute(element):
    for attribute_for_rename in set(element.attrib.keys()).intersection(ATTRIBUTE_MAPPING.keys()):
        for new_attribute_name in ATTRIBUTE_MAPPING[attribute_for_rename]:
            element.attrib[new_attribute_name] = element.attrib[attribute_for_rename]
        del element.attrib[attribute_for_rename]

# Removes empty nodes from the tree
def removeemptytags(elem):
    if elem.text:
        elem.text = elem.text.strip()
    toberemoved = []
    for child in elem:
        if len(child) == 0 and not child.text and len(child.attrib) == 0:
            toberemoved.append(child)
    for child in toberemoved:
        elem.remove(child)
    for child in elem:
        removeemptytags(child)
    remap_attribute(elem)

# Check if an unknown tag is present (most likely an indication for a typo)
# This is useless, until *.xsd is in use
validtags = {
    "system", "name", "new", "description", "ascendingnode", "discoveryyear",
    "lastupdate", "list", "discoverymethod", "semimajoraxis", "period", "magV", "magJ",
    "magH", "magR", "magB", "magK", "magI", "magU", "distance",
    "longitude", "imagedescription", "image", "age", "declination", "rightascension",
    "metallicity", "inclination", "spectraltype", "binary", "planet", "periastron", "star",
    "mass", "eccentricity", "radius", "temperature", "videolink", "transittime", 
    "spinorbitalignment", "istransiting", "separation", "positionangle", "periastrontime",
    "meananomaly", "minimal-code"}
validattributes = {
    "error",
    "errorplus",
    "errorminus",
    "unit",
    "upperlimit",
    "lowerlimit",
    "type"}
validlists = {
    "Confirmed planets",
    "Planets in binary systems, S-type",
    "Controversial",
    "Orphan planets",
    "Planets in binary systems, P-type",
    "Kepler Objects of Interest",
    "Solar System",
    "Retracted planet candidate"}
validdiscoverymethods = {"RV", "transit", "timing", "imaging", "microlensing"}
tagsallowmultiple = {"list", "name", "planet", "star", "binary", "separation"}
numerictags = {"mass", "radius", "ascnedingnode", "discoveryyear", "semimajoraxis", "period",
    "magV", "magJ", "magH", "magR", "magB", "magK", "magI", "magU", "distance", "longitude", "age",
    "metallicity", "inclination", "periastron", "eccentricity", "temperature", "transittime",
    "spinorbitalignment", "separation", "positionangle", "periastrontime", "meananomaly"}
numericattributes = {"error", "errorplus", "errorminus", "upperlimit", "lowerlimit"}
nonzeroattributes = {"error", "errorplus", "errorminus"}


def checkforvalidtags(elem):
    problematictag = None
    if elem.tag in numerictags:
        if elem.text:
            if not re.match(num_format,elem.text):
                return elem.tag
        deleteattribs = []
        for a in elem.attrib:
            if a in numericattributes:
                if not re.match(num_format,elem.attrib[a]):
                    return elem.tag
    for child in elem:
        # I think it could be much better subtitue it with stack
        _tmp = checkforvalidtags(child)
        if _tmp:
            problematictag = _tmp
    if elem.tag not in validtags:
        problematictag = elem.tag
    for a in elem.attrib:
        if a not in validattributes:
            return a
    return problematictag

def checkforvaliderrors(elem):
    problematictag = None
    if elem.tag in numerictags:
        deleteattribs = []
        for a in nonzeroattributes:
            try:
                if a in elem.attrib and (not elem.attrib[a] or float(elem.attrib[a]) == 0.):
                    print "Warning: deleting error bars with value 0 in tag "+elem.tag
                    elem.attrib.pop(a)
                    # deleteattribs.append(a)
            except ValueError as e:
                print "Warning probrem reading error bars in tag " + elem.tag
                print e
                elem.attrib.pop(a)
        #
        # for a in elem.attrib:
        #     if a in nonzeroattributes:
        #         try:
        #             if len(elem.attrib[a])==0 or float(elem.attrib[a])==0.:
        #                 deleteattribs.append(a)
        #         except:
        #             print "Warning: problem reading error bars in tag "+elem.tag
        #             return 1
        # for a in deleteattribs:
        #     print "Warning: deleting error bars with value 0 in tag "+elem.tag
        #     del elem.attrib[a]
        if "errorplus" in elem.attrib:
            if not "errorminus" in elem.attrib:
                print "Warning: one sided error found in tag "+elem.tag+". Fixing it."
                elem.attrib["errorminus"] = elem.attrib["errorplus"]
        if "errorminus" in elem.attrib:
            if not "errorplus" in elem.attrib:
                print "Warning: one sided error found in tag "+elem.tag+". Fixing it."
                elem.attrib["errorplus"] = elem.attrib["errorminus"]
    for child in elem:
        if checkforvaliderrors(child):
            return 1
    return 0


# Convert units (makes data entry easier)
def convert_unit_attrib(elem, attrib_name, factor):
    if not hasattr(attrib_name, '__iter__'):
        attrib_name = {attrib_name,}
    for attrib in set(attrib_name).intersection(elem.attrib.keys()):
        elem.attrib[attrib] = "%f" % (float(elem.attrib[attrib]) * factor)


UNIT_CONVERSION_SET = {'e', 'error', 'errorplus', 'errorminus', 'ep', 'em', 'upperlimit', 'lowerlimit'}


def convertunit(elem, factor):
    print "Converting unit of tag \"" + elem.tag + "\"."
    del elem.attrib['unit']
    if elem.text:
        elem.text = "%f" % (float(elem.text) * factor)
    convert_unit_attrib(elem, UNIT_CONVERSION_SET, factor)


def checkForBinaryPlanet(root, criteria, liststring):
    """ Checks if binary planets have been added to corresponding list
    """
    global fileschanged
    planets = root.findall(criteria)
    for planet in planets:
        plists = planet.findall(".//list")
        if liststring not in {plist.text for plist in plists}:
            ET.SubElement(planet, "list").text = liststring
            print "Added '" + filename + "' to list '" + liststring + "'."
            fileschanged += 1


def checkForTransitingPlanets(root):
    """ Checks for transisting planets by first seeing if there is a transittime and then checking the discovery
    method
    """
    global fileschanged
    global issues
    planets = root.findall(".//planet")
    for planet in planets:
        if not planet.findtext('.//istransiting'):
            addtag = 0
            hasTransittime = planet.findtext(".//transittime")
            discoveryMethod = planet.findtext(".//discoverymethod")
            planetRadius = planet.findtext(".//radius")
            if hasTransittime or 'transit' == discoveryMethod:
                addtag = 1
            else:
                if planetRadius:  # only measured from transits, imaging for now
                    planetName = planet.findtext(".//name")
                    excludeList = ('Mercury', 'Venus', 'Earth', 'Mars', 'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto',
                    'PSR J1719-1438 b',  # radius estimated from  Roche Lobe radius
                    '',
                    )
                    if planetName not in excludeList:
                        if not discoveryMethod == 'imaging':
                            print '{} in {} has a radius but is is missing a istransiting tag'.format(planetName, filename)
                            issues += 1

            if addtag:
                ET.SubElement(planet, "istransiting").text = '1'
                print 'Added istransiting tag to {}'.format(filename)
                fileschanged += 1


def average_dyson_temperature(eccentricity, distance, star_temperature, star_radius):
    """
    Calculate average Dyson temperature for planet.
    :param eccentricity: float
    :param distance: float
    :param star_temperature: float
    :param star_radius: float
    :return:
    """
    try:
        eccentricity = float(eccentricity)
        if eccentricity <= 0 or eccentricity > 1:
            eccentricity = 0
    except ValueError:
        eccentricity = 0.
    distance = float(distance)
    star_temperature = float(star_temperature)
    star_radius = float(star_radius)
    if distance <= 0 or star_temperature <= 0 or star_radius <= 0:
        raise ValueError('Invalid value present')
    temperature_sum = 0.
    angle = 0.
    for k in xrange(0, 10, 1):
        angle += math.pi / 5.
        e1 = angle + eccentricity * math.sin(angle)
        m1 = e1 - eccentricity * math.sin(e1)
        e2 = e1 + (angle - m1) / (1. - eccentricity * math.cos(e1))
        m2 = e2 - eccentricity * math.sin(e2)
        e3 = e2 + (angle - m2) / (1. - eccentricity * math.cos(e1))
        r = distance * (1. - eccentricity * math.cos(e3))
        temperature_sum += (((star_temperature ** 4 * star_radius ** 2) / (r ** 2)) ** (1./4))/10.
    return temperature_sum


MINIMAL_CODE_MASS = (
    (float('-inf'), .002, 'M'),
    (.002, .03, 'E'),
    (.03, .6, 'N'),
    (.6, 5., 'J'),
    (5., 15., 'S'),
    (15., float('inf'), 'D')
)


MINIMAL_CODE_TEMPERATURE = (
    (0., 250., 'F'),
    (250., 450., 'W'),
    (450., 1000., 'G'),
    (1000., float('inf'), 'R'),
)


def create_minimal_code(mass, temperature, orbits_around_pulsar=False):
    if temperature < 0 and not orbits_around_pulsar:
        raise ValueError("Invalid temperature")
    return ''.join((find_best_interval(mass, MINIMAL_CODE_MASS),
                    find_best_interval(temperature, MINIMAL_CODE_TEMPERATURE) if not orbits_around_pulsar else 'P'))


def create_full_code(mass, distance, temparature, eccentricity):
    min_code = create_minimal_code(mass, temparature)
    log_dst = math.log10(distance)
    ecc_code = int(round(eccentricity * 10))
    return "%s%.1f%s%d" % (min_code[0], log_dst, min_code[1], ecc_code)


def find_best_interval(value, intervals):
    for from_value, to_value, code in intervals:
        if from_value <= value <= to_value:
            return code


def get_mass(object_in_tree):
    return get_value(object_in_tree, "mass")


def get_radius(obj):
    return get_value(obj, "radius")


def is_pulsar_nearby(obj):
    """
    :param obj: Element
    :return: bool
    """
    for name in obj.findall("*/name"):
        return name.text.strip().startswith("PSR")


def get_temperature(obj):
    return get_value(obj, "temperature")


def get_eccentricity(obj):
    try:
        return get_value(obj, "eccentricity")
    except ValueError:
        return 0.


def create_or_overwrite(element, tag, value):
    overwritten = False
    search_for_tag = ".//%s" % tag
    for tag_element in element.findall(search_for_tag):
        if not overwritten:
            tag_element.text = value
            overwritten = True
        else:
            element.remove(tag_element)
    if not overwritten:
        child = ET.Element(tag)
        child.text = value
        element.append(child)


def remove_element(element, tag):
    search_for_tag = ".//%s" % tag
    for tag_element in element.findall(search_for_tag):
        element.remove(tag_element)


def get_value(element, tag, parser=float):
    """
    Returns parsed value of element tree object from within tag. If parser is None then return element value string
    representation.
    :param element: Element
    :param tag: string
    :param parser: parser callback
    :return: object parsed value
    """
    for value in element.findall(tag):
        try:
            if not value.text:
                if 'upperlimit' in value.attrib:
                    return parser(value.attrib['upperlimit']) if parser else value.attrib['upperlimit']
                if 'lowerlimit' in value.attrib:
                    return parser(value.attrib['lowerlimit']) if parser else value.attrib['lowerlimit']
            return parser(value.text) if parser else value.text
        except Exception as e:
            print e.message
            continue
    raise ValueError("Tag %s not found in element" % tag)


# Loop over all files and  create new data
def start_radius_in_au(star_radius):
    return 4.65247e-3 * star_radius


for filename in glob.glob("systems*/*.xml"):
    fileschecked += 1

    # Save md5 for later
    with open(filename, 'rt') as f:
        md5_orig = md5_for_file(f)
    # Open file
    with open(filename, 'rt') as f:  # it's good practice to close file, after work was finished

        # Try to parse file
        try:
            root = ET.parse(f).getroot()
            planets = root.findall(".//planet")
            stars = root.findall(".//star")
            binaries = root.findall(".//binary")
            if len(root.findall('.//minimal-code')):
                minimal_code += 1
        except ET.ParseError as error:
            print '{}, {}'.format(filename, error)
            xmlerrors += 1
            issues += 1
            # f.close()
            continue
        finally:
            f.close()

        # Find tags with range=1 and convert to default error format
        for elem in root.findall(".//*[@range='1']"):
            fragments = elem.text.split()
            elem.text = fragments[0]
            elem.attrib["errorminus"] = "%f" % (float(fragments[0]) - float(fragments[1]))
            elem.attrib["errorplus"] = "%f" % (float(fragments[2]) - float(fragments[0]))
            del elem.attrib["range"]
            print "Converted range to errorbars in tag '" + elem.tag + "'."

            # Convert units to default units
        for mass in root.findall(".//planet/mass[@unit='me']"):
            convertunit(mass, 0.0031457007)
        for radius in root.findall(".//planet/radius[@unit='re']"):
            convertunit(radius, 0.091130294)
        for angle in root.findall(".//*[@unit='rad']"):
            convertunit(angle, 57.2957795130823)

        for star in root.findall(".//star"):
            try:
                pulsar = is_pulsar_nearby(star)
                star_temperature = -1.
                if not pulsar:
                    star_temperature = get_temperature(star)
                star_radius = get_radius(star)
                for planet in star.findall(".//planet"):
                    try:
                        eccentricity = get_eccentricity(planet)
                        distance = get_value(planet, "semimajoraxis")
                        _temp = -1.  # This value is not reachable
                        if not pulsar:
                            _temp = average_dyson_temperature(eccentricity, distance, star_temperature, start_radius_in_au(star_radius))
                        min_code = create_minimal_code(
                            get_mass(planet),
                            _temp,
                            pulsar
                        )
                        full_code = create_full_code(get_mass(planet), distance, _temp, eccentricity)
                        create_or_overwrite(planet, "minimal-code", min_code)
                        create_or_overwrite(planet, "full-code", full_code)
                        remove_element(planet, "dyson-temperature")
                        remove_element(planet, "d-temp")
                    except ValueError:
                        continue
            except ValueError:
                continue

        # Check lastupdate tag for correctness
        for lastupdate in root.findall(".//planet/lastupdate"):
            la = lastupdate.text.split("/")
            if len(la) != 3 or len(lastupdate.text) != 8: # this is pointless. By this check is also valid %$/sd/\nk
                print "Date format not following 'yy/mm/dd' convention: " + filename
                issues += 1
            if int(la[0]) + 2000 - datetime.date.today().year > 0 or int(la[1]) > 12 or int(la[2]) > 31:
                print "Date not valid: " + filename
                issues += 1

        # Check that names follow conventions
        if not root.findtext("./name") + ".xml" == os.path.basename(filename):
            print "Name of system not the same as filename: " + filename
            issues += 1
        for obj in planets + stars:
            name = obj.findtext("./name")
            if not name:
                print "Didn't find name tag for object \"" + obj.tag + "\" in file \"" + filename + "\"."
                issues += 1

        # Check if tags are valid and have valid attributes
        if checkforvaliderrors(root):
            print "Problematic errorbar in in file \"" + filename + "\"."

        problematictag = checkforvalidtags(root)
        if problematictag:
            print "Problematic tag/attribute '" + problematictag + "' found in file \"" + filename + "\"."
            issues += 1
        discoverymethods = root.findall(".//discoverymethod")
        for dm in discoverymethods:
            if not (dm.text in validdiscoverymethods):
                print "Problematic discoverymethod '" + dm.text + "' found in file \"" + filename + "\"."
                issues += 1

        # Check if there are duplicate tags
        for obj in planets + stars + binaries:
            uniquetags = []
            for child in obj:
                if not child.tag in tagsallowmultiple:
                    if child.tag in uniquetags:
                        print "Error: Found duplicate tag \"" + child.tag + "\" in file \"" + filename + "\"."
                        issues += 1
                    else:
                        uniquetags.append(child.tag)

        # Check binary planet lists
        checkForBinaryPlanet(root, ".//binary/planet", "Planets in binary systems, P-type")
        checkForBinaryPlanet(root, ".//binary/star/planet", "Planets in binary systems, S-type")

        # Check for valid list names
        lists = root.findall(".//list")
        for l in lists:
            if l.text not in validlists:
                    print "Error: Invalid list \"" + l.text + "\" in file \"" + filename + "\"."
                    issues += 1

        # Check if each planet is in at least one list
        oneListOf = ["Confirmed planets", "Controversial", "Kepler Objects of Interest","Solar System", "Retracted planet candidate"]
        for p in planets:
            isInList = 0
            for l in p.findall("./list"):
                if l.text in oneListOf:
                    isInList += 1
            if isInList!=1:
                print "Error: Planet needs to be in exactly one of the following lists: '" + "', '".join(oneListOf) \
                      + "'. Check planets in file \"" + filename + "\"."
                issues += 1


        # Check transiting planets
        checkForTransitingPlanets(root)

        # Cleanup XML
        removeemptytags(root)
        indent(root)

        # Write XML to file.
        ET.ElementTree(root).write(filename, encoding="UTF-8", xml_declaration=False)

        # Check for new md5
    with open(filename, 'rt') as f:
        md5_new = md5_for_file(f)
        if md5_orig != md5_new:
            fileschanged += 1

errorcode = 0
print "Cleanup script finished. %d files checked." % fileschecked
if fileschanged > 0:
    print "%d file(s) modified." % fileschanged
    errorcode = 1

print "Minimal code computed: %d" % minimal_code

if xmlerrors > 0:
    print "%d XML errors found." % xmlerrors
    errorcode = 2

if issues > 0:
    print "Number of issues: %d (see above)." % issues
    errorcode = 3
else:
    print "No issues found."

sys.exit(errorcode)

