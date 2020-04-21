import subprocess
import os
import json
import docker
import shutil
from pathlib import Path
from bayes_opt import BayesianOptimization
from bayes_opt.logger import JSONLogger
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
        #"globalInhibition": True, always true (set in detector) as swarm cannot work with bool
        "localAreaDensity": 0.025,  # optimize this one
        "stimulusThreshold": 2,
        "synPermInactiveDec": 0.001,
        "synPermActiveInc": 0.006,
        "synPermConnected": 0.5,  # this shouldn't make any effect, keep as intended by Connections
        "boostStrength": 0.0,  # so far, boosting negatively affects results. Suggest leaving OFF (0.0)
        #"wrapAround": True, always true (set in detector) as swarm cannot work with bool
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
        "permanenceIncrement": 0.04,
        "permanenceDecrement": 0.008,
        "predictedSegmentDecrement": 0.001,
        "maxSegmentsPerCell": 128,
        "maxSynapsesPerSegment": 128,
        "seed": 5,
    },
    "anomaly": {
        "likelihood": {
            "probationaryPct": 0.1,
            "reestimationPeriod": 100
        }
    }
}


def target_func(localAreaDensity):
    # get params
    my_params = default_parameters
    my_params['sp']['localAreaDensity'] = localAreaDensity

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
    container.wait()

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


def optimize_local_area_density():
    # define bounds for the params you want to optimize. Can be multivariate. Check https://github.com/fmfn/BayesianOptimization on how to
    bounds = {
        'localAreaDensity': (0.01, 0.15),
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
    logger = JSONLogger(path="./local_area_density_optimization_logs.json")
    optimizer.subscribe(Events.OPTIMIZATION_STEP, logger)

    # If you want to guide the optimization process
    val = 0.02
    while val <= 0.04:
        print('Adding', val)
        optimizer.probe(
            params={
                'localAreaDensity': val,
            },
            lazy=True,
        )
        val = round(val + 0.001, 3)

    print('Starting optimization...')

    optimizer.maximize(
        init_points=20,
        n_iter=50,
    )

    print(optimizer.max)


if __name__ == "__main__":
    optimize_local_area_density()
