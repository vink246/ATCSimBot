from selenium.webdriver import Firefox
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import ElementNotInteractableException
import time
import re

TAKEOFF_QUEUE = 0
DEPARTURE = 1
ARRIVAL = 2
APPROACHING = 3


# Start up chrome and open the website
driver = Firefox()
driver.maximize_window()
driver.get('http://atc-sim.com/')

# Change the airport and start the game
driver.find_element(by=By.XPATH,
                    value='/html/body/div[4]/div[1]/form/table/tbody/tr/td[1]/div[1]/select/option[4]').click()
driver.find_element_by_xpath(
    '//*[@id="frmOptions"]/table/tbody/tr/td[1]/div[7]/select/option[4]').click()
driver.find_element(by=By.XPATH,
                    value='//*[@id="frmOptions"]/table/tbody/tr/td[1]/input[1]').click()
time.sleep(3)

failed = True
while failed:
    try:
        driver.find_element(by=By.XPATH, value='//*[@id="btnclose"]').click()
        failed = False
    except ElementNotInteractableException:
        time.sleep(1)

command_input = driver.find_element(by=By.XPATH,
                                    value='//*[@id="canvas"]/div[1]/div/form/input[1]')
# Plane States is an array that stores the state of each plane in play
# It has a list of sub-arrays corresponding to each possible state
# 0 - planes waiting to takeoff - (Callsign, Runway, Destination)
# 1 - planes departing
# 2 - planes being guided to their final approach
# 3 - planes on final approach
# Each index will contain an array of each plane in that state
plane_states = [[], [], [], []]


def parse_plane_strips(html):
    global plane_states

    plane_states = [[], [], [], []]
    to_queue_expression = \
        r'<div id="(.+?)" name="\1".+? rgb\(192, 228, 250\);">\1 &nbsp;(\d{1,2}[LR]).+?To: (.{3,6})<'
    for match in re.findall(to_queue_expression, html):
        # print('Departure Callsign: {}, Runway: {}, Destination: {}'.format(match[0], match[1], match[2]))
        plane_states[TAKEOFF_QUEUE].append([match[0], match[1], match[2]])

    departure_expression = r'<div id="(.+?)" name="\1".+? rgb\(192, 228, 250\);">\1 &nbsp;(\D.+?) '
    for match in re.findall(departure_expression, html):
        # print('Departure Callsign: {}, Destination: {}'.format(match[0], match[1]))
        plane_states[DEPARTURE].append([match[0], match[1]])

    arrival_expression = r'<div id="(.+?)" name="\1".+? rgb\(252, 240, 198\);">\1 &nbsp;(\w[A-Z]{2,5}|\d{2,3}°)'
    for match in re.findall(arrival_expression, html):
        # print('Arrival Callsign: {}, Heading: {}'.format(match[0], match[1]))
        plane_states[ARRIVAL].append([match[0], match[1].replace('°', '')])

    approach_expression = r'<div id="(.+?)" name="\1".+? rgb\(252, 240, 198\);">\1 &nbsp;((?:9|27)[LR])'
    for match in re.findall(approach_expression, html):
        # print('Approach Callsign: {}, Destination: {}'.format(match[0], match[1]))
        plane_states[APPROACHING].append([match[0], match[1]])


def parse_canvas(html):
    parse_expression = r'<div id="(.+?)" class="SanSerif12".+?left: (.+?)px; top: (.+?)px.*\1<br>(\d{3})'
    for match in re.findall(parse_expression, html):
        callsign = match[0]
        # Iterate through each plane to find the matching callsign and then append the values of x, y and alt
        # Quite inefficient but it works because there are only around 10 - 20 planes tops
        # Might update indexing later to make this prettier
        for category in plane_states:
            for plane in category:
                if plane[0] == callsign:
                    plane.append(int(match[1]))
                    plane.append(int(match[2]))
                    plane.append(int(match[3]) * 100)


def get_command_list():
    command_list = []

    # First find if it is safe for a plane to takeoff
    # Values of min & max height for TO and Landing aircraft can be changed later
    safe_for_hold = True

    # Index 0 is Left Rwy, Index 1 is Right Rwy
    safe_runways = [True, True]
    for departure in plane_states[DEPARTURE]:
        if departure[4] < 200:
            safe_for_takeoff = False

    for approaching in plane_states[APPROACHING]:
        if approaching[4] < 700:
            
            safe_for_takeoff = False

    if safe_for_takeoff and len(plane_states[TAKEOFF_QUEUE]):
        callsign = plane_states[TAKEOFF_QUEUE][0][0]
        destination = plane_states[TAKEOFF_QUEUE][0][2]
        command_list.append('{} C {} C 11 T'.format(callsign, destination))

    return command_list


def execute_commands(commands):
    for command in commands:
        print("Executing command:", command)
        command_input.send_keys(command)
        command_input.send_keys(Keys.ENTER)


while True:
    driver.switch_to.frame('ProgressStrips')
    strips_text = driver.find_element(by=By.XPATH,
                                      value='//*[@id="strips"]').get_attribute('innerHTML')
    parse_plane_strips(strips_text)
    driver.switch_to.parent_frame()
    canvas_text = driver.find_element(by=By.XPATH,
                                      value='//*[@id="canvas"]').get_attribute('innerHTML')
    parse_canvas(canvas_text)
    command_list = get_command_list()
    execute_commands(command_list)
    time.sleep(2)
