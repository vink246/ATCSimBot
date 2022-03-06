from subprocess import call
from selenium.webdriver import Firefox
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import ElementNotInteractableException
import time
import re
import math

TAKEOFF_QUEUE = 0
DEPARTURE = 1
ARRIVAL = 2
APPROACHING = 3

# Plane States is an array that stores the state of each plane in play
# It has a list of sub-arrays corresponding to each possible state
# 0 - planes waiting to takeoff - (Callsign, Runway, Destination)
# 1 - planes departing
# 2 - planes being guided to their final approach
# 3 - planes on final approach
# Each index will contain an array of each plane in that state
plane_states = [[], [], [], []]
taking_off = []
arrival_states = {}


# Target points with 09 landing runway
TARGET_POINTS_09_N = [(350, 800), (350, 600)]
TARGET_POINTS_09_S = [(350, 150), (350, 350)]
# Target points with 27 landing runway
TARGET_POINTS_27_N = [(1350, 800), (1350, 600)]
TARGET_POINTS_27_S = [(1350, 200), (1350, 400)]
# Target points
target_points = []
landing_rwy = ''
target_rwy = ''


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
        if match[0] in taking_off:
            taking_off.remove(match[0])

    arrival_expression = r'<div id="(.+?)" name="\1".+? rgb\(252, 240, 198\);">\1 &nbsp;(\w[A-Z]{2,5}|\d{2,3}°)'
    for match in re.findall(arrival_expression, html):
        # print('Arrival Callsign: {}, Heading: {}'.format(match[0], match[1]))
        plane_states[ARRIVAL].append([match[0], match[1].replace('°', '')])

    approach_expression = r'<div id="(.+?)" name="\1".+? rgb\(252, 240, 198\);">\1 &nbsp;((?:9|27)[LR])'
    for match in re.findall(approach_expression, html):
        # print('Approach Callsign: {}, Runway: {}'.format(match[0], match[1]))
        plane_states[APPROACHING].append([match[0], match[1]])
        if match[0] in arrival_states.keys():
            arrival_states.pop(match[0])
            if 'L' in target_rwy: 
                target_rwy.replace('L', 'R')
            else:
                target_rwy.replace('R', 'L')


def parse_canvas(html):
    parse_expression = r'<div id="(.+?)" class="SanSerif12".+?left: (.+?)px; top: (.+?)px.*\1<br>(\d{3}).(\d{2})'
    for match in re.findall(parse_expression, html):
        callsign = match[0]
        # Iterate through each plane to find the matching callsign and then append the values of x, y and alt
        # Quite inefficient but it works because there are only around 10 - 20 planes tops
        # Might update indexing later to make this prettier
        for category in plane_states:
            for plane in category:
                if plane[0] == callsign:
                    plane.append(int(match[1]) + 25)
                    plane.append(950 - int(match[2]))
                    plane.append(int(match[3]) * 100)
                    plane.append(int(match[4]))


def calculate_heading(pos1, pos2):
    dx = pos2[0] - pos1[0]
    dy = pos2[1] - pos1[1]

    initial_hdg = math.degrees(math.atan2(dx, dy))
    if initial_hdg < 0:
        initial_hdg += 360

    return round(initial_hdg)


def calculate_sqr_distance(pos1, pos2):
    dx = pos2[0] - pos1[0]
    dy = pos2[1] - pos1[1]

    sqr_d = (dx ** 2) + (dy ** 2)
    return sqr_d


