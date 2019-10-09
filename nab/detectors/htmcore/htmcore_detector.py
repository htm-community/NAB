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

import math
import datetime

# htm.core imports
from htm.bindings.sdr import SDR, Metrics
from htm.encoders.rdse import RDSE as Encoder, RDSE_Parameters as EncParameters
from htm.encoders.date import DateEncoder
from htm.bindings.algorithms import SpatialPooler
from htm.bindings.algorithms import TemporalMemory
from htm.algorithms.anomaly_likelihood import AnomalyLikelihood
from htm.bindings.algorithms import Predictor

from nab.detectors.base import AnomalyDetector

parameters_numenta_comparable = {
  # there are 2 (3) encoders: "value" (RDSE) & "time" (DateTime weekend, timeOfDay)
  'enc': {
    "value" : # RDSE for value
      {'resolution': 0.9,
        'size': 400,
        'sparsity': 0.10
      },
    "time": {  # DateTime for timestamps
        # fields with 1 bit encoding are effectively disabled (have no implact on SP, take little input space)
        # it is possible to totaly ignore the timestamp (this encoder) input, and results are not much worse.
        'season': (1, 30), # represents months, each "season" is 30 days
        'timeOfDay': (1, 1), #40 on bits for each hour
        'dayOfWeek': 20, #this field has most significant impact, as incorporates (day + hours)
        'weekend': 0, #TODO try impact of weekend
        }},
  'predictor': {'sdrc_alpha': 0.1},
  'sp': {
    'boostStrength': 0.0,
    'columnCount': 1024*1,
    'localAreaDensity': 40/(1024*1), #TODO accuracy extremely sensitive to this value (??)
    'potentialRadius': 999999, # 2 * 20 -> 40 of 400 (input size) = 10% #TODO this is global all-to-all connection, try more local
    'potentialPct': 0.4,
    'stimulusThreshold': 4,
    'synPermActiveInc': 0.05,
    'synPermConnected': 0.5,
    'synPermInactiveDec': 0.01},
  'tm': {
    'activationThreshold': 13,
    'cellsPerColumn': 4,
    'initialPerm': 0.51,
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
    self.verbose            = True

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
    #parameters = default_parameters
    parameters = parameters_numenta_comparable


    ## setup Enc, SP, TM, Likelihood
    # Make the Encoders.  These will convert input data into binary representations.
    self.encTimestamp = DateEncoder(timeOfDay= parameters["enc"]["time"]["timeOfDay"],
                                    weekend  = parameters["enc"]["time"]["weekend"],
                                    season   = parameters["enc"]["time"]["season"],
                                    dayOfWeek= parameters["enc"]["time"]["dayOfWeek"])

    scalarEncoderParams            = EncParameters()
    scalarEncoderParams.size       = parameters["enc"]["value"]["size"]
    scalarEncoderParams.sparsity   = parameters["enc"]["value"]["sparsity"]
    scalarEncoderParams.resolution = parameters["enc"]["value"]["resolution"]

    self.encValue = Encoder( scalarEncoderParams )
    encodingWidth = (self.encTimestamp.size + self.encValue.size)
    self.enc_info = Metrics( [encodingWidth], 999999999 )

    # Make the HTM.  SpatialPooler & TemporalMemory & associated tools.
    # SpatialPooler
    spParams = parameters["sp"]
    self.sp = SpatialPooler(
      inputDimensions            = (encodingWidth,),
      columnDimensions           = (spParams["columnCount"],),
      potentialPct               = spParams["potentialPct"],
      potentialRadius            = spParams["potentialRadius"],
      globalInhibition           = True,
      localAreaDensity           = spParams["localAreaDensity"],
      stimulusThreshold          = spParams["stimulusThreshold"],
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
      self.tm.compute(activeColumns, learn=True)
      self.tm_info.addData( self.tm.getActiveCells().flatten() )

      # 4.1 (optional) Predictor #TODO optional
      #TODO optional: also return an error metric on predictions (RMSE, R2,...)

      # 4.2 Anomaly 
      # handle contextual (raw, likelihood) anomalies
      # -temporal (raw)
      raw = self.tm.anomaly
      temporalAnomaly = raw

      if self.useLikelihood:
        # Compute log(anomaly likelihood)
        like = self.anomalyLikelihood.anomalyProbability(val, raw, ts)
        logScore = self.anomalyLikelihood.computeLogLikelihood(like)
        temporalAnomaly = logScore #TODO optional: TM to provide anomaly {none, raw, likelihood}, compare correctness with the py anomaly_likelihood

      anomalyScore = temporalAnomaly # this is the "main" anomaly, compared in NAB

      # 5. print stats
      if self.verbose and self.iteration_ % 1000 == 0:
          print(self.enc_info)
          print(self.sp_info)
          print(self.tm_info)
          pass

      return (anomalyScore, raw)
