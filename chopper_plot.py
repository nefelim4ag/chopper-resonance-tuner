#!/usr/bin/env python3
####################################
###### CHOPPER REGISTERS TUNE ######
####################################
# Written by @altzbox @mrx8024
# @version: 1.2

# CHANGELOG:
#   v1.0: first version of the script, data sort, collection, graph generation
#   v1.1: add support any accelerometers, find vibr mode, smart work area, auto-install,
#   auto-import export, out nametags(acc+drv+sr+date), cleaner data
#   v1.2: rethinking motion calculation & measurements

# These changes describe the operation of the entire system, not a specific file.

import os
#################################################################################################################
RESULTS_FOLDER = os.path.expanduser('~/printer_data/config/adxl_results/chopper_magnitude')
DATA_FOLDER = '/tmp'
#################################################################################################################

import sys
import csv
import json
import numpy as np
import plotly.graph_objects as go
import plotly.io as pio
import time
from datetime import datetime
import serial

FCLK = 12                   # System clock frequency MHz
CUTOFF_RANGE = 5            # Data trim size
DELAY = 1.00                # Delay between checks csv in tmp in sec
OPEN_DELAY = 0.25           # Delay between open csv in sec
TIMER = 10.0                # Exit program time in sec
SAVE_RESULT_IN_CSV = False


def cleaner():
    os.system('rm -f /tmp/*.csv')


def check_export_path(path):
    if not os.path.exists(path):
        try:
            os.makedirs(path)
        except OSError as e:
            print(f'Error generate path {path}: {e}')


def parse_arguments():
    args = sys.argv[1:]
    parsed_args = {}
    for arg in args:
        name, value = arg.split('=')
        parsed_args[name] = int(value) if value.isdigit() else value
    return parsed_args


def calculate_static_measures(file_path):
    with open(file_path, 'r') as file:
        static = np.array([[float(row["accel_x"]),
                            float(row["accel_y"]),
                            float(row["accel_z"])] for row in csv.DictReader(file)])
        return static.mean(axis=0)

def klippy_write(msg):
    klippy = serial.Serial(os.path.expanduser('~/printer_data/comms/klippy.serial'), 115200)
    klippy.write(msg)

def dir_listener(path):
    timer = 0
    while True:
        time.sleep(DELAY)
        if timer / DELAY > 2:
            print(f'Wait new file {round(timer * DELAY)} sec')
        timer += 1

        for f in os.listdir(path):
            if not f.endswith(".csv"):
                continue
            timer = 0
            file_path = os.path.join(path, f)
            if f.endswith('chopper-end.csv'):
                os.remove(file_path)
                print('Last csv received, launching plotter')
                return None

            yield file_path

        if timer >= TIMER / DELAY:
            print('TIMER OUT')
            klippy_write(f'RESPOND TYPE=error MSG="WARNING!!! TIMER OUT" \n'.encode('utf-8'))
            raise

