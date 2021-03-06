##########################################################################
# Random Hacks of Kindness - 2018 April 13-15
# Project #1 - Growing Futures Hydroponic Monitoring System
# https://rhok.ca/events/rhok-8/
#
# This code is used to read data from an arduino, clean it up a bit and then
# put it in a database.
#
# Currently all our code is in one file for easy of updating. In the future
# it would be nice to have this split over separate files.
#
##########################################################################
# Requirements:
# -python 3
# -library: pySerial - http://pyserial.readthedocs.io
# -library: InfluxDBClient - https://pypi.python.org/pypi/influxdb
# -correct system time (for light's status)
#
##########################################################################
# Usage:
# Run the script. This can be used to change the configuration data and/or
# loop on the sensor data.
# >>> python3 rhok.py
#
# Used to skip the setup.
# >>> python3 rhok.py --skip_setup
#
##########################################################################
# Notes:
# If a json dictionary key string is changed in the configuration file, the
# string also needs to be changed in this file.
#
# Example configuration file entry:
# "tags" : {
#     "towerName" : "Tower_60",
#     "towerGroup" : "Tower 60 Postal Office"
# }
#
# If a string key name ("tags", "towerName", or "towerGroup") is changed in
# the configuration file, its corresponding value in this file needs to be
# updated.
#
# TAGS = 'tags'
# T_TOWER_NAME = "towerName"
# T_TOWER_GROUP = "towerGroup"
#
# If a value is changed (eg. from above: "Tower_60" or
# "Tower 60 Postal Office"), that does not need to be reflected in this file.
#
##########################################################################
# Example of the data format that is written to influxdb.
# [{
#       "measurement" : "TowerData",
#
#       "tags" : {
#           "towerName" : "Tower_60",
#           "towerGroup" : "Tower 60 Postal Office"
#       },
#
#       "fields" : {
#           "water_level" : 80.5,
#           "air_humidity" : 44.4,
#           "air_temp" : 25.2,
#           "water_temp" : 22.9,
#           "pH" : 7.0,
#           "light_status_1" : 1.0,
#           "light_status_2" : 1.0,
#           "light_status_3" : 1.0,
#           "light_status_4" : 1.0
#       }
# }]
##########################################################################


from datetime import datetime, time
from enum import Enum, unique
from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError
import json
import serial  # For communication with arduino.
import sys


# This is our default config file. Don't write to this. Read only.
DFLT_CONFIG_FILENAME = 'default_config.json'
CONFIG_FILENAME = 'config.json'


# Use this cmd on the raspberry pi to get the dev name of the arduino. There
# will be a bunch of tty devices. It is usually something like ttyACM0
# or ttypUSB0. The last number is dependant on the usb port being used.
# >>> ls /dev/tty*
SERIAL_PORT = '/dev/ttyACM1'
#SERIAL_PORT = '/dev/ttyACM0'
#SERIAL_PORT = '/dev/ttyUSB0'


# Most of the following consts are based on the strings in the config.json
# file.
MEASUREMENT = 'measurement'


TAGS = 'tags'
T_TOWER_NAME = "towerName"
T_TOWER_GROUP = "towerGroup"

TAGS_ORDER = (
        T_TOWER_NAME,
        T_TOWER_GROUP,
)


DB = 'db'
DB_HOST_NAME = "host_name"
DB_HOST_PORT = "host_port"
DB_DBNAME = "dbname"
DB_USERNAME = "username"

DB_ORDER = (
        DB_HOST_NAME,
        DB_HOST_PORT,
        DB_DBNAME,
        DB_USERNAME,
)


ARDUINO = 'arduino'
A_BAUD_RATE = 'baud_rate'


WATER_LEVEL = 'water_level'
WL_SENSOR_HEIGHT = "sensor_height"
WL_MAX = "max_water_level"
WL_MIN = "min_water_level"

WATER_LEVEL_ORDER = (
        WL_SENSOR_HEIGHT,
        WL_MAX,
        WL_MIN,
)

LIGHT_SENSOR = 'light_sensor'
LS_EXPECTED_START_ON_HOUR = 'expected_start_on_hour'
LS_EXPECTED_START_ON_MIN = "expected_start_on_min"
LS_EXPECTED_START_OFF_HOUR = "expected_start_off_hour"
LS_EXPECTED_START_OFF_MIN = "expected_start_off_min"