def get_command_list():
    command_list = []

    # First find if it is safe for a plane to takeoff
    # Values of min & max height for TO and Landing aircraft can be changed later

    # Index 0 is Left Rwy, Index 1 is Right Rwy
    safe_runways = [True, True]
    for departure in plane_states[DEPARTURE]:
        if departure[5] <= 13:
            safe_runways = [False, False]

    for approaching in plane_states[APPROACHING]:
        if approaching[4] < 800:
            if 'L' in approaching[1]:
                safe_runways[0] = False
            elif 'R' in approaching[1]:
                safe_runways[1] = False

    for rto in plane_states[TAKEOFF_QUEUE]:
        if 'L' in rto[1] and safe_runways[0]:
            callsign = rto[0]
            if not callsign in taking_off:
                destination = rto[2]
                command_list.append(
                    '{} C {} C 11 T'.format(callsign, destination))
                taking_off.append(callsign)

            safe_runways[0] = False
        elif 'R' in rto[1] and safe_runways[1]:
            callsign = rto[0]
            if not callsign in taking_off:
                destination = rto[2]
                command_list.append(
                    '{} C {} C 11 T'.format(callsign, destination))
                taking_off.append(callsign)

            safe_runways[1] = False

    # Calculate headings for each plane on the approaching list
    for arrival in plane_states[ARRIVAL]:
        callsign = arrival[0]
        plane_heading = int(arrival[1])
        plane_pos = (arrival[2], arrival[3])

        if plane_pos[1] < 500:
            if landing_rwy == '9':
                target_points = TARGET_POINTS_09_S
                intercept_hdg = 60
            else:
                target_points = TARGET_POINTS_27_S
                intercept_hdg = 300
        else:
            if landing_rwy == '9':
                target_points = TARGET_POINTS_09_N
                intercept_hdg = 120
            else:
                target_points = TARGET_POINTS_27_N
                intercept_hdg = 240

        if not callsign in arrival_states:
            if landing_rwy == '27':
                if plane_pos[1] > 200 and plane_pos[1] < 800 and plane_pos[0] > 1350:
                    arrival_states[callsign] = 1
                    command_list.append('{} C 3 EX'.format(callsign))
                else:
                    arrival_states[callsign] = 0
                    command_list.append('{} C 4'.format(callsign))
            else:
                if plane_pos[1] > 200 and plane_pos[1] < 800 and plane_pos[0] < 350:
                    arrival_states[callsign] = 1
                    command_list.append('{} C 3 EX'.format(callsign))
                else:
                    arrival_states[callsign] = 0
                    command_list.append('{} C 4'.format(callsign))

        elif arrival_states[callsign] == len(target_points):
            command_list.append('{} L {}'.format(callsign, target_rwy))
            continue

        target_point = target_points[arrival_states[callsign]]

        # Check if the plane is near the target point
        if calculate_sqr_distance(plane_pos, target_point) < 1000:
            arrival_states[callsign] += 1

            command_list.append('{} C {}'.format(
                callsign, 4 - arrival_states[callsign]))
            # Check if the plane is at the last point
            if arrival_states[callsign] == len(target_points):
                hdg_str = str(intercept_hdg)
                if len(hdg_str) < 3:
                    hdg_str = '0' + hdg_str
                
                command_list.append('{} C {}'.format(callsign, hdg_str))
                command_list.append('{} L {}'.format(callsign, target_rwy))

        target_heading = calculate_heading(plane_pos, target_point)

        if abs(target_heading - plane_heading) > 5:
            hdg_str = str(target_heading)
            while len(hdg_str) < 3:
                hdg_str = '0' + hdg_str

            command_list.append('{} C {}'.format(arrival[0], hdg_str))

    return command_list


def execute_commands(commands):
    for command in commands:
        print("Executing command:", command)
        command_input.send_keys(command)
        command_input.send_keys(Keys.ENTER)


if __name__ == '__main__':
    # Start up chrome and open the website
    driver = Firefox()
    driver.maximize_window()
    driver.get('http://atc-sim.com/')

    # Change the airport and start the game
    driver.find_element(by=By.XPATH,
                        value='/html/body/div[4]/div[1]/form/table/tbody/tr/td[1]/div[1]/select/option[4]').click()
    '''driver.find_element(by=By.XPATH,
                        value='//*[@id="frmOptions"]/table/tbody/tr/td[1]/div[7]/select/option[4]').click()'''
    driver.find_element(by=By.XPATH,
                        value='//*[@id="frmOptions"]/table/tbody/tr/td[1]/input[1]').click()
    time.sleep(1)

    failed = True
    while failed:
        try:
            driver.find_element(
                by=By.XPATH, value='//*[@id="btnclose"]').click()
            failed = False
        except ElementNotInteractableException:
            time.sleep(1)

    wind_dir = int(driver.find_element(by=By.XPATH,
                                       value='/html/body/div[1]/div/div[9]/div[1]').get_attribute('innerHTML').split('<br>')[1].replace('°', ''))

    # Check if the landing runway is 09 or 27
    if abs(90 - wind_dir) < abs(270 - wind_dir):
        # Hardcoded but I will change this later
        landing_rwy = '9'
        target_rwy = '9L'
    else:
        # Hardcoded but I will change this later
        landing_rwy = '27'
        target_rwy = '27R'

    command_input = driver.find_element(by=By.XPATH,
                                        value='//*[@id="canvas"]/div[1]/div/form/input[1]')

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
