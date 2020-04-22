"""
This file implements parameter optimization of the htm.core detector on NAB using Bayesian Optimization.
To run this script, you need to install the bayesian-optimization python module with pip install bayesian-optimization.
Then, build the Dockerfile provided in the root of this repo using docker build -t optimize-htmcore-nab:latest . -f htmcore.Dockerfile
Finally, run this script with python optimize_bayesopt.py
Check https://github.com/fmfn/BayesianOptimization for details on how to use the bayesian optimization module.
"""

import subprocess
import os
import json
import docker
import shutil
from pathlib import Path
from bayes_opt import BayesianOptimization
from bayes_opt.logger import JSONLogger, ScreenLogger
from bayes_opt.event import Events
from bayes_opt.util import load_logs


default_parameters = {
    "enc": {
        "value": {
            # "resolution": 0.9, calculate by max(0.001, (maxVal - minVal) / numBuckets) where numBuckets = 130
            "size": 400,
            "activeBits": 21,  # results very sensitive to the size/active bits in the input encoders
            "seed": 5,
        },
        "time": {
            "timeOfDay": (21, 9.49),
        }
    },
    "sp": {
        # inputDimensions: use width of encoding
        "columnDimensions": 2048,
        # "potentialRadius": use width of encoding
        "potentialPct": 0.8,
        #"globalInhibition": True,
        #"localAreaDensity": 0.025,  ## MUTEX #0.025049634479368352,  # optimize
        "numActiveColumnsPerInhArea": 0,  ##MUTEX
        "stimulusThreshold": 0,
        "synPermInactiveDec": 0.0005,
        "synPermActiveInc": 0.003,
        "synPermConnected": 0.2,  # this shouldn't make any effect, keep as intended by Connections
        "boostStrength": 0.0,  # so far, boosting negatively affects results. Suggest leaving OFF (0.0)
        #"wrapAround": True,
        "minPctOverlapDutyCycle": 0.001,
        "dutyCyclePeriod": 1000,
        "seed": 5,
    },
    "tm": {
        # "columnDimensions": 2048, #must match SP
        "cellsPerColumn": 32,
        "activationThreshold": 20,
        "initialPermanence": 0.24,
        "connectedPermanence": 0.5,
        "minThreshold": 13,
        "maxNewSynapseCount": 31,
        #"permanenceIncrement": 0.04, optimize
        "permanenceDecrement": 0.008,
        "predictedSegmentDecrement": 0.001,
        "maxSegmentsPerCell": 128,
        "maxSynapsesPerSegment": 128,
        "seed": 5,
    },
    "spatial_tolerance": 0.05,
    "anomaly": {
        "likelihood": {
            "probationaryPct": 0.1,
            "reestimationPeriod": 100
        }
    }
}


def target_func(localAreaDensity, permanenceIncrement):
    # get params
    my_params = default_parameters
    my_params['sp']['localAreaDensity'] = localAreaDensity
    my_params['tm']['permanenceIncrement'] = permanenceIncrement

    # get client
    client = docker.from_env()

    # create container
    container = client.containers.create(image='optimize-htmcore-nab:latest')

    # make dir for container
    Path(os.path.join('temp', container.id)).mkdir(parents=True, exist_ok=True)

    # write params to json in that dir
    with open(os.path.join('temp', container.id, 'params.json'), 'w') as outfile:
        json.dump(my_params, outfile)

    # copy file to container
    cmd = 'docker cp ./temp/' + container.id + '/params.json ' + container.id + ':NAB/nab/detectors/htmcore/params.json'
    subprocess.check_call(cmd, shell=True)

    # start container
    container.start()
    res = container.wait()
    if res.get('StatusCode') != 0:
        raise Exception('Something went wrong. Check the logs of container ' + container.id + ' (' + container.name + ') ' + 'for troubleshooting.')

    # copy results file into temp directory with container id in path
    cmd = 'docker cp ' + container.id + ':NAB/results/final_results.json ./temp/' + container.id + '/final_results.json'
    subprocess.check_call(cmd, shell=True)

    # read and return score from results file
    with open(os.path.join('temp', container.id, 'final_results.json')) as json_file:
        results = json.load(json_file)
        score = results.get('htmcore').get('standard')

    # remove container
    container.remove()

    # remove temp dir
    shutil.rmtree(os.path.join('temp', container.id))

    return score


def optimize():
    # define bounds for the params you want to optimize. Can be multivariate. Check https://github.com/fmfn/BayesianOptimization on how to
    bounds = {
        'localAreaDensity': (0.01, 0.15),
        'permanenceIncrement': (0.01, 0.1),
    }

    optimizer = BayesianOptimization(
        f=target_func,
        pbounds=bounds,
        random_state=1,
    )

    # We can start from saved logs
    if os.path.isfile('./local_area_density_optimization_logs_base.json'):
        print('Loading Logs...')
        load_logs(optimizer, logs=["./local_area_density_optimization_logs_base.json"]);

    # The new log file to write to
    json_logger = JSONLogger(path="./local_area_density_optimization_logs.json")
    optimizer.subscribe(Events.OPTIMIZATION_STEP, json_logger)

    # Additionally log to console
    screen_logger = ScreenLogger()
    optimizer.subscribe(Events.OPTIMIZATION_STEP, screen_logger)

    # If you want to guide the optimization process
    val = 0.02
    while val <= 0.04:
        optimizer.probe(
            params={
                'localAreaDensity': val,
                'permanenceIncrement': 0.04,
            },
            lazy=True,
        )
        val = round(val + 0.001, 3)

    optimizer.maximize(
        init_points=20,
        n_iter=50,
    )

    print(optimizer.max)

    # cleanup temp dir
    shutil.rmtree(os.path.join('temp'))


if __name__ == "__main__":
    optimize()