LIGHT_SENSOR_ORDER = (
        LS_EXPECTED_START_ON_HOUR,
        LS_EXPECTED_START_ON_MIN,
        LS_EXPECTED_START_OFF_HOUR,
        LS_EXPECTED_START_OFF_MIN,
)

# Used with the light sensor code.
ARDUINO_LIGHT_ON = 1
ARDUINO_INVALID_DATA = 'x'

# Used to validate light sensor hour/minute values.
MIN_HOUR = 0
MAX_HOUR = 23
MIN_MINUTE = 0
MAX_MINUTE = 59


CONFIG_KEYS = (MEASUREMENT, TAGS, DB, ARDUINO, WATER_LEVEL, LIGHT_SENSOR)
SETUP_KEYS = (TAGS, DB, WATER_LEVEL, LIGHT_SENSOR)

# This is used to keep the setup order consistant over each setup.
SETUP_KEYS_ORDER_DICT = {
        TAGS : TAGS_ORDER,
        DB : DB_ORDER,
        WATER_LEVEL : WATER_LEVEL_ORDER,
        LIGHT_SENSOR : LIGHT_SENSOR_ORDER,
}


FIELDS = 'fields'
F_WATER_LEVEL = "water_level"
F_AIR_HUMIDITY = "air_humidity"
F_AIR_TEMP = "air_temp"
F_WATER_TEMP = "water_temp"
F_PH = "pH"
F_LIGHT_STATUS_1 = "light_status_1"
F_LIGHT_STATUS_2 = "light_status_2"
F_LIGHT_STATUS_3 = "light_status_3"
F_LIGHT_STATUS_4 = "light_status_4"


# Required as the arduino sends us the data in this order.
FIELD_ORDER = (
        F_WATER_LEVEL,
        F_AIR_HUMIDITY,
        F_AIR_TEMP,
        F_WATER_TEMP,
        F_PH,
        F_LIGHT_STATUS_1,
        F_LIGHT_STATUS_2,
        F_LIGHT_STATUS_3,
        F_LIGHT_STATUS_4,
)

FIELDS_LEN = len(FIELD_ORDER)


@unique
class LightStatus(Enum):
    on  = 1
    off = 2
    on_expected  = 3  # light is off, but it should be on
    off_expected = 4  # light is on, but it should be off


# Ref: https://stackoverflow.com/a/10748024
def time_in_range(start, end, in_time):
    """Return True if in_time is in the range [start, end]"""
    if start <= end:
        return start <= in_time <= end
    else:
        return start <= in_time or in_time <= end


def to_float(s):
    try:
        return float(s)
    except ValueError:
        # Re-raise the exception, to be caught by users of this function.
        raise e


def to_int(s):
    try:
        return int(s)
    except ValueError:
        # Re-raise the exception, to be caught by users of this function.
        raise e


def to_str(s): return s


def create_to_light_status(config_data):
    ls_config = config_data[LIGHT_SENSOR]
    start_time = time(ls_config[LS_EXPECTED_START_ON_HOUR],
            ls_config[LS_EXPECTED_START_ON_MIN], 0)
    end_time = time(ls_config[LS_EXPECTED_START_OFF_HOUR],
            ls_config[LS_EXPECTED_START_OFF_MIN], 0)

    def to_light_status(sensor_value, start_time=start_time,
            end_time=end_time):
        """Used to convert light sensor data to light status."""
        sensor_value = to_int(sensor_value)
        if time_in_range(start_time, end_time, datetime.time(datetime.now())):
            if ARDUINO_LIGHT_ON == sensor_value:
                status = LightStatus.on
            else:
                status =  LightStatus.off
        else:
            if ARDUINO_LIGHT_ON == sensor_value:
                status = LightStatus.off_expected
            else:
                status =  LightStatus.on_expected
        return float(status.value)
    return to_light_status


def create_to_water_level(config_data):
    """Used to create the 'to_water_level' func."""
    wl_config = config_data[WATER_LEVEL]
    height = wl_config[WL_SENSOR_HEIGHT]
    wl_max = wl_config[WL_MAX]
    wl_min = wl_config[WL_MIN]
    wl_diff = wl_max - wl_min

    def to_water_level(sensor_value, height=height, wl_min=wl_min,
            wl_diff=wl_diff):
        return ((height - to_float(sensor_value) - wl_min) / wl_diff) * 100
    return to_water_level