def main(database_dir):
    print('Start tracking')
    current_date = datetime.now().strftime('%Y%m%d_%H%M%S')
    results = {}
    accelerometer = ""
    driver = ""
    rsense = 0
    database_path = ""
    for file_path in dir_listener(DATA_FOLDER):
        if file_path.endswith('stand_still.csv'):
            time.sleep(OPEN_DELAY)
            static = calculate_static_measures(file_path)
            print('Calculated static measures')
            os.remove(file_path)
            continue

        if file_path.endswith('.csv'):
            time.sleep(OPEN_DELAY)
            print(f'Receiving csv: {file_path}')
            file_name = os.path.splitext(os.path.basename(file_path))[0]
            params = {}
            for item in file_name.split('-'):
                if '_' in item:
                    key = item.split('_')[0]
                    value_raw = item.split('_')[1]
                    value = value_raw.replace('dot', '.').replace('minus', '-')
                    params[key] = value

            # overwrited "global" in each loop =(
            accelerometer = params["chip"]
            driver = params["driver"]
            rsense = round(float(params["rsense"]), 3)

            current = float(params["current"])
            tbl = int(params["tbl"])
            toff = int(params["toff"])
            hstrt = int(params["hstrt"])
            hend = int(params["hend"])
            speed = float(params["speed"])
            tpfd = int(params["tpfd"])


            freq = float(round(1/(2*(12+32*toff)*1/(1000000*FCLK)+2*1/(1000000*FCLK)*16*(1.5**tbl))/1000, 1))
            params["freq"] = freq

            parameters = (f'current={current} tbl={tbl} toff={toff} hstrt={hstrt} '
                            f'hend={hend} tpfd={tpfd} speed={speed} freq={freq}kHz')

            with open(file_path, 'r') as csv_file:
                data = np.array([[float(row["accel_x"]),
                                    float(row["accel_y"]),
                                    float(row["accel_z"])] for row in csv.DictReader(csv_file)]) - static

                trim_size = len(data) // CUTOFF_RANGE
                data = data[trim_size:-trim_size]
                md_magnitude = np.median([np.linalg.norm(row) for row in data])
                if results.get(parameters) is None:
                    results[parameters] = {'datapoints': [md_magnitude], 'color': toff}
                else:
                    # This is other iteration
                    datapoints = results[parameters]['datapoints']
                    datapoints.append(md_magnitude)
                    results[parameters]['datapoints'] = datapoints

            database_path = os.path.join(database_dir, f".{accelerometer}-{driver}-{rsense}.db")
            with open(database_path, mode="a+") as fd:
                record = {
                    "parameters": parameters,
                    "datapoints": results[parameters]["datapoints"],
                    "color": toff
                }
                fd.write(json.dumps(record) + '\n')
                os.remove(file_path)

    # Group result in csv
    # if SAVE_RESULT_IN_CSV:
    #     results_csv_path = os.path.join(RESULTS_FOLDER,f'median_magnitudes_{accelerometer}_tmc{driver}_{rsense}_{current_date}.csv')
    #     with open(results_csv_path, 'w', newline='') as csvfile:
    #         writer = csv.DictWriter(csvfile, fieldnames=['median magnitude', 'parameters'])
    #         writer.writeheader()
    #         for result in results:
    #             writer.writerow({key: value for key, value in result.items() if key != 'color'})

    # Graphs generation
    del results
    results = {}
    print(f'Load persistent database: {database_path}')
    klippy_write(f'Load persistent database: {database_path} \r\n'.encode('utf-8'))
    with open(database_path, mode="r") as fd:
        for record_json in fd.readlines():
            record = json.loads(record_json)
            parameters = record["parameters"]
            # Replace duplicated/updated data by new record
            results[parameters] = record

    print('Magnitude graphs generation...')
    klippy_write(f'M118 Magnitude graphs generation... \r\n'.encode('utf-8'))
    colors = ['', '#2F4F4F', '#12B57F', '#9DB512', '#DF8816', '#1297B5', '#5912B5', '#B51284', '#127D0C']

    result_list = []
    for parameters in results:
        datapoints = results[parameters]["datapoints"]
        result_list.append({'parameters': parameters, 'median magnitude': np.mean(datapoints), 'color': toff})

    graphs = {
        'interactive': result_list,
        'interactive_sorted': sorted(result_list, key=lambda x: x['median magnitude'])
    }
    for name in graphs:
        fig = go.Figure()
        for entry in graphs[name]:
            marker_color =  colors[entry['color'] % 9]
            mean_magnitude = entry['median magnitude']
            chopper = entry['parameters']
            fig.add_trace(go.Bar(x=[mean_magnitude],
                                 y=[chopper],
                                 marker_color=marker_color,
                                 orientation='h',
                                 showlegend=False))
        fig.update_layout(title='Median Magnitude vs Parameters', xaxis_title='Median Magnitude',
                          yaxis_title='Parameters', coloraxis_showscale=True)
        plot_html_path = os.path.join(RESULTS_FOLDER, f'{name}_{accelerometer}_tmc{driver}_{rsense}_{current_date}.html')
        pio.write_html(fig, plot_html_path, auto_open=False)
        print(f'Access to interactive plot at: {plot_html_path}')
        klippy_write(f'M118 Access to interactive plot at: {plot_html_path} \r\n'.encode('utf-8'))


if __name__ == '__main__':
    own_dir = os.path.dirname(sys.argv[0])
    try:
        check_export_path(RESULTS_FOLDER)
        main(own_dir)
    except Exception as e:
        klippy_write('RESPOND TYPE=error MSG="WARNING!!! FATAL ERROR IN PLOTTER" \n'.encode('utf-8'))
        raise e
