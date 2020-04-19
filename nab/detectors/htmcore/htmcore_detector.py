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
        "enc": {
            "value": {
                # "resolution": 0.9, calculate by max(0.001, (maxVal - minVal) / numBuckets) where numBuckets = 130
                "size": 400,
                "activeBits": 21, #results very sensitive to the size/active bits in the input encoders
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
            "globalInhibition": True,
            "localAreaDensity": 0.025,  # optimize this one
            "stimulusThreshold": 2,
            "synPermInactiveDec": 0.0005,
            "synPermActiveInc": 0.003,
            "synPermConnected": 0.2,
            "boostStrength": 0.0,
            "wrapAround": True,
            "minPctOverlapDutyCycle": 0.001,
            "dutyCyclePeriod": 1000,
            "seed": 5,
        },
        "tm": {
            #"columnDimensions": 2048, #must match SP
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
    self.encTimestamp = DateEncoder(timeOfDay=parameters["enc"]["time"]["timeOfDay"])

    scalarEncoderParams = EncParameters()
    scalarEncoderParams.size = parameters["enc"]["value"]["size"]
    scalarEncoderParams.activeBits = parameters["enc"]["value"]["activeBits"]
    # scalarEncoderParams.resolution = parameters["enc"]["value"]["resolution"]
    scalarEncoderParams.resolution = max(0.001, (self.inputMax - self.inputMin) / 130)
    #scalarEncoderParams.seed = parameters["enc"]["value"]["seed"]
    self.encValue = Encoder(scalarEncoderParams)

    self.encValue = Encoder( scalarEncoderParams )
    encodingWidth = (self.encTimestamp.size + self.encValue.size)
    self.enc_info = Metrics( [encodingWidth], 999999999 )

    # Make the HTM.  SpatialPooler & TemporalMemory & associated tools.
    # SpatialPooler
    spParams = parameters["sp"]
    self.sp = SpatialPooler(
        inputDimensions=(encodingWidth,),
        columnDimensions=(spParams["columnDimensions"],),
        potentialRadius=encodingWidth,
        potentialPct=spParams["potentialPct"],
        globalInhibition=spParams["globalInhibition"],
        localAreaDensity=spParams["localAreaDensity"],
        stimulusThreshold=spParams["stimulusThreshold"],
        synPermInactiveDec=spParams["synPermInactiveDec"],
        synPermActiveInc=spParams["synPermActiveInc"],
        synPermConnected=spParams["synPermConnected"],
        boostStrength=spParams["boostStrength"],
        wrapAround=spParams["wrapAround"],
        minPctOverlapDutyCycle=spParams["minPctOverlapDutyCycle"],
        dutyCyclePeriod=spParams["dutyCyclePeriod"],
        #seed=spParams["seed"],
    )
    self.sp_info = Metrics( self.sp.getColumnDimensions(), 999999999 )

    # TemporalMemory
    tmParams = parameters["tm"]
    self.tm = TemporalMemory(
        columnDimensions=(spParams["columnDimensions"],),
        cellsPerColumn=tmParams["cellsPerColumn"],
        activationThreshold=tmParams["activationThreshold"],
        initialPermanence=tmParams["initialPermanence"],
        connectedPermanence=tmParams["connectedPermanence"],
        minThreshold=tmParams["minThreshold"],
        maxNewSynapseCount=tmParams["maxNewSynapseCount"],
        permanenceIncrement=tmParams["permanenceIncrement"],
        permanenceDecrement=tmParams["permanenceDecrement"],
        predictedSegmentDecrement=tmParams["predictedSegmentDecrement"],
        maxSegmentsPerCell=tmParams["maxSegmentsPerCell"],
        maxSynapsesPerSegment=tmParams["maxSynapsesPerSegment"],
        #seed=tmParams["seed"]
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
