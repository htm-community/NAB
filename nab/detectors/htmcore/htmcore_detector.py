# ----------------------------------------------------------------------
# Copyright (C) 2014, Numenta, Inc.  Unless you have an agreement
# with Numenta, Inc., for a separate license for this software code, the
# following terms and conditions apply:
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU Affero Public License for more details.
#
# You should have received a copy of the GNU Affero Public License
# along with this program.  If not, see http://www.gnu.org/licenses.
#
# Copyright (C) 2019, @breznak
#
# http://numenta.org/licenses/
# ----------------------------------------------------------------------

import os
import json
import math

# htm.core imports
from htm.bindings.sdr import SDR, Metrics
from htm.encoders.rdse import RDSE, RDSE_Parameters
from htm.encoders.date import DateEncoder
from htm.bindings.algorithms import SpatialPooler
from htm.bindings.algorithms import TemporalMemory
from htm.algorithms.anomaly_likelihood import AnomalyLikelihood
from htm.bindings.algorithms import Predictor

from nab.detectors.base import AnomalyDetector

# Fraction outside of the range of values seen so far that will be considered
# a spatial anomaly regardless of the anomaly likelihood calculation. This
# accounts for the human labelling bias for spatial values larger than what
# has been seen so far.
SPATIAL_TOLERANCE = 0.05

PANDA_VIS_ENABLED = False # if we want to run pandaVis tool (repo at https://github.com/htm-community/HTMpandaVis )

if PANDA_VIS_ENABLED:
    from PandaVis.pandaComm.server import PandaServer
    from PandaVis.pandaComm.dataExchange import ServerData, dataHTMObject, dataLayer, dataInput

    pandaServer = PandaServer()

parameters_numenta_comparable = {
  # there are 2 (3) encoders: "value" (RDSE) & "time" (DateTime weekend, timeOfDay)
  'enc': {
    "value" : # RDSE for value
      {'resolution': 0.001,
        'size': 4000,
        'sparsity': 0.10
      },
    "time": {  # DateTime for timestamps
        'timeOfDay': (21, 9.49), 
        'weekend': 0 #21 TODO try impact of weekend
        }},
  'predictor': {'sdrc_alpha': 0.1},
  'sp': {
    'boostStrength': 0.0,
    'columnCount': 2048,
    'localAreaDensity': 40/2048,
    'potentialPct': 0.4,
    'synPermActiveInc': 0.003,
    'synPermConnected': 0.2,
    'synPermInactiveDec': 0.0005},
  'tm': {
    'activationThreshold': 13,
    'cellsPerColumn': 32,
    'initialPerm': 0.21,
    'maxSegmentsPerCell': 128,
    'maxSynapsesPerSegment': 32,
    'minThreshold': 10,
    'newSynapseCount': 20,
    'permanenceDec': 0.1,
    'permanenceInc': 0.1},
  'anomaly': {
    'likelihood': {
      #'learningPeriod': int(math.floor(self.probationaryPeriod / 2.0)),
      #'probationaryPeriod': self.probationaryPeriod-default_parameters["anomaly"]["likelihood"]["learningPeriod"],
      'probationaryPct': 0.1,
      'reestimationPeriod': 100}}
}


def get_params(filename):
  """Reads parameters from a json file

  @param filename is a string defining the name of the file to read

  @return dict of parameters
  """
  dirname = os.path.dirname(__file__)
  filename = os.path.join(dirname, filename)
  with open(filename) as json_file:
    params = json.load(json_file)
    return params