def to_dict(config_data, field_dict, sensor_data):
    """Used to convert the sensor data into a dict for easy conversion to
    json format.
    """
    # TODO - have dict already created, only need to populate with new sensor
    # data
    d = {}

    # Measurement data.
    d[MEASUREMENT] = config_data[MEASUREMENT]
    d[TAGS] = dict(config_data[TAGS])

    fields = {}

    for e, field in enumerate(FIELD_ORDER):
        # We ignore 'x' fields. The arduino is sending 4 light statuses even
        # if they only have 1 light. We filter out any that don't have data.
        convert_func = field_dict.get(field, to_str)
        data = sensor_data[e]
        if ARDUINO_INVALID_DATA == data: continue

        try:
            fields[field] = convert_func(data)
        except ValueError as e:
            # Skip this field/data. This is most likely caused by a sensor
            # value not being as expected (ie. to_int or to_float)
            print('Exception: {}'.format(e))
            continue

    d[FIELDS] = fields
    return d


def check_config_data_keys_sanity(config_data):
    """Does very basic sanity on the config data keys."""
    for key in CONFIG_KEYS:
        if key not in config_data:
            print('ERROR: Missing config file key "{}"'.format(key))
            return False
    return True


def get_config_data(filename):
    """Used to read the json config data."""
    try:
        with open(filename) as fp:
            config_data = json.load(fp)
    except OSError as e:
        print('Exception: {}'.format(e))
        print('ERROR: Unable to read config file: {}'.format(filename))
        return {}

    if check_config_data_keys_sanity(config_data): return config_data
    else: return {}


def update_config_data(filename, config_data):
    """Used to overwrite the json config data."""
    if not check_config_data_keys_sanity(config_data):
        print('ERROR: Invalid config data={}, config file not updated'.format(
            config_data))
        return False

    try:
        with open(filename, 'w') as fp:
            json.dump(config_data, fp, indent=4)
            #print(json.dumps(config_data))
    except OSError as e:
        print('Exception: {}'.format(e))
        print('ERROR: Unable to write config file: {}'.format(filename))
        return False
    return True


def create_sensor_field_dict(config_data):
    return {
            F_WATER_LEVEL : create_to_water_level(config_data),
            F_AIR_HUMIDITY : to_float,
            F_AIR_TEMP : to_float,
            F_WATER_TEMP : to_float,
            F_PH : to_float,
            F_LIGHT_STATUS_1 : create_to_light_status(config_data),
            F_LIGHT_STATUS_2 : create_to_light_status(config_data),
            F_LIGHT_STATUS_3 : create_to_light_status(config_data),
            F_LIGHT_STATUS_4 : create_to_light_status(config_data),
    }


def config_adruino_serial_port(config_data):
    try:
        return serial.Serial(SERIAL_PORT, config_data[ARDUINO][A_BAUD_RATE])
    except serial.SerialException as e:
        print('Exception: {}'.format(e))
        print('ERROR: Unable to configure adruino serial port: {}'.format(
            SERIAL_PORT))
        return None


def config_db_client(config_data):
    try:
        # TODO - remove password
        db = config_data[DB]
        client = InfluxDBClient(host=db[DB_HOST_NAME], port=db[DB_HOST_PORT],
                username=db[DB_USERNAME], password='rhokmonitoring', ssl=True,
                verify_ssl=True)
        client.switch_database(db[DB_DBNAME])
        return client
    except InfluxDBClientError as e:
        print('Exception: {}'.format(e))
        print('ERROR: Unable to configure influx db client: host={}, port={}, '
            'username={}'.format(
                db[DB_HOST_NAME], db[DB_HOST_PORT], db[DB_USERNAME]))
        return None


#
# Functions to manage setup.
#
#
def is_value_in_range(value, min_v, max_v):
    """Checks value in range [min_v, max_v]."""
    return min_v <= value <= max_v


def check_hour_value(value):
    if not is_value_in_range(value, MIN_HOUR, MAX_HOUR):
        print('Invalid hour (range: {}-{})'.format(MIN_HOUR, MAX_HOUR))
        return False
    return True


def check_minute_value(value):
    if not is_value_in_range(value, MIN_MINUTE, MAX_MINUTE):
        print('Invalid minute (range: {}-{})'.format(MIN_MINUTE, MAX_MINUTE))
        return False
    return True


