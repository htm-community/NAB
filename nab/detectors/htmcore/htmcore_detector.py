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

## parameters to initialize our HTM model (encoder, SP, TM, AnomalyLikelihood)
# TODO optional: optimize these params, either manually and/or swarming. But first keep comparable to numenta_detector
default_parameters = {
  # there are 2 (3) encoders: "value" (RDSE) & "time" (DateTime weekend, timeOfDay)
  'enc': {
    "value" : #RDSE for value
      {'resolution': 0.001, 'size': 700, 'sparsity': 0.02},
    "time":   #DateTime for timestamps
      {'timeOfDay': (30, 1), 'weekend': 21}},
  'predictor': {'sdrc_alpha': 0.1},
  'sp': {
    'boostStrength': 3.0,
    'columnCount': 1638,
    'localAreaDensity': 0.04395604395604396,
    'potentialPct': 0.85,
    'synPermActiveInc': 0.04,
    'synPermConnected': 0.14,
    'synPermInactiveDec': 0.006},
  'tm': {
    'activationThreshold': 17,
    'cellsPerColumn': 13,
    'initialPerm': 0.21,
    'maxSegmentsPerCell': 128,
    'maxSynapsesPerSegment': 64,
    'minThreshold': 10,
    'newSynapseCount': 32,
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
    self.useSpatialAnomaly  = True
    self.verbose            = False

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
    parameters = default_parameters

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
    self.predictor = Predictor( steps=[1, 5], alpha=parameters["predictor"]['sdrc_alpha'] )
    predictor_resolution = 1



  def _setupEncoderParams(self, encoderParams):
    # The encoder must expect the NAB-specific datafile headers #FIXME can be removed?
    encoderParams["timestamp_dayOfWeek"] = encoderParams.pop("c0_dayOfWeek")
    encoderParams["timestamp_timeOfDay"] = encoderParams.pop("c0_timeOfDay")
    encoderParams["timestamp_timeOfDay"]["fieldname"] = "timestamp"
    encoderParams["timestamp_timeOfDay"]["name"] = "timestamp"
    encoderParams["timestamp_weekend"] = encoderParams.pop("c0_weekend")
    encoderParams["value"] = encoderParams.pop("c1")
    encoderParams["value"]["fieldname"] = "value"
    encoderParams["value"]["name"] = "value"

    self.sensorParams = encoderParams["value"]

  def modelRun(self, ts, val):
      """
         Run a single pass through HTM model

         @params ts - Timestamp
         @params val - float input value

         @return rawAnomalyScore computed for the `val` in this step
      """
      ## run data through our model pipeline: enc -> SP -> TM -> Anomaly
      self.inputs_.append( val )
      
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
      self.tm_info.addData( self.tm.getActiveCells().flatten() ) #FIXME for anomaly, should we use active cells, or winner cells? And also convert to columns!

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

      return (anomalyScore, raw)