class HtmcoreDetector(AnomalyDetector):
  """
  This detector uses an HTM based anomaly detection technique.
  """

  def __init__(self, *args, **kwargs):

    super(HtmcoreDetector, self).__init__(*args, **kwargs)

    ## API for controlling settings of htm.core HTM detector:

    # Set this to False if you want to get results based on raw scores
    # without using AnomalyLikelihood. This will give worse results, but
    # useful for checking the efficacy of AnomalyLikelihood. You will need
    # to re-optimize the thresholds when running with this setting.
    self.useLikelihood      = True
    self.useSpatialAnomaly  = True
    self.verbose            = True

    # Set this to true if you want to use the optimization.
    # If true, it reads the parameters from ./params.json
    # If false, it reads the parameters from ./best_params.json
    self.use_optimization   = False

    ## internal members 
    # (listed here for easier understanding)
    # initialized in `initialize()`
    self.encTimestamp   = None
    self.encValue       = None
    self.sp             = None
    self.tm             = None
    self.anLike         = None
    # optional debug info
    self.enc_info       = None
    self.sp_info        = None
    self.tm_info        = None
    # internal helper variables:
    self.inputs_ = []
    self.iteration_ = 0

    # initialize pandaVis server
    if PANDA_VIS_ENABLED:
        pandaServer.Start()
        self.BuildPandaSystem(parameters_numenta_comparable)


  def getAdditionalHeaders(self):
    """Returns a list of strings."""
    return ["raw_score"] #TODO optional: add "prediction"


  def handleRecord(self, inputData):
    """Returns a tuple (anomalyScore, rawScore).

    @param inputData is a dict {"timestamp" : Timestamp(), "value" : float}

    @return tuple (anomalyScore, <any other fields specified in `getAdditionalHeaders()`>, ...)
    """
    # Send it to Numenta detector and get back the results
    return self.modelRun(inputData["timestamp"], inputData["value"]) 



  def initialize(self):
    # toggle parameters here
    if self.use_optimization:
      parameters = get_params('params.json')
    else:
      parameters = parameters_numenta_comparable

    # setup spatial anomaly
    if self.useSpatialAnomaly:
      # Keep track of value range for spatial anomaly detection
      self.minVal = None
      self.maxVal = None

    ## setup Enc, SP, TM, Likelihood
    # Make the Encoders.  These will convert input data into binary representations.
    self.encTimestamp = DateEncoder(timeOfDay= parameters["enc"]["time"]["timeOfDay"],
                                    weekend  = parameters["enc"]["time"]["weekend"])

    scalarEncoderParams            = RDSE_Parameters()
    scalarEncoderParams.size       = parameters["enc"]["value"]["size"]
    scalarEncoderParams.sparsity   = parameters["enc"]["value"]["sparsity"]
    scalarEncoderParams.resolution = parameters["enc"]["value"]["resolution"]

    self.encValue = RDSE( scalarEncoderParams )
    encodingWidth = (self.encTimestamp.size + self.encValue.size)
    self.enc_info = Metrics( [encodingWidth], 999999999 )

    # Make the HTM.  SpatialPooler & TemporalMemory & associated tools.
    # SpatialPooler
    spParams = parameters["sp"]
    self.sp = SpatialPooler(
      inputDimensions            = (encodingWidth,),
      columnDimensions           = (spParams["columnCount"],),
      potentialPct               = spParams["potentialPct"],
      potentialRadius            = encodingWidth,
      globalInhibition           = True,
      localAreaDensity           = spParams["localAreaDensity"],
      synPermInactiveDec         = spParams["synPermInactiveDec"],
      synPermActiveInc           = spParams["synPermActiveInc"],
      synPermConnected           = spParams["synPermConnected"],
      boostStrength              = spParams["boostStrength"],
      wrapAround                 = True
    )
    self.sp_info = Metrics( self.sp.getColumnDimensions(), 999999999 )

    # TemporalMemory
    tmParams = parameters["tm"]
    self.tm = TemporalMemory(
      columnDimensions          = (spParams["columnCount"],),
      cellsPerColumn            = tmParams["cellsPerColumn"],
      activationThreshold       = tmParams["activationThreshold"],
      initialPermanence         = tmParams["initialPerm"],
      connectedPermanence       = spParams["synPermConnected"],
      minThreshold              = tmParams["minThreshold"],
      maxNewSynapseCount        = tmParams["newSynapseCount"],
      permanenceIncrement       = tmParams["permanenceInc"],
      permanenceDecrement       = tmParams["permanenceDec"],
      predictedSegmentDecrement = 0.0,
      maxSegmentsPerCell        = tmParams["maxSegmentsPerCell"],
      maxSynapsesPerSegment     = tmParams["maxSynapsesPerSegment"]
    )
    self.tm_info = Metrics( [self.tm.numberOfCells()], 999999999 )

    # setup likelihood, these settings are used in NAB
    if self.useLikelihood:
      anParams = parameters["anomaly"]["likelihood"]
      learningPeriod     = int(math.floor(self.probationaryPeriod / 2.0))
      self.anomalyLikelihood = AnomalyLikelihood(
                                 learningPeriod= learningPeriod,
                                 estimationSamples= self.probationaryPeriod - learningPeriod,
                                 reestimationPeriod= anParams["reestimationPeriod"])
    # Predictor
    # self.predictor = Predictor( steps=[1, 5], alpha=parameters["predictor"]['sdrc_alpha'] )
    # predictor_resolution = 1


  def modelRun(self, ts, val):
      """
         Run a single pass through HTM model

         @params ts - Timestamp
         @params val - float input value

         @return rawAnomalyScore computed for the `val` in this step
      """
      ## run data through our model pipeline: enc -> SP -> TM -> Anomaly
      self.inputs_.append( val )
      self.iteration_ += 1
      
      # 1. Encoding
      # Call the encoders to create bit representations for each value.  These are SDR objects.
      dateBits        = self.encTimestamp.encode(ts)
      valueBits       = self.encValue.encode(float(val))
      # Concatenate all these encodings into one large encoding for Spatial Pooling.
      encoding = SDR( self.encTimestamp.size + self.encValue.size ).concatenate([valueBits, dateBits])
      self.enc_info.addData( encoding )

      # 2. Spatial Pooler
      # Create an SDR to represent active columns, This will be populated by the
      # compute method below. It must have the same dimensions as the Spatial Pooler.
      activeColumns = SDR( self.sp.getColumnDimensions() )
      # Execute Spatial Pooling algorithm over input space.
      self.sp.compute(encoding, True, activeColumns)
      self.sp_info.addData( activeColumns )

      # 3. Temporal Memory
      # Execute Temporal Memory algorithm over active mini-columns.

      # the tm.compute() execute activateDendrites() - calculateAnomaly()/getPredictiveCells() - activateCells()
      # but to get insight into system with visTool, we need to have different execution order
      # Note: pandaVis retrieves synapses etc. by requesting data from sp/tm python objects, so data validity is crucial
      if PANDA_VIS_ENABLED:
        # activates cells in columns by TM algorithm (winners, bursting...)
        self.tm.activateCells(activeColumns, learn=True)
        # activateDendrites calculates active segments
        self.tm.activateDendrites(learn=True)
        # predictive cells are calculated directly from active segments
        predictiveCells = self.tm.getPredictiveCells()
      else:
        self.tm.compute(activeColumns, learn=True)

      self.tm_info.addData( self.tm.getActiveCells().flatten() )

      if PANDA_VIS_ENABLED:
        self.PandaUpdateData(ts, val, valueBits, dateBits , activeColumns, predictiveCells)

      # 4.1 (optional) Predictor #TODO optional
      #TODO optional: also return an error metric on predictions (RMSE, R2,...)

      # 4.2 Anomaly 
      # handle spatial, contextual (raw, likelihood) anomalies
      # -Spatial
      spatialAnomaly = 0.0 #TODO optional: make this computed in SP (and later improve)
      if self.useSpatialAnomaly:
        # Update min/max values and check if there is a spatial anomaly
        if self.minVal != self.maxVal:
          tolerance = (self.maxVal - self.minVal) * SPATIAL_TOLERANCE
          maxExpected = self.maxVal + tolerance
          minExpected = self.minVal - tolerance
          if val > maxExpected or val < minExpected:
            spatialAnomaly = 1.0
        if self.maxVal is None or val > self.maxVal:
          self.maxVal = val
        if self.minVal is None or val < self.minVal:
          self.minVal = val

      # -temporal (raw)
      raw = self.tm.anomaly
      temporalAnomaly = raw

      if self.useLikelihood:
        # Compute log(anomaly likelihood)
        like = self.anomalyLikelihood.anomalyProbability(val, raw, ts)
        logScore = self.anomalyLikelihood.computeLogLikelihood(like)
        temporalAnomaly = logScore #TODO optional: TM to provide anomaly {none, raw, likelihood}, compare correctness with the py anomaly_likelihood

      anomalyScore = max(spatialAnomaly, temporalAnomaly) # this is the "main" anomaly, compared in NAB

      # 5. print stats
      if self.verbose and self.iteration_ % 1000 == 0:
          # print(self.enc_info)
          # print(self.sp_info)
          # print(self.tm_info)
          pass

      if PANDA_VIS_ENABLED:
          pandaServer.BlockExecution()


      return (anomalyScore, raw)

  def BuildPandaSystem(self,modelParams):
      global serverData
      serverData = ServerData()
      serverData.HTMObjects["HTM1"] = dataHTMObject()
      serverData.HTMObjects["HTM1"].inputs["Value"] = dataInput()
      serverData.HTMObjects["HTM1"].inputs["TimeOfDay"] = dataInput()

      serverData.HTMObjects["HTM1"].layers["Layer1"] = dataLayer(
          modelParams["sp"]["columnCount"],
          modelParams["tm"]["cellsPerColumn"],
      )
      serverData.HTMObjects["HTM1"].layers["Layer1"].proximalInputs = ["Value","TimeOfDay"]


  def PandaUpdateData(self, timestamp, value, valueSDR, datetimeSDR, activeColumns, predictiveCells):

    pandaServer.currentIteration = self.iteration_ # update server's iteration number
    # do not update if we are running GOTO iteration command
    if (not pandaServer.cmdGotoIteration or (
            pandaServer.cmdGotoIteration and pandaServer.gotoIteration == pandaServer.currentIteration)):
      # ------------------HTMpandaVis----------------------
      # fill up values
      serverData.iterationNo = pandaServer.currentIteration
      serverData.HTMObjects["HTM1"].inputs["Value"].stringValue = "VALUE:" + str(value)
      serverData.HTMObjects["HTM1"].inputs["Value"].bits = valueSDR.sparse
      serverData.HTMObjects["HTM1"].inputs["Value"].count = valueSDR.size

      serverData.HTMObjects["HTM1"].inputs["TimeOfDay"].stringValue = "TIME OF DAY:" + str(timestamp)
      serverData.HTMObjects["HTM1"].inputs["TimeOfDay"].bits = datetimeSDR.sparse
      serverData.HTMObjects["HTM1"].inputs["TimeOfDay"].count = datetimeSDR.size

      serverData.HTMObjects["HTM1"].layers["Layer1"].activeColumns = activeColumns.sparse

      serverData.HTMObjects["HTM1"].layers["Layer1"].winnerCells = self.tm.getWinnerCells().sparse
      serverData.HTMObjects["HTM1"].layers["Layer1"].activeCells = self.tm.getActiveCells().sparse
      serverData.HTMObjects["HTM1"].layers["Layer1"].predictiveCells = predictiveCells.sparse

      # print("ACTIVECOLS:"+str(serverData.HTMObjects["HTM1"].layers["SensoryLayer"].activeColumns ))
      # print("WINNERCELLS:"+str(serverData.HTMObjects["HTM1"].layers["SensoryLayer"].winnerCells))
      # print("ACTIVECELLS:" + str(serverData.HTMObjects["HTM1"].layers["SensoryLayer"].activeCells))
      # print("PREDICTCELLS:"+str(serverData.HTMObjects["HTM1"].layers["SensoryLayer"].predictiveCells))

      pandaServer.serverData = serverData

      pandaServer.spatialPoolers["HTM1"] = self.sp
      pandaServer.temporalMemories["HTM1"] = self.tm
      pandaServer.NewStateDataReady()


# WHILE USING PANDAVIS
# SPECIFY HERE FOR WHAT DATA YOU WANT TO RUN THIS DETECTOR
if PANDA_VIS_ENABLED:
  import pandas as pd
  import os.path as path
  from nab.corpus import Corpus
  dataDir =  path.abspath(path.join(__file__ ,"../../../..","data"))

  corpus = Corpus(dataDir)

  dataSet = corpus.dataFiles["artificialWithAnomaly/art_daily_flatmiddle.csv"]

  detector = HtmcoreDetector(dataSet=dataSet,
                  probationaryPercent=0.15)

  detector.initialize()

  detector.run()
