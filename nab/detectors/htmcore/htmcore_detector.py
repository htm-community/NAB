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

# htm.core imports
from htm.bindings.algorithms import SpatialPooler   as SP
from htm.bindings.algorithms import TemporalMemory  as TM
from htm.bindings.algorithms import Predictor

from htm.algorithms.anomaly_likelihood import AnomalyLikelihood
from nab.detectors.base import AnomalyDetector

# Fraction outside of the range of values seen so far that will be considered
# a spatial anomaly regardless of the anomaly likelihood calculation. This
# accounts for the human labelling bias for spatial values larger than what
# has been seen so far.
SPATIAL_TOLERANCE = 0.05



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
    self.useLikelihood = True
    self.useSpatialAnomaly = True


  def getAdditionalHeaders(self):
    """Returns a list of strings."""
    return ["raw_score"] #TODO add "prediction"


  def handleRecord(self, inputData):
    """Returns a tuple (anomalyScore, rawScore).

    @param inputData is a dict {"timestamp" : Timestamp(), "value" : float}

    @return tuple (anomalyScore, <any other fields specified in `getAdditionalHeaders()`>, ...)
    """
    # Send it to Numenta detector and get back the results
    result = self.modelRun(inputData["timestamp"], inputData["value"]) 

    # Get the value
    value = inputData["value"]

    # Retrieve the anomaly score and write it to a file
    rawScore = result

    ## handle anomalies: raw -> ?spatial or ?likelihood -> finalScore
    spatialAnomaly = 0.0 #TODO make this computed in SP (and later improve)
    if self.useSpatialAnomaly:
      # Update min/max values and check if there is a spatial anomaly
      if self.minVal != self.maxVal:
        tolerance = (self.maxVal - self.minVal) * SPATIAL_TOLERANCE
        maxExpected = self.maxVal + tolerance
        minExpected = self.minVal - tolerance
        if value > maxExpected or value < minExpected:
          spatialAnomaly = 1.0
      if self.maxVal is None or value > self.maxVal:
        self.maxVal = value
      if self.minVal is None or value < self.minVal:
        self.minVal = value

    if self.useLikelihood:
      # Compute log(anomaly likelihood)
      anomalyScore = self.anomalyLikelihood.anomalyProbability(inputData["value"], rawScore, inputData["timestamp"])
      logScore = self.anomalyLikelihood.computeLogLikelihood(anomalyScore)
      temporalAnomaly = logScore #TODO TM to provide anomaly {none, raw, likelihood}, compare correctness with the py anomaly_likelihood 
    else:
      temporalAnomaly = rawScore

    anomalyScore = max(spatialAnomaly, temporalAnomaly)

    return (anomalyScore, rawScore)


  def initialize(self):
    # Get config params, setting the RDSE resolution
    rangePadding = abs(self.inputMax - self.inputMin) * 0.2
    minVal=self.inputMin-rangePadding
    maxVal=self.inputMax+rangePadding
    minResolution=0.001 #TODO there params should form default_params for encoder etc

    # setup anomaly likelihood
    if self.useLikelihood:
      numentaLearningPeriod = int(math.floor(self.probationaryPeriod / 2.0))
      self.anomalyLikelihood = AnomalyLikelihood( #TODO make these default for py anomaly_likelihood? as NAB is likely tuned for best Likelihood!
        learningPeriod=numentaLearningPeriod,
        estimationSamples=self.probationaryPeriod-numentaLearningPeriod,
        reestimationPeriod=100
      )

    # setup spatial anomaly
    if self.useSpatialAnomaly:
      # Keep track of value range for spatial anomaly detection
      self.minVal = None
      self.maxVal = None



  def _setupEncoderParams(self, encoderParams):
    # The encoder must expect the NAB-specific datafile headers
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
      #FIXME do enc->SP->TM->AN here
      return 0.0