def validate_cmd_data(cmd_line_input, data, data_key):
    expected_data_type = type(data)
    value = None
    cmd_line_input = cmd_line_input.strip()

    if cmd_line_input:
        if str != expected_data_type:
            try:
                value = expected_data_type(cmd_line_input)
            except ValueError:
                # Try again.
                print('Invalid input (hint: {})'.format(
                    expected_data_type.__name__))

            if value is not None:
                # Do some extra validation on some of the data. If the check
                # fails set the value to None and try again.
                if (LS_EXPECTED_START_ON_HOUR == data_key or
                        LS_EXPECTED_START_OFF_HOUR == data_key):
                    if not check_hour_value(value): value = None
                if (LS_EXPECTED_START_ON_MIN == data_key or
                        LS_EXPECTED_START_OFF_MIN == data_key):
                    if not check_minute_value(value): value = None
        else:
            value = cmd_line_input
    else:
        # Empty string means keep things as they are.
        value = data

    return value


def display_config_summary_change(config_data, changed_config):
    if changed_config:
        print('\nSummary of configuration changes:')
        for key in SETUP_KEYS:
            if key in changed_config:
                for data_key in SETUP_KEYS_ORDER_DICT[key]:
                    if data_key in changed_config[key]:
                        print("    '{}':'{}' = {} (old={})".format(
                            key, data_key, config_data[key][data_key],
                            changed_config[key][data_key]))


def is_yes_reply(cmd_line_input):
    return 'y' == cmd_line_input.lower()


def setup():
    """Function to assist the user in configuring a device."""
    config_data = get_config_data(CONFIG_FILENAME)
    #print(config_data)
    prompt = "Update configuration data for '{}' entries (y/Y): "
    data_prompt = "'{}' = {}: "
    help_str = "Input new value or press 'enter' to keep current value."

    # TODO - have a way to allow the user to revert to the dflt config file.
    changed_config = {}

    for key in SETUP_KEYS:
        print()
        cmd_line_input = input(prompt.format(key))

        if is_yes_reply(cmd_line_input):
            for data_key in SETUP_KEYS_ORDER_DICT[key]:
                print(help_str)
                data = config_data[key][data_key]
                value = None

                while value is None:
                    value = validate_cmd_data(
                            input(data_prompt.format(data_key, data)), data,
                            data_key)

                # Only update if it has changed.
                if value != data:
                    config_data[key][data_key] = value
                    changed_config.setdefault(key, {})[data_key] = data

    #print(config_data)
    if changed_config:
        display_config_summary_change(config_data, changed_config)
        cmd_line_input = input('\nSave configuration changes? (y/Y): ')

        if is_yes_reply(cmd_line_input):
            saved = update_config_data(CONFIG_FILENAME, config_data)
            if saved: print('Configuration changes SAVED.')
        else:
            print('Configuration changes ABORTED.')
    else:
        print('Configuration unchanged.')


def sensor_loop():
    """Does some initial config then loops forever reading the sensor data."""
    config_data = get_config_data(CONFIG_FILENAME)
    #print(config_data)
    if not config_data: return

    field_dict = create_sensor_field_dict(config_data)

    ser_adruino = config_adruino_serial_port(config_data)
    if ser_adruino is None: return

    db_client = config_db_client(config_data)
    if db_client is None: return

    while True:
        try:
            sensor_data = ser_adruino.readline()
        except serial.SerialException as e:
            # One reason this can occur is when the rpi is disconnected from
            # the arduino.
            print('Exception: {}'.format(e))
            print('ERROR: Unable to read adruino serial port')
            break

        # Convert byte array to a string. Common separated values.
        sensor_data = sensor_data.decode('utf-8').strip().split(',')
        #print(sensor_data)

        if len(sensor_data) != FIELDS_LEN:
            # This can happen once in while, especially during the first few
            # reads.
            print('WARNING: Sensor data length mismatch (ignoring sensor '
                    'data), received {} values, expecting {} values'.format(
                    len(sensor_data), sensor_fields_len))
            continue

        # Output to json.
        d = [to_dict(config_data, field_dict, sensor_data)]
        #print(json.dumps(d))

        try:
            if db_client.write_points(d):
                print('DB updated with data: {}'.format(d))
            else:
                print('Failed db client data write: {}'.format(d))
        except InfluxDBClientError as e:
            print('Exception: {}'.format(e))
            print('ERROR: Unable to write data to client db, data={}'.format(d))


def main(skip_setup):
    if not skip_setup:
        # Check to see if the user wants to enter config mode.
        prompt = "Do you want to enter configuration mode? (y/Y): "
        cmd_line_input = input(prompt)
        if is_yes_reply(cmd_line_input):
            setup()
    sensor_loop()


if '__main__' == __name__:
    # TODO - add proper args support, ie: argparse
    skip_setup = '--skip_setup' in sys.argv
    main(skip_setup)


